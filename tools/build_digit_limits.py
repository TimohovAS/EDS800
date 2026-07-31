"""Derive per-digit limits for keypad fields and store them in the profiles.

Keypad parameters pack one setting per digit ("Units digit: ... 0: ... 1: ...").
Checking only the digit alphabet lets impossible combinations through, so the
highest value each digit accepts is extracted once, here, and written into
``parameters.json`` as ``digit_limits`` (most significant digit first, in the
same notation the manual uses for its ``0000~2112`` ranges).

    python tools/build_digit_limits.py                # report only
    python tools/build_digit_limits.py --write        # update the profiles

Whatever cannot be derived is reported and left alone; the editor then falls
back to the digit alphabet for that parameter.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PROFILES = Path(__file__).resolve().parent.parent / "profiles"

# "0000~2112" or "000H~E22H" at the start of a printed range.
EXPLICIT_RANGE = re.compile(r"^\s*([0-9A-F]{2,5})H?\s*[~～]\s*([0-9A-F]{2,5})H?(?![0-9A-F])")

# Digit sections, least significant first, as printed in the manuals.
DIGIT_WORDS = {
    "ten thousands": 4,
    "ten thousand": 4,
    "thousands": 3,
    "thousand": 3,
    "hundreds": 2,
    "hundred": 2,
    "tens": 1,
    "ten": 1,
    "units": 0,
    "unit": 0,
}
UNKNOWN = "*"
SECTION = re.compile(
    r"(ten\s*thousands?|thousands?|hundreds?|tens?|units?)\s*digit\s*[:：]?",
    re.IGNORECASE,
)
# "Units digit ~ Hundreds digit: Reserved" covers a span of digits at once.
SPAN = re.compile(r"\s*[~～]\s*$")
OPTION = re.compile(r"(?:^|[\s(（])([0-9A-F])\s*[:：]")
SAME_AS_UNITS = re.compile(r"same as (?:the )?units digit", re.IGNORECASE)


def digit_value(char: str) -> int:
    return int(char, 16)


def limits_from_explicit_range(value_range: str, digits: int) -> str | None:
    match = EXPLICIT_RANGE.match(value_range)
    if not match:
        return None
    low, high = match.group(1), match.group(2)
    if len(high) != digits or len(low) != digits:
        return None
    if any(digit_value(char) != 0 for char in low):
        return None  # a non-zero lower bound is not a plain per-digit range
    return high


def limits_from_description(value_range: str, digits: int) -> str | None:
    """Read the options listed under each digit heading.

    A digit the manual does not describe - because it is unused, reserved, or
    because the PDF text ends early - stays unconstrained (``*``) instead of
    being guessed at, so a legitimate value is never rejected.
    """
    # "The same as units digit" would otherwise be parsed as a new section.
    value_range = SAME_AS_UNITS.sub(" @SAME@ ", value_range)
    sections = list(SECTION.finditer(value_range))
    if not sections:
        return None
    found: dict[int, int] = {}
    units_limit: int | None = None
    for index, match in enumerate(sections):
        name = " ".join(match.group(1).lower().split())
        position = DIGIT_WORDS.get(name)
        if position is None or position >= digits:
            continue
        end = sections[index + 1].start() if index + 1 < len(sections) else len(value_range)
        body = value_range[match.end() : end]
        if SPAN.search(body):
            continue  # "Units digit ~ Hundreds digit: ..." - the span header
        if "@SAME@" in body:
            if units_limit is not None:
                found[position] = units_limit
            continue
        options = [digit_value(char) for char in OPTION.findall(body)]
        if not options:
            continue
        found[position] = max(options)
        if position == 0:
            units_limit = found[position]
    if not found:
        return None
    return "".join(
        f"{found[position]:X}" if position in found else UNKNOWN
        for position in reversed(range(digits))
    )


def derive(parameter: dict) -> tuple[str | None, str]:
    if parameter["encoding"] not in ("bcd", "hex"):
        return None, "not a digit field"
    digits = parameter["digits"]
    value_range = " ".join(parameter["range"].split())
    explicit = limits_from_explicit_range(value_range, digits)
    if explicit:
        return explicit, "range"
    described = limits_from_description(value_range, digits)
    if described:
        return described, "description"
    return None, "not derivable"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="update parameters.json")
    arguments = parser.parse_args()

    for path in sorted(PROFILES.glob("*/parameters.json")):
        parameters = json.loads(path.read_text(encoding="utf-8"))
        sources: dict[str, int] = {}
        skipped: list[str] = []
        for parameter in parameters:
            if parameter["encoding"] not in ("bcd", "hex"):
                continue
            limits, source = derive(parameter)
            sources[source] = sources.get(source, 0) + 1
            if limits is None:
                skipped.append(parameter["code"])
                parameter.pop("digit_limits", None)
                continue
            parameter["digit_limits"] = limits
        print(f"{path.parent.name}: {sources}")
        if skipped:
            print(f"  no limits for {len(skipped)}: {', '.join(skipped[:10])}")
        if arguments.write:
            path.write_text(
                json.dumps(parameters, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"  updated {path}")


if __name__ == "__main__":
    main()
