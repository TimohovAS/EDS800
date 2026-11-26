"""Read-only decoding of drive diagnostics; tables belong to the profile.

Raw values remain untouched in Session/settings files. In particular, an alarm
word contains bit flags, whereas an indexed fault log contains a fault *code*.
"""
from __future__ import annotations

from typing import Any, Mapping

from .codecs import READ_ERROR


class ResetRefused(RuntimeError):
    """A safety precondition for a remote reset was not satisfied."""

    def __init__(self, key: str):
        self.key = key
        super().__init__(key)


def validate(data: Mapping[str, Any], parameters: Mapping[str, Mapping]) -> None:
    """Reject broken references and writable diagnostic rows on profile load."""
    if not isinstance(data, dict) or not isinstance(data.get("fields"), dict):
        raise ValueError("diagnostics requires a fields map")
    tables = data.get("tables", {})
    for code, definition in data["fields"].items():
        if code not in parameters or not parameters[code].get("read_only"):
            raise ValueError(f"diagnostics field {code} must be a read-only parameter")
        kind = definition.get("kind")
        table = tables.get(definition.get("table"))
        if kind not in ("bits", "code") or not isinstance(table, dict):
            raise ValueError(f"invalid diagnostics definition for {code}")
        for number, labels in table.items():
            index = int(number)
            limit = parameters[code].get("data_bits", 16) if kind == "bits" else 256
            if not 0 <= index < limit or not isinstance(labels, dict) or not labels.get("en"):
                raise ValueError(f"invalid diagnostics entry {code}/{number}")
    if data.get("reset") not in (None, "danfoss_fc"):
        raise ValueError("unknown diagnostics reset protocol")
    if data.get("reset") and not {"16-03", "16-90"} <= parameters.keys():
        raise ValueError("FC reset requires status/alarm readouts")


def decode(data: Mapping, code: str, raw: Any, translator) -> str:
    """Decode all set bits, preserving undocumented bits/codes explicitly."""
    definition = data.get("fields", {}).get(code)
    if not definition:
        return ""
    if raw == READ_ERROR:
        return translator("diag.read_error")
    if raw is None:
        return translator("diag.not_read")
    if type(raw) is not int or raw < 0:
        return translator("diag.invalid")
    table = data["tables"][definition["table"]]

    def label(number):
        labels = table.get(str(number), {})
        return labels.get(translator.language) or labels.get("en")

    if definition["kind"] == "code":
        if raw == 0:
            return translator(definition.get("zero_key", "diag.no_event"))
        return f"{raw}: {label(raw)}" if label(raw) else translator("diag.unknown_code", code=raw)
    if raw == 0:
        return translator("diag.no_flags")
    return "; ".join(
        f"{translator('diag.bit', bit=bit)}: {label(bit)}"
        if label(bit) else translator("diag.unknown_bit", bit=bit)
        for bit in range(raw.bit_length()) if raw & (1 << bit)
    )
