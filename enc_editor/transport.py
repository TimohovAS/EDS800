"""Modbus RTU transport: everything that talks to the drive, and nothing else.

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
from .codecs import READ_ERROR

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
    """Split parameters into address-contiguous Modbus read batches."""
    ordered = sorted(parameters, key=lambda parameter: parameter["address"])
    chunks: list[list[Mapping[str, Any]]] = []
    current: list[Mapping[str, Any]] = []
    for parameter in ordered:
        if current and (
            parameter["address"] != current[-1]["address"] + 1
            or len(current) >= maximum_size
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
            try:
                result = self.read_registers(chunk[0]["address"], len(chunk))
                if not result.isError() and len(result.registers) == len(chunk):
                    values.update(
                        {
                            parameter["code"]: value
                            for parameter, value in zip(chunk, result.registers)
                        }
                    )
                    if progress:
                        progress(len(values), total)
                    continue
            except ModbusException as exc:
                logger.warning("Batch read failed at 0x%04X: %s", chunk[0]["address"], exc)

            for parameter in chunk:
                self.raise_if_cancelled()
                try:
                    result = self.read_register(parameter["address"])
                    values[parameter["code"]] = (
                        result.registers[0] if not result.isError() else READ_ERROR
                    )
                except ModbusException:
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
        failed: list[tuple[str, str]] = []
        total = len(targets)
        for index, (parameter, raw_value, displayed) in enumerate(targets, start=1):
            self.raise_if_cancelled()
            code = parameter["code"]
            try:
                result = self.write_register(parameter["address"], raw_value)
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
        return {"written": written, "failed": failed}
