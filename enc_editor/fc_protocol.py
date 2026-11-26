"""Danfoss FC parameter channel (MG02K402, sections 8.4–8.5).

All parameter telegrams carry CTW=0 / REF=0. Data-valid bit 10 is therefore
clear: reading/writing parameters never sends a valid motor control command.
No process-control or remote-reset API is exposed by this transport.
"""
from __future__ import annotations

from functools import reduce
import logging
from operator import xor
import threading
import time

import serial

from .codecs import READ_ERROR, raw_maximum
from .diagnostics import ResetRefused
from .transport import LinkError, TaskCancelled

logger = logging.getLogger(__name__)


class FCProtocolError(ConnectionError):
    def __init__(self, key: str, **params):
        self.key, self.params = key, params
        super().__init__(f"{key}: {params}" if params else key)


def parameter_number(parameter) -> int:
    group, number = parameter["code"].split("[")[0].split("-")
    pnu = int(group) * 100 + int(number)
    if not 0 <= pnu <= 0xFFF:
        raise ValueError("FC parameter number is out of range")
    return pnu


def build_request(device_id: int, parameter, command: int = 1, value: int = 0) -> bytes:
    """Encode a 16-byte parameter telegram, not a process-control telegram."""
    if not 1 <= device_id <= 126:
        raise ValueError("FC address must be 1–126; broadcast is forbidden")
    if command not in (1, 13, 14, 15):
        raise ValueError("Unsupported FC parameter command")
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("FC value exceeds 32 bits")
    index = parameter.get("array_index", 0)
    if not 0 <= index <= 255:
        raise ValueError("FC subindex must fit one byte")
    if command == 15:
        index |= 0x0400  # Read text: IND high byte = 4, low byte = subindex.
    pke = (command << 12) | parameter_number(parameter)
    data = pke.to_bytes(2, "big") + index.to_bytes(2, "big") + value.to_bytes(4, "big")
    data += b"\0\0\0\0"  # CTW=0 (Data valid=0), REF=0; never Start.
    packet = bytes((2, len(data) + 2, device_id | 0x80)) + data
    return packet + bytes((reduce(xor, packet, 0),))


def parse_response(frame: bytes, request: bytes, parameter) -> int:
    """Validate identity, framing and checksum before returning a packed value."""
    if len(frame) < 12 or frame[0] != 2 or frame[1] + 2 != len(frame) or reduce(xor, frame, 0):
        raise FCProtocolError("fc.bad_frame")
    if frame[2] != request[2] or (int.from_bytes(frame[3:5], "big") & 0xFFF) != parameter_number(parameter) or frame[5:7] != request[5:7]:
        raise FCProtocolError("fc.wrong_response")
    command = frame[3] >> 4
    if command == 7:
        if len(frame) != 16:
            raise FCProtocolError("fc.bad_frame")
        raise FCProtocolError("fc.rejected", code=int.from_bytes(frame[7:11], "big"))
    if parameter["encoding"] == "text":
        if command != 15:
            raise FCProtocolError("fc.bad_frame")
        text = frame[7:-5]  # Text is followed by STW/MAV and BCC.
        width = parameter["register_count"] * 2
        if len(text) > width:
            raise FCProtocolError("fc.bad_frame")
        return int.from_bytes(text.ljust(width, b"\0"), "big")
    if len(frame) != 16 or command not in (1, 2):
        raise FCProtocolError("fc.bad_frame")
    value = int.from_bytes(frame[9:11] if command == 1 else frame[7:11], "big")
    if value > raw_maximum(parameter):
        raise FCProtocolError("fc.bad_frame")
    request_command = request[3] >> 4
    if request_command in (13, 14):
        expected_command = 2 if request_command == 13 else 1
        if command != expected_command or value != int.from_bytes(request[7:11], "big"):
            raise FCProtocolError("fc.write_unverified")
    return value


class FCLink:
    """One point-to-point FC parameter session. Writes are never retried."""
    def __init__(self, port, device_id, settings, cancel=None):
        if not 1 <= int(device_id) <= 126:
            raise ValueError("FC address must be 1–126")
        if settings.bytesize != 8 or settings.parity != "E" or settings.stopbits != 1:
            raise ValueError("Danfoss FC requires 8E1")
        self.port, self.device_id, self.settings = port, int(device_id), settings
        self.cancel = cancel or threading.Event()
        self.client = None

    def open(self):
        try:
            self.client = serial.Serial(
                port=self.port, baudrate=self.settings.baudrate, bytesize=8,
                parity="E", stopbits=1, timeout=min(self.settings.timeout, 0.05),
                write_timeout=self.settings.timeout,
            )
        except serial.SerialException as exc:
            raise LinkError(self.port) from exc
        return self

    def close(self):
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                logger.debug("Closing the FC serial port failed", exc_info=True)
            finally:
                self.client = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exception):
        self.close()

    def raise_if_cancelled(self):
        if self.cancel.is_set():
            raise TaskCancelled

    def _exchange(self, request, parameter):
        self.raise_if_cancelled()
        # Allow adapter turnaround; check cancellation before any transmission.
        self.cancel.wait(0.01)
        self.raise_if_cancelled()
        self.client.reset_input_buffer()
        if self.client.write(request) != len(request):
            raise FCProtocolError("fc.short_write")
        self.client.flush()
        deadline = time.monotonic() + self.settings.timeout
        buffer = bytearray()
        last_error = None
        while time.monotonic() < deadline:
            self.raise_if_cancelled()
            buffer.extend(self.client.read(min(max(self.client.in_waiting, 1), 256)))
            while buffer:
                start = buffer.find(b"\x02")
                if start < 0:
                    buffer.clear()
                    break
                del buffer[:start]
                if len(buffer) < 2:
                    break
                size = buffer[1] + 2
                if size < 12:
                    del buffer[0]
                    last_error = FCProtocolError("fc.bad_frame")
                    continue
                if len(buffer) < size:
                    break
                frame = bytes(buffer[:size])
                del buffer[:size]
                if frame == request:
                    # Some adapters echo TX. An exact zero-value read echo is
                    # indistinguishable from a real reply: fail closed unless
                    # another independently valid response follows it.
                    last_error = FCProtocolError("fc.echo_only")
                    continue
                try:
                    return parse_response(frame, request, parameter)
                except FCProtocolError as exc:
                    if exc.key in ("fc.rejected", "fc.write_unverified"):
                        raise
                    last_error = exc
        raise last_error or FCProtocolError("fc.timeout")

    def read_parameter(self, parameter):
        command = 15 if parameter["encoding"] == "text" else 1
        request = build_request(self.device_id, parameter, command)
        return self._exchange(request, parameter)

    def read_values(self, parameters, progress=None, maximum_size=None):
        values = {}
        for index, parameter in enumerate(parameters, 1):
            self.raise_if_cancelled()
            try:
                values[parameter["code"]] = self.read_parameter(parameter)
            except (FCProtocolError, serial.SerialException, ValueError) as exc:
                logger.warning("FC read %s failed: %s", parameter["code"], exc)
                values[parameter["code"]] = READ_ERROR
            if progress:
                progress(index, len(parameters))
        return values

    def write_values(self, targets, progress=None):
        written, failed = {}, []
        for index, (parameter, raw, displayed) in enumerate(
            sorted(targets, key=lambda target: target[0].get("write_last", 0)), 1
        ):
            self.raise_if_cancelled()
            code = parameter["code"]
            try:
                if parameter.get("read_only") or parameter["encoding"] == "text":
                    raise ValueError("Read-only parameter")
                if not 0 <= raw <= raw_maximum(parameter):
                    raise ValueError("Value exceeds parameter register width")
                # EEPROM commands are explicit, unlike the separate Modbus coil.
                command = 13 if parameter.get("data_bits", 16) == 32 else 14
                self._exchange(build_request(self.device_id, parameter, command, raw), parameter)
                written[code] = raw
                logger.info("FC written %s: %s (from %s)", code, raw, displayed)
            except (FCProtocolError, serial.SerialException, ValueError) as exc:
                failed.append((code, str(exc)))
            if progress:
                progress(index, len(targets))
        return {"written": written, "failed": failed}

    def reset_fc_trip(self, status_parameter):
        # A valid FC process word would also replace the bus speed reference.
        # Do not silently turn a parameter-only connection into motor control.
        raise ResetRefused("diag.reset_fc_unavailable")
