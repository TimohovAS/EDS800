"""Validated PC-side serial overrides; never changes a drive's parameters."""
from dataclasses import replace
import math
from typing import Mapping

from .catalog import InverterProfile, LinkSettings

SERIAL_FIELDS = ("protocol", "baudrate", "bytesize", "parity", "stopbits", "timeout")
COMMON_BAUDRATES = (2400, 4800, 9600, 19200, 38400, 57600, 115200)


class SettingsError(ValueError):
    def __init__(self, key):
        self.key = key
        super().__init__(key)


def serial_payload(settings: LinkSettings) -> dict:
    return {key: getattr(settings, key) for key in SERIAL_FIELDS}


def settings_for(profile: InverterProfile, overrides: Mapping | None = None) -> LinkSettings:
    """Keep model-specific address/index/storage settings outside user overrides."""
    overrides = overrides or {}
    protocol = overrides.get("protocol", profile.link.protocol)
    if protocol not in profile.supported_protocols:
        raise SettingsError("connection.invalid_protocol")
    settings = replace(profile.link_for_protocol(protocol), **{
        key: overrides[key] for key in SERIAL_FIELDS if key in overrides
    })
    if type(settings.device_id_limit) is not int or not 1 <= settings.device_id_limit <= 255:
        raise ValueError("Invalid profile device address limit")
    if type(settings.baudrate) is not int or not 300 <= settings.baudrate <= 4_000_000:
        raise SettingsError("connection.invalid_baudrate")
    allowed = profile.protocols.get(protocol, {}).get("baudrates")
    if allowed is not None and settings.baudrate not in allowed:
        raise SettingsError("connection.invalid_baudrate")
    if settings.bytesize != 8 or type(settings.bytesize) is not int:
        raise SettingsError("connection.invalid_frame")
    if settings.parity not in ("N", "E", "O") or type(settings.stopbits) is not int or settings.stopbits not in (1, 2):
        raise SettingsError("connection.invalid_frame")
    if isinstance(settings.timeout, bool) or not isinstance(settings.timeout, (int, float)) or not math.isfinite(settings.timeout) or not 0.1 <= settings.timeout <= 30:
        raise SettingsError("connection.invalid_timeout")
    if protocol == "danfoss_fc" and (settings.parity != "E" or settings.stopbits != 1):
        raise SettingsError("connection.fc_frame")
    return settings


def restore_overrides(catalog, saved) -> dict[str, dict]:
    """Malformed or obsolete saved settings cannot prevent application startup."""
    restored = {}
    if isinstance(saved, dict):
        for key, values in saved.items():
            if key not in catalog or not isinstance(values, dict):
                continue
            try:
                restored[key] = serial_payload(settings_for(catalog[key], values))
            except (ValueError, TypeError):
                continue
    return restored
