"""Automatic revision detection, driven by the profile manifest.

A profile that carries a ``detect`` block is a virtual entry: it borrows the
parameter table of a concrete profile and, before the first operation, reads
one register to decide which concrete profile really matches the drive::

    "detect": {
      "link_check": "F00.00",
      "probe": "F02.26",
      "rules": [{"in_range": [95, 115], "profile": "en600_v5"}],
      "fallback": "en600_v2"
    }

Nothing is written to the inverter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .catalog import Catalog, InverterProfile
from .transport import ModbusLink


@dataclass(frozen=True)
class Detection:
    """Outcome of a probe: which profile matched and what was read."""

    profile: InverterProfile
    probe_code: str
    value: int | None

    @property
    def displayed_value(self) -> str:
        return "N/A" if self.value is None else str(self.value)


def needs_detection(profile: InverterProfile) -> bool:
    return bool(profile.detect)


def _address_of(profile: InverterProfile, code: str | None) -> int | None:
    if not code:
        return None
    for parameter in profile.parameters:
        if parameter["code"] == code:
            return parameter["address"]
    return None


def _matches(rule: Mapping[str, Any], value: int | None) -> bool:
    if value is None:
        return False
    if "in_range" in rule:
        minimum, maximum = rule["in_range"]
        return minimum <= value <= maximum
    if "equals" in rule:
        return value == rule["equals"]
    return False


def detect(catalog: Catalog, profile: InverterProfile, link: ModbusLink) -> Detection:
    """Probe the drive and return the concrete profile to use.

    Raises ``ConnectionError`` when the link check itself fails, so a silent
    wrong-profile choice cannot happen on a dead bus.
    """
    rules = profile.detect or {}
    probe_code = rules.get("probe", "")

    link_address = _address_of(profile, rules.get("link_check"))
    if link_address is None and profile.parameters:
        link_address = profile.parameters[0]["address"]
    if link_address is not None:
        check = link.read_registers(link_address, 1)
        if check.isError():
            raise ConnectionError(str(check))

    value = None
    probe_address = _address_of(profile, probe_code)
    if probe_address is not None:
        result = link.read_registers(probe_address, 1)
        value = None if result.isError() else result.registers[0]

    for rule in rules.get("rules", ()):
        if _matches(rule, value):
            return Detection(catalog[rule["profile"]], probe_code, value)
    return Detection(catalog[rules["fallback"]], probe_code, value)
