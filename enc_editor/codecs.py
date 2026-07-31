"""Value codecs: register bits <-> the text shown in the parameter table.

Every inverter model describes each parameter with an ``encoding`` name.  The
codec for that name owns all three directions: formatting a register for the
table, encoding an edited cell back into a register, and validating what the
user typed.  Adding an encoding therefore means adding one class here and
registering it - no other module needs to change.

Codecs never format user-facing messages themselves; they return a
:class:`Problem` (translation key plus parameters) so the UI can render it in
the interface language.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

# Placeholders shown in the value column when a value cannot be represented.
READ_ERROR = "Error"
BCD_ERROR = "BCD Error"
CODE_ERROR = "Code Error"
ERROR_TEXTS = frozenset({READ_ERROR, BCD_ERROR, CODE_ERROR})

REGISTER_MASK = 0xFFFF
FUNCTION_CODE_PATTERN = re.compile(r"F?(\d{1,2})(?:\.(\d{1,2}))?", re.IGNORECASE)


@dataclass(frozen=True)
class Problem:
    """Why a value is not acceptable, as a translation key and its fields."""

    key: str
    params: dict[str, Any] = field(default_factory=dict)


class CodecError(ValueError):
    """Raised when an edited value cannot be encoded into a register."""

    def __init__(self, key: str, **params: Any):
        self.problem = Problem(key, params)
        super().__init__(key)


class Codec:
    """Base class; subclasses implement one ``encoding`` name."""

    name = ""

    def format(self, raw: Any, parameter: Mapping[str, Any]) -> str:
        raise NotImplementedError

    def encode(self, text: str, parameter: Mapping[str, Any]) -> int:
        raise NotImplementedError

    def validate(self, text: str, parameter: Mapping[str, Any]) -> Problem | None:
        raise NotImplementedError


class NumericCodec(Codec):
    """Plain scaled integers: ``50.25 Hz`` <-> ``5025`` with ``scale = 100``."""

    name = "numeric"

    def format(self, raw, parameter):
        scale = parameter["scale"]
        if scale == 1:
            value = int(raw)
            width = parameter.get("display_width")
            return f"{value:0{width}d}" if width else str(value)
        decimals = len(str(scale)) - 1
        integer_digits = parameter.get("display_integer_digits")
        if integer_digits:
            width = int(integer_digits) + decimals + 1
            return f"{float(raw) / scale:0{width}.{decimals}f}"
        return f"{float(raw) / scale:.{decimals}f}"

    def encode(self, text, parameter):
        try:
            return int(round(float(text) * parameter["scale"]))
        except (TypeError, ValueError):
            raise CodecError("error.invalid_value", value=text) from None

    def validate(self, text, parameter):
        try:
            number = float(text)
        except ValueError:
            return Problem("valid.number")
        minimum, maximum = limits(parameter)
        if minimum is not None and maximum is not None and not minimum <= number <= maximum:
            unit = parameter.get("unit") or ""
            return Problem(
                "valid.between",
                {
                    "minimum": f"{minimum:g}",
                    "maximum": f"{maximum:g}",
                    "unit": f" {unit}" if unit else "",
                },
            )
        return None


class BcdCodec(Codec):
    """Keypad digit fields: each decimal digit lives in its own nibble."""

    name = "bcd"

    def format(self, raw, parameter):
        value = int(raw) & REGISTER_MASK
        digits = [
            (value >> shift) & 0x0F
            for shift in range((parameter["digits"] - 1) * 4, -1, -4)
        ]
        if all(str(digit) in parameter["digit_chars"] for digit in digits):
            return "".join(map(str, digits))
        return BCD_ERROR

    def encode(self, text, parameter):
        encoded = 0
        try:
            for char in text:
                encoded = (encoded << 4) | int(char)
        except (TypeError, ValueError):
            raise CodecError("error.invalid_value", value=text) from None
        return encoded

    def validate(self, text, parameter):
        expected = parameter["digits"]
        allowed = parameter["digit_chars"]
        if len(text) != expected or any(char not in allowed for char in text):
            return Problem("valid.bcd_digits", {"digits": expected, "chars": allowed})
        # Some keypad fields also carry a plain decimal range such as "000~111".
        value_range = parameter.get("range", "")
        if value_range.count("~") == 1:
            minimum, maximum = value_range.split("~", maxsplit=1)
            if minimum.isdigit() and maximum.isdigit():
                if not int(minimum) <= int(text) <= int(maximum):
                    return Problem(
                        "valid.between",
                        {"minimum": minimum, "maximum": maximum, "unit": ""},
                    )
        return None


class HexCodec(Codec):
    """Bit-mask selection fields the manual prints in hexadecimal."""

    name = "hex"

    def format(self, raw, parameter):
        value = int(raw) & REGISTER_MASK
        suffix = "H" if parameter.get("hex_suffix") else ""
        return f"{value:0{parameter['digits']}X}{suffix}"

    def encode(self, text, parameter):
        try:
            return int(text.upper().removesuffix("H"), 16)
        except (AttributeError, TypeError, ValueError):
            raise CodecError("error.invalid_value", value=text) from None

    def validate(self, text, parameter):
        normalized = text.upper().removesuffix("H")
        expected = parameter["digits"]
        allowed = parameter["digit_chars"]
        if len(normalized) != expected or any(char not in allowed for char in normalized):
            return Problem("valid.hex_digits", {"digits": expected, "chars": allowed})
        return None


class FunctionCodeCodec(Codec):
    """References to another function code: ``25.00`` <-> ``0x2500``."""

    name = "function_code"

    def format(self, raw, parameter):
        value = int(raw) & REGISTER_MASK
        nibbles = [(value >> shift) & 0x0F for shift in (12, 8, 4, 0)]
        if any(nibble > 9 for nibble in nibbles):
            return CODE_ERROR
        return f"{nibbles[0]}{nibbles[1]}.{nibbles[2]}{nibbles[3]}"

    def encode(self, text, parameter):
        match = FUNCTION_CODE_PATTERN.fullmatch(str(text))
        if not match:
            raise CodecError("error.invalid_function_code", value=text)
        group = int(match.group(1))
        number = int(match.group(2) or 0)
        return (
            ((group // 10) << 12)
            | ((group % 10) << 8)
            | ((number // 10) << 4)
            | (number % 10)
        )

    def validate(self, text, parameter):
        match = FUNCTION_CODE_PATTERN.fullmatch(text)
        if not match:
            return Problem("valid.function_code")
        group = int(match.group(1))
        number = int(match.group(2) or 0)
        maximum_group = parameter.get("maximum_group", 99)
        if group > maximum_group:
            return Problem("valid.function_group", {"maximum": f"{maximum_group:02d}"})
        if number > 99:
            return Problem("valid.function_number")
        return None


CODECS: dict[str, Codec] = {}


def register(codec: Codec) -> Codec:
    """Make ``codec`` available under its ``name``."""
    CODECS[codec.name] = codec
    return codec


for _codec in (NumericCodec(), BcdCodec(), HexCodec(), FunctionCodeCodec()):
    register(_codec)


def codec_for(parameter: Mapping[str, Any]) -> Codec:
    encoding = parameter.get("encoding", NumericCodec.name)
    try:
        return CODECS[encoding]
    except KeyError:
        raise KeyError(f"{parameter.get('code', '?')}: unknown encoding {encoding!r}") from None


def parse_range(value_range: str) -> tuple[float | None, float | None]:
    """Read ``min~max`` out of a printed range, or ``(None, None)``."""
    try:
        minimum, maximum = map(float, value_range.split("~"))
        return minimum, maximum
    except (AttributeError, ValueError):
        return None, None


def limits(parameter: Mapping[str, Any]) -> tuple[float | None, float | None]:
    """Validation limits of a parameter, falling back to its printed range."""
    minimum = parameter.get("minimum")
    maximum = parameter.get("maximum")
    if minimum is None or maximum is None:
        return parse_range(parameter.get("range", ""))
    return minimum, maximum


def format_value(raw: Any, parameter: Mapping[str, Any]) -> str:
    """Render a register for the table; never raises."""
    if raw == "":
        return ""
    try:
        return codec_for(parameter).format(raw, parameter)
    except (KeyError, TypeError, ValueError):
        return str(raw)


def encode_value(parameter: Mapping[str, Any], text: str) -> int:
    """Convert an edited cell into one 16-bit register."""
    return codec_for(parameter).encode(str(text).strip(), parameter)


def validate_value(parameter: Mapping[str, Any], text: str) -> Problem | None:
    """Check an edited cell against the parameter definition."""
    if parameter.get("read_only"):
        return Problem("valid.read_only")
    return codec_for(parameter).validate(str(text).strip(), parameter)
