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
import math
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

# Placeholders shown in the value column when a value cannot be represented.
READ_ERROR = "Error"
BCD_ERROR = "BCD Error"
CODE_ERROR = "Code Error"
SCALE_ERROR = "Scale unknown"
ERROR_TEXTS = frozenset({READ_ERROR, BCD_ERROR, CODE_ERROR, SCALE_ERROR})

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


def version_number(raw: Any) -> int:
    """Decode panel uXX.XX without silently choosing decimal over BCD.

    For the reported functional version 37.44, decimal 3744 is not valid BCD,
    while BCD 0x3744 exceeds four decimal digits. Ambiguous encodings stop
    revision-dependent writes instead of selecting an arbitrary layout.
    """
    if type(raw) is not int or not 0 <= raw <= 65535:
        raise ValueError("Invalid version register")
    candidates = {raw} if raw <= 9999 else set()
    digits = [(raw >> shift) & 15 for shift in (12, 8, 4, 0)]
    if max(digits) <= 9:
        candidates.add(sum(digit * 10 ** (3 - i) for i, digit in enumerate(digits)))
    if len(candidates) != 1:
        raise ValueError("Ambiguous version register")
    return candidates.pop()


def context_codes(parameter: Mapping[str, Any]) -> tuple[str, ...]:
    codes = [parameter.get(field) for field in ("scale_from", "unit_from", "variants_from")]
    codes.extend(guard["code"] for guard in parameter.get("write_guards", ()))
    return tuple(dict.fromkeys(code for code in codes if code))


def resolve_parameter(parameter: Mapping[str, Any], values: Mapping[str, Any]) -> Mapping[str, Any]:
    """Resolve an engineering scale from a selector actually read from the drive.

    Never substitute the factory default: the keypad may have changed it.
    The original profile remains immutable; write targets carry their resolved
    selector so the transport can check it again against the live drive.
    """
    providers = context_codes(parameter)
    if not providers:
        return parameter
    resolved = dict(parameter)
    for provider in providers:
        if type(values.get(provider)) is not int:
            raise CodecError("valid.scale_unknown", code=provider)
    provider = parameter.get("variants_from")
    if provider:
        value = values[provider]
        if parameter.get("variants_decoder") == "version":
            try:
                value = version_number(value)
            except ValueError:
                raise CodecError("valid.scale_unknown", code=provider) from None
        variant = next((v for v in parameter["variants"]
                        if v["minimum"] <= value <= v.get("maximum", 65535)), None)
        if not variant or variant.get("unsupported"):
            raise CodecError("valid.context_unsupported", code=provider)
        resolved.update(variant["fields"])
        resolved["_variant_fields"] = tuple(variant["fields"])
    provider = parameter.get("scale_from")
    if provider:
        value = values[provider]
        if str(value) not in parameter["scale_values"]:
            raise CodecError("valid.scale_unknown", code=provider)
        scale = parameter["scale_values"][str(value)]
        resolved.update(scale=scale, minimum=parameter.get("minimum_raw", 0) / scale,
                        maximum=parameter["maximum_raw"] / scale, _scale_resolved=value)
    provider = parameter.get("unit_from")
    if provider:
        value = values[provider]
        if str(value) not in parameter["unit_values"]:
            raise CodecError("valid.scale_unknown", code=provider)
        resolved["unit"] = parameter["unit_values"][str(value)]
    for guard in parameter.get("write_guards", ()):
        if values[guard["code"]] not in guard["allowed_values"]:
            raise CodecError("valid.context_unsupported", code=guard["code"])
    resolved["_resolved_context"] = {code: values[code] for code in providers}
    return resolved


def scale_problem(parameter: Mapping[str, Any]) -> Problem | None:
    providers = context_codes(parameter)
    if providers and "_resolved_context" not in parameter:
        return Problem("valid.scale_unknown", {"code": providers[0]})
    return None


UNCONSTRAINED_DIGIT = "*"


def digit_limit_problem(text: str, parameter: Mapping[str, Any]) -> Problem | None:
    """Check a keypad value digit by digit against ``digit_limits``.

    Each digit of such a parameter selects one setting, so the alphabet alone
    is not enough: ``2222`` is made of valid characters but is not a valid
    combination for a field documented as ``0000~2112``.  A ``*`` marks a digit
    the manual does not constrain.
    """
    limits = parameter.get("digit_limits")
    if not limits:
        return None
    text = text.zfill(len(limits))  # a keypad hides leading zeros
    if len(text) != len(limits):
        return Problem("valid.digit_limits", {"pattern": limits})
    for digit, limit in zip(text, limits):
        if limit == UNCONSTRAINED_DIGIT:
            continue
        try:
            if int(digit, 16) > int(limit, 16):
                return Problem("valid.digit_limits", {"pattern": limits})
        except ValueError:
            return Problem("valid.digit_limits", {"pattern": limits})
    minimums = parameter.get("digit_minimums")
    if minimums:
        for digit, minimum in zip(text, minimums):
            if minimum != UNCONSTRAINED_DIGIT and int(digit, 16) < int(minimum, 16):
                return Problem("valid.digit_minimums", {"pattern": minimums})
    return None


def raw_maximum(parameter: Mapping[str, Any]) -> int:
    """Largest packed value in the parameter's holding registers."""
    bits = parameter.get("data_bits", 16 * parameter.get("register_count", 1))
    return (1 << bits) - 1


def numeric_raw(raw: Any, parameter: Mapping[str, Any]) -> int:
    """Interpret a packed integer using its documented sign and width."""
    value = int(raw)
    bits = parameter.get("data_bits", 16 * parameter.get("register_count", 1))
    if parameter.get("signed") and value >= (1 << (bits - 1)):
        value -= 1 << bits
    return value


def register_problem(raw_value: int, parameter: Mapping[str, Any] | None = None) -> Problem | None:
    maximum = raw_maximum(parameter or {})
    if not 0 <= raw_value <= maximum:
        return Problem("valid.register_range", {"maximum": maximum})
    return None


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
        raw = numeric_raw(raw, parameter)
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
            raw = int(round(Decimal(text) * Decimal(str(parameter["scale"]))))
            if raw < 0 and parameter.get("signed"):
                raw += 1 << parameter.get("data_bits", 16 * parameter.get("register_count", 1))
            return raw
        except (TypeError, ValueError, OverflowError, InvalidOperation):
            raise CodecError("error.invalid_value", value=text) from None

    def validate(self, text, parameter):
        try:
            number = float(text)
        except ValueError:
            return Problem("valid.number")
        if not math.isfinite(number):
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
        allowed = parameter.get("allowed_values")
        if allowed is not None and number not in allowed:
            return Problem("valid.options", {"options": ", ".join(map(str, allowed))})
        if parameter.get("data_bits"):
            scaled = Decimal(text) * Decimal(str(parameter["scale"]))
            if scaled != scaled.to_integral_value():
                return Problem("valid.resolution", {"step": f"{1 / parameter['scale']:g}"})
        # Some fields are plain decimals whose digits each select a setting.
        if parameter.get("digit_limits"):
            return digit_limit_problem(text, parameter)
        return None


class TextCodec(Codec):
    """Read-only ASCII identification strings, two characters per register."""

    name = "text"

    def format(self, raw, parameter):
        data = int(raw).to_bytes(2 * parameter["register_count"], "big")
        return data.decode("ascii", errors="replace").rstrip("\x00 ")

    def encode(self, text, parameter):
        raise CodecError("valid.read_only")

    def validate(self, text, parameter):
        return Problem("valid.read_only")


class VersionCodec(TextCodec):
    name = "version"

    def format(self, raw, parameter):
        version = version_number(raw)
        return f"u{version // 100:02}.{version % 100:02}"


class BcdCodec(Codec):
    """Keypad digit fields: each decimal digit lives in its own nibble."""

    name = "bcd"

    def format(self, raw, parameter):
        value = int(raw) & REGISTER_MASK
        if parameter.get("reject_high_bits") and value >= 1 << (4 * parameter["digits"]):
            return BCD_ERROR
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
        return digit_limit_problem(text, parameter)


class HexCodec(Codec):
    """Bit-mask selection fields the manual prints in hexadecimal."""

    name = "hex"

    @staticmethod
    def normalized(text):
        return str(text).strip().upper().removeprefix("H.").strip().removesuffix("H")

    def format(self, raw, parameter):
        value = int(raw) & REGISTER_MASK
        suffix = "H" if parameter.get("hex_suffix") else ""
        prefix = "H." if parameter.get("hex_prefix") else ""
        return f"{prefix}{value:0{parameter['digits']}X}{suffix}"

    def encode(self, text, parameter):
        try:
            return int(self.normalized(text), 16)
        except (AttributeError, TypeError, ValueError):
            raise CodecError("error.invalid_value", value=text) from None

    def validate(self, text, parameter):
        normalized = self.normalized(text)
        expected = parameter["digits"]
        allowed = parameter["digit_chars"]
        if len(normalized) != expected or any(char not in allowed for char in normalized):
            return Problem("valid.hex_digits", {"digits": expected, "chars": allowed})
        return digit_limit_problem(normalized, parameter)


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


for _codec in (NumericCodec(), BcdCodec(), HexCodec(), FunctionCodeCodec(), TextCodec(), VersionCodec()):
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
    if scale_problem(parameter):
        return SCALE_ERROR
    try:
        return codec_for(parameter).format(raw, parameter)
    except (KeyError, TypeError, ValueError):
        return str(raw)


def encode_value(parameter: Mapping[str, Any], text: str) -> int:
    """Convert an edited cell into a packed unsigned register value."""
    problem = scale_problem(parameter)
    if problem:
        raise CodecError(problem.key, **problem.params)
    return codec_for(parameter).encode(str(text).strip(), parameter)


def validate_value(parameter: Mapping[str, Any], text: str) -> Problem | None:
    """Check an edited cell against the parameter definition."""
    if parameter.get("read_only"):
        return Problem("valid.read_only")
    problem = scale_problem(parameter)
    if problem:
        return problem
    text = str(text).strip()
    codec = codec_for(parameter)
    problem = codec.validate(text, parameter)
    if problem is not None:
        return problem
    # Whatever the encoding says, the result must fit its holding registers.
    try:
        return register_problem(codec.encode(text, parameter), parameter)
    except CodecError as exc:
        return exc.problem
