"""Supported inverter models and their parameter maps."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parameters import PARAMETERS as EDS800_PARAMETERS


@dataclass(frozen=True)
class InverterProfile:
    key: str
    label: str
    series: str
    model: str
    parameters: tuple[dict[str, Any], ...]
    baudrate: int = 9600
    parity: str = "N"
    stopbits: int = 1
    bytesize: int = 8
    timeout: float = 1.0
    default_device_id: int = 1
    max_read_registers: int = 50
    manual_url: str = ""

    @property
    def groups(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(parameter["group"] for parameter in self.parameters))


def _load_json_parameters(filename: str) -> tuple[dict[str, Any], ...]:
    path = Path(__file__).with_name("profiles") / filename
    with path.open(encoding="utf-8") as stream:
        parameters = json.load(stream)
    required_fields = {
        "code",
        "description",
        "range",
        "minimum",
        "maximum",
        "unit",
        "address",
        "group",
        "default",
        "scale",
        "encoding",
        "read_only",
    }
    for parameter in parameters:
        missing = required_fields - parameter.keys()
        if missing:
            raise RuntimeError(
                f"{filename}: {parameter.get('code', '?')} is missing {sorted(missing)}"
            )
    codes = [parameter["code"] for parameter in parameters]
    addresses = [parameter["address"] for parameter in parameters]
    if len(codes) != len(set(codes)) or len(addresses) != len(set(addresses)):
        raise RuntimeError(f"{filename}: duplicate parameter code or address")
    return tuple(parameters)


EDS800_PROFILE = InverterProfile(
    key="eds800",
    label="ENC EDS800",
    series="EDS800",
    model="EDS800",
    parameters=tuple(EDS800_PARAMETERS),
    manual_url=(
        "https://thanglongautomation.com/upload/files/"
        "ENC-EDS800%20Manual.pdf"
    ),
)

EN600_V2_PROFILE = InverterProfile(
    key="en600_2s0007_v2",
    label="ENC EN600-2S0007 — V2.0-A2 (legacy)",
    series="EN600",
    model="EN600-2S0007 V2.0-A2",
    parameters=_load_json_parameters("en600_parameters.json"),
    max_read_registers=10,
    manual_url=(
        "https://hungvuongelectric.com/uploads/File/ENC/"
        "EN500_EN600_Manual_V2.0-A2.pdf"
    ),
)

EN600_2S0007_PROFILE = InverterProfile(
    key="en600_2s0007_v5",
    label="ENC EN600-2S0007 — V5.0-A13",
    series="EN600",
    model="EN600-2S0007 V5.0-A13",
    parameters=_load_json_parameters("en600_v5_parameters.json"),
    max_read_registers=10,
    manual_url=(
        "https://konel.ba/wp-content/uploads/2024/05/"
        "EN500-EN600-Series-Manual-V5.0-A13.pdf"
    ),
)

EN600_AUTO_PROFILE = InverterProfile(
    key="en600_2s0007",
    label="ENC EN600-2S0007 — Auto revision",
    series="EN600",
    model="EN600-2S0007 (auto)",
    parameters=EN600_2S0007_PROFILE.parameters,
    max_read_registers=10,
    manual_url=EN600_2S0007_PROFILE.manual_url,
)

PROFILES = {
    profile.key: profile
    for profile in (
        EDS800_PROFILE,
        EN600_AUTO_PROFILE,
        EN600_V2_PROFILE,
        EN600_2S0007_PROFILE,
    )
}

PROFILE_LABELS = {profile.label: profile.key for profile in PROFILES.values()}
