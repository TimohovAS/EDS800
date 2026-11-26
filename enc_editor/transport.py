"""Modbus RTU transport and protocol selection for a serial drive session.

The link is deliberately free of UI and translation concerns so it can be
driven from a worker thread or a script.  Long operations accept a progress
callback and a cancel event.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Iterable, Mapping, Sequence

from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusException

from .catalog import LinkSettings
from .codecs import READ_ERROR, Problem, context_codes, format_value, raw_maximum, scale_problem, validate_value
from .diagnostics import ResetRefused

logger = logging.getLogger(__name__)

Progress = Callable[[int, int], None]


class TaskCancelled(RuntimeError):
    """Raised inside a worker when the user cancels an operation."""


class LinkError(RuntimeError):
    """The serial port could not be opened."""

    def __init__(self, port: str):
        self.port = port
        super().__init__(f"Could not open {port}")


def contiguous_chunks(
    parameters: Iterable[Mapping[str, Any]], maximum_size: int = 50
) -> list[list[Mapping[str, Any]]]:
    """Batch adjacent register spans; indexed values always stand alone."""
    ordered = sorted(parameters, key=lambda parameter: parameter["address"])
    chunks: list[list[Mapping[str, Any]]] = []
    current: list[Mapping[str, Any]] = []
    for parameter in ordered:
        if current and (
            parameter["address"] != current[-1]["address"] + current[-1].get("register_count", 1)
            or sum(p.get("register_count", 1) for p in current) + parameter.get("register_count", 1) > maximum_size
            or parameter.get("array_index") is not None
            or current[-1].get("array_index") is not None
        ):
            chunks.append(current)
            current = []
        current.append(parameter)
    if current:
        chunks.append(current)
    return chunks


class ModbusLink:
    """One serial conversation with one inverter."""

    def __init__(
        self,
        port: str,
        device_id: int,
        settings: LinkSettings,
        cancel: threading.Event | None = None,
    ):
        self.port = port
        self.device_id = int(device_id)
        self.settings = settings
        self.cancel = cancel or threading.Event()
        self.client = None

    # -- lifecycle -----------------------------------------------------
    def open(self) -> "ModbusLink":
        client = ModbusSerialClient(
            port=self.port,
            baudrate=self.settings.baudrate,
            parity=self.settings.parity,
            stopbits=self.settings.stopbits,
            bytesize=self.settings.bytesize,
            timeout=self.settings.timeout,
        )
        if not client.connect():
            raise LinkError(self.port)
        self.client = client
        return self

    def close(self) -> None:
        if self.client is not None:
            try:
                self.client.close()
            except Exception:  # a failed close must never mask the real error
                logger.debug("Closing the Modbus client failed", exc_info=True)
            self.client = None

    def __enter__(self) -> "ModbusLink":
        return self.open()

    def __exit__(self, *exception) -> None:
        self.close()

    def raise_if_cancelled(self) -> None:
        if self.cancel.is_set():
            raise TaskCancelled

    # -- raw register access -------------------------------------------
    # ``device_id`` is the argument name since pymodbus 3.10; see requirements.
    def read_registers(self, address: int, count: int = 1):
        return self.client.read_holding_registers(
            address=address, count=count, device_id=self.device_id
        )

    def read_register(self, address: int):
        return self.read_registers(address, 1)

    def write_register(self, address: int, value: int):
        return self.client.write_register(
            address=address, value=value, device_id=self.device_id
        )

    def reset_fc_trip(self, status_parameter: Mapping[str, Any]) -> None:
        """Pulse only FC control bit 7 (one-based coil 8), never Start/REF.

        Do not enable a previously ignored control word: that could activate
        stale commands, relay outputs or another setup. An active RUN/JOG or
        trip lock also requires operator intervention, not a software reset.
        """
        self.raise_if_cancelled()
        status = self.read_parameter(status_parameter)
        if status == READ_ERROR:
            raise ResetRefused("diag.reset_read_error")
        if status & (1 << 6):
            raise ResetRefused("diag.reset_locked")
        if status & ((1 << 11) | (1 << 12)):
            raise ResetRefused("diag.reset_running")
        coils = self.client.read_coils(address=0, count=16, device_id=self.device_id)
        if coils.isError() or len(coils.bits) < 16:
            raise ResetRefused("diag.reset_read_error")
        if coils.bits[6] or coils.bits[8]:
            raise ResetRefused("diag.reset_running")
        if not coils.bits[10]:
            raise ResetRefused("diag.reset_ignored")
        self.raise_if_cancelled()

        def reset_bit(value):
            result = self.client.write_coil(address=7, value=value, device_id=self.device_id)
            if result.isError():
                raise ModbusException(f"FC reset coil: {result}")

        # Clear first so even a previously asserted reset produces a new edge.
        reset_bit(False)
        self.raise_if_cancelled()
        try:
            reset_bit(True)
            self.cancel.wait(0.1)
        finally:
            # The slave may have received ON even if its response was lost.
            # Cleanup must run after errors/cancellation as well as success.
            reset_bit(False)
        self.raise_if_cancelled()

    def _select_index(self, parameter: Mapping[str, Any]) -> None:
        index = parameter.get("array_index")
        if index is None:
            return
        if self.settings.index_register is None:
            raise ValueError("Indexed parameter requires an index register")
        result = self.write_register(self.settings.index_register, index)
        if result.isError():
            raise ModbusException(f"Cannot select index {index}: {result}")

    @staticmethod
    def _unpack(registers: Sequence[int]) -> int:
        value = 0
        for word in registers:
            value = (value << 16) | word
        return value

    def read_parameter(self, parameter: Mapping[str, Any]):
        self.raise_if_cancelled()
        self._select_index(parameter)
        count = parameter.get("register_count", 1)
        result = self.read_registers(parameter["address"], count)
        if result.isError() or len(result.registers) != count:
            return READ_ERROR
        return self._unpack(result.registers)

    # -- parameter level ------------------------------------------------
    def read_values(
        self,
        parameters: Sequence[Mapping[str, Any]],
        progress: Progress | None = None,
        maximum_size: int | None = None,
    ) -> dict[str, Any]:
        """Read parameters in batches, falling back to single reads on error."""
        values: dict[str, Any] = {}
        total = len(parameters)
        batch_size = maximum_size or self.settings.max_read_registers
        for chunk in contiguous_chunks(parameters, batch_size):
            self.raise_if_cancelled()
            count = sum(p.get("register_count", 1) for p in chunk)
            try:
                self._select_index(chunk[0])
                result = self.read_registers(chunk[0]["address"], count)
                if not result.isError() and len(result.registers) == count:
                    offset = 0
                    for parameter in chunk:
                        width = parameter.get("register_count", 1)
                        values[parameter["code"]] = self._unpack(result.registers[offset:offset + width])
                        offset += width
                    if progress:
                        progress(len(values), total)
                    continue
            except (ValueError, ModbusException) as exc:
                logger.warning("Batch read failed at 0x%04X: %s", chunk[0]["address"], exc)

            for parameter in chunk:
                self.raise_if_cancelled()
                try:
                    values[parameter["code"]] = self.read_parameter(parameter)
                except (ValueError, ModbusException):
                    values[parameter["code"]] = READ_ERROR
            if progress:
                progress(len(values), total)
        return values

    def write_values(
        self,
        targets: Sequence[tuple[Mapping[str, Any], int, str]],
        progress: Progress | None = None,
    ) -> dict[str, Any]:
        """Write ``(parameter, raw_value, displayed_text)`` triples."""
        written: dict[str, int] = {}
        failed: list[tuple[str, str | Problem]] = []
        total = len(targets)
        contexts = {}
        for parameter, _raw, _text in targets:
            providers = context_codes(parameter)
            if not providers:
                continue
            required = parameter.get("write_context") or ([parameter["scale_context"]] if parameter.get("scale_context") else [])
            if scale_problem(parameter) or {c["code"] for c in required} != set(providers):
                problem = Problem("valid.scale_unknown", {"code": providers[0]})
                return {"written": {}, "failed": [(p["code"], problem) for p, _, _ in targets]}
            for context in required:
                contexts[context["code"]] = context
        planned = {p["code"]: raw for p, raw, _ in targets}
        observed = {}
        preserved = [item for item in targets if item[0].get("preserve_mask") or item[0].get("verify_current")]

        def outcome(written, failed):
            result = {"written": written, "failed": failed}
            if contexts or preserved:
                result["context"] = dict(observed)
            return result

        def context_problem(context):
            code = context["code"]
            if code not in observed:
                try:
                    observed[code] = self.read_parameter(context)
                except (ValueError, ModbusException):
                    observed[code] = READ_ERROR
            if observed[code] != context["value"]:
                return Problem("valid.scale_changed", {"code": code})
            return None

        # Check before ANY writes, including persistence/other parameters. A
        # cached/file selector is not proof of the current keypad setting.
        for code, context in contexts.items():
            problem = context_problem(context)
            if problem and (observed[code] == READ_ERROR or planned.get(code) != context["value"]):
                return outcome({}, [(p["code"], problem) for p, _, _ in targets])
        for parameter, raw, _text in preserved:
            code = parameter["code"]
            try:
                observed[code] = self.read_parameter(parameter)
            except (ValueError, ModbusException):
                observed[code] = READ_ERROR
            mask = parameter.get("preserve_mask", 0)
            if observed[code] == READ_ERROR or (observed[code] & mask) != (raw & mask):
                problem = Problem("valid.preserved_bits", {"code": code})
                return outcome({}, [(p["code"], problem) for p, _, _ in targets])
            if parameter.get("verify_current") and validate_value(parameter, format_value(observed[code], parameter)):
                problem = Problem("valid.live_value", {"code": code})
                return outcome({}, [(p["code"], problem) for p, _, _ in targets])
        if targets and self.settings.persist_coil is not None:
            self.raise_if_cancelled()
            try:
                result = self.client.write_coil(
                    address=self.settings.persist_coil, value=True, device_id=self.device_id
                )
                if result.isError():
                    raise ModbusException(f"Cannot enable persistent storage: {result}")
            except ModbusException as exc:
                return {"written": {}, "failed": [(p["code"], str(exc)) for p, _, _ in targets]}
        # Address/protocol/baud changes can disconnect the current session.
        ordered = sorted(targets, key=lambda item: (
            item[0].get("write_last", 0), 0 if item[0]["code"] in contexts else 1))
        for index, (parameter, raw_value, displayed) in enumerate(ordered, start=1):
            self.raise_if_cancelled()
            code = parameter["code"]
            if code in contexts:
                # Even a failed write may have reached the slave. Read back
                # the selector after its write before sending dependent times.
                observed.pop(code, None)
            required = parameter.get("write_context") or ([parameter["scale_context"]] if parameter.get("scale_context") else [])
            problem = next((problem for context in required if (problem := context_problem(context))), None)
            if problem:
                failed.append((code, problem))
                if progress:
                    progress(index, total)
                continue
            try:
                if parameter.get("read_only"):
                    raise ValueError("Read-only parameter")
                if not 0 <= raw_value <= raw_maximum(parameter):
                    raise ValueError("Value exceeds parameter register width")
                self._select_index(parameter)
                width = parameter.get("register_count", 1)
                if width == 1:
                    result = self.write_register(parameter["address"], raw_value)
                else:
                    words = [(raw_value >> (16 * shift)) & 0xFFFF for shift in reversed(range(width))]
                    result = self.client.write_registers(
                        address=parameter["address"], values=words, device_id=self.device_id
                    )
                if result.isError():
                    failed.append((code, str(result)))
                    logger.error("Failed to write %s", code)
                else:
                    written[code] = raw_value
                    logger.info("Written %s: %s (from %s)", code, raw_value, displayed)
            except (ValueError, ModbusException) as exc:
                failed.append((code, str(exc)))
                logger.error("Error writing %s: %s", code, exc)
            if progress:
                progress(index, total)
        return outcome(written, failed)


def create_link(port, device_id, settings, cancel=None):
    """Select a transport explicitly; never probe/change the drive protocol."""
    if settings.protocol == "modbus_rtu":
        return ModbusLink(port, device_id, settings, cancel)
    if settings.protocol == "danfoss_fc":
        from .fc_protocol import FCLink
        return FCLink(port, device_id, settings, cancel)
    raise ValueError(f"Unsupported serial protocol: {settings.protocol}")
