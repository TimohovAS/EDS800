"""Extract EN500/EN600 function parameters from the V2.0-A2 service manual.

This is a reproducible data-generation utility.  The generated JSON is checked
into the repository so the application does not need the PDF or pdfplumber at
runtime.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import pdfplumber


CODE_PATTERN = re.compile(r"F(?P<group>\d{2})\.(?P<number>\d{2})")
NUMBER_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?")
RANGE_PATTERN = re.compile(
    r"^\s*(?P<minimum>[-+]?\d+(?:\.\d+)?)"
    r"(?:\s*[A-Za-z%℃°/().]+)?\s*[~～－]\s*"
    r"(?P<maximum>[-+]?\d+(?:\.\d+)?)"
)
OPTION_PATTERN = re.compile(r"(?:^|\s)(\d+)\s*[:：]")
COMPOSITE_DIGIT_PATTERN = re.compile(
    r"(?i)\b(?:units?|tens|hundreds?|thousands?)\s*digit\b|unitsdigit"
)
HEX_VALUE_PATTERN = re.compile(r"\b(?=[0-9A-F]*[A-F])[0-9A-F]+H\b")
FUNCTION_CODE_RANGE_PATTERN = re.compile(
    r"^F00\.00\s*[~～－]\s*F(?P<maximum_group>25|26)\.xx$",
    re.IGNORECASE,
)


def normalize(value: str | None) -> str:
    text = (value or "").replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_pdf_artifacts(value: str) -> str:
    """Remove isolated watermark letters captured inside V5 table cells."""
    value = re.sub(
        r"(^|\s)[CEN]\s+(?=(?:[-+]?\d|F\d|Units?\b|Write\b|Range\b))",
        r"\1",
        value,
    )
    return re.sub(r"(?<=\s)[CEN](?=\d[:.])", "", value)


def decimal_places(value: str) -> int:
    match = NUMBER_PATTERN.search(value)
    if not match or "." not in match.group():
        return 0
    return len(match.group().partition(".")[2])


def infer_scale(minimum_unit: str, value_range: str, default: str) -> int:
    unit_match = NUMBER_PATTERN.match(minimum_unit)
    if unit_match:
        step = float(unit_match.group())
        if 0 < step < 1:
            return round(1 / step)

    places = max(decimal_places(value_range), decimal_places(default))
    return 10**places if places else 1


def infer_unit(minimum_unit: str) -> str:
    unit = NUMBER_PATTERN.sub("", minimum_unit, count=1)
    unit = unit.replace("（", "(").replace("）", ")").strip(" ()")
    return unit.replace("％", "%")


def infer_limits(
    value_range: str,
    scale: int,
    display_width: int | None,
) -> tuple[float, float]:
    match = RANGE_PATTERN.match(value_range)
    if match:
        minimum = float(match.group("minimum"))
        maximum = float(match.group("maximum"))
        if minimum <= maximum and maximum * scale <= 65535:
            return minimum, maximum
    if display_width is not None:
        return 0.0, float((10**display_width) - 1)
    options = [int(value) for value in OPTION_PATTERN.findall(value_range)]
    if options:
        return float(min(options)), float(max(options))
    return 0.0, 65535 / scale


def include_numeric_default(
    default: str,
    minimum: float,
    maximum: float,
) -> tuple[float, float]:
    """Keep enum ranges from excluding a documented numeric default."""
    match = NUMBER_PATTERN.match(default.strip())
    if not match:
        return minimum, maximum
    value = float(match.group())
    return min(minimum, value), max(maximum, value)


def infer_display_width(default: str) -> int | None:
    value = default.strip().removesuffix("H").removesuffix("h")
    if value.isdigit() and len(value) > 1 and value.startswith("0"):
        return len(value)
    return None


def infer_encoding(value_range: str, default: str) -> str:
    """Infer how the EN600 stores the value in its 16-bit register."""
    value = default.strip()
    if FUNCTION_CODE_RANGE_PATTERN.fullmatch(value_range.strip()):
        return "function_code"
    if value.upper().endswith("H") or HEX_VALUE_PATTERN.search(value_range):
        return "hex"
    if (
        COMPOSITE_DIGIT_PATTERN.search(value_range)
        and value.isdigit()
        and len(value) <= 4
    ):
        # EN600 keypad fields use one decimal digit per register nibble.
        return "bcd"
    return "numeric"


def extract_parameters(
    pdf_path: Path,
    first_page: int = 57,
    last_page: int = 98,
) -> list[dict[str, object]]:
    parameters: list[dict[str, object]] = []
    with pdfplumber.open(pdf_path) as manual:
        # Function parameter tables occupy pages 57-94 in V2.0-A2 and
        # pages 57-98 in V5.0-A13.
        for page_number in range(first_page, last_page + 1):
            page = manual.pages[page_number - 1]
            for table in page.extract_tables():
                for row in table:
                    cells = [normalize(cell) for cell in row]
                    if not cells:
                        continue
                    code_match = CODE_PATTERN.fullmatch(cells[0])
                    if not code_match:
                        continue

                    code = cells[0]
                    group_number = int(code_match.group("group"))
                    parameter_number = int(code_match.group("number"))
                    description = clean_pdf_artifacts(cells[1])
                    if group_number == 27:
                        continue
                    reserved = "reserved" in description.lower()

                    value_range = clean_pdf_artifacts(cells[2])
                    minimum_unit = cells[3]
                    default = cells[4]
                    modification = cells[5] if len(cells) > 5 else ""
                    encoding = infer_encoding(value_range, default)
                    if code == "F13.14":
                        # Verified on an EN600-2S0007: the keypad displays 011
                        # while Modbus returns 0x0011, despite the V2.0-A2
                        # manual documenting this field as a single 0/1 enum.
                        encoding = "bcd"
                    long_composite = (
                        encoding == "numeric"
                        and COMPOSITE_DIGIT_PATTERN.search(value_range)
                        and default.isdigit()
                        and len(default) > 4
                    )
                    scale = (
                        1
                        if encoding in {"bcd", "hex", "function_code"} or long_composite
                        else infer_scale(minimum_unit, value_range, default)
                    )
                    display_width = infer_display_width(default)
                    if encoding == "bcd":
                        # The printed default normally matches the keypad
                        # width. Firmware-specific exceptions were verified
                        # against a connected EN600-2S0007.
                        display_width = len(default)
                        if code in {"F01.16", "F14.14"}:
                            display_width = 4
                        elif code == "F13.14":
                            display_width = 3
                    elif long_composite:
                        # Five decimal selections cannot fit in four BCD
                        # nibbles; EN600 stores this field as a binary integer.
                        display_width = len(default)
                    if code == "F07.17":
                        # Present on the tested V5 keypad as 00000, although
                        # the manual marks it reserved.
                        display_width = 5
                    display_integer_digits = None
                    if code in {"F11.07", "F11.08"}:
                        # The tested EN600-2S0007 firmware uses two decimal
                        # places for its PID gains. Modbus returns 50/25 while
                        # the keypad shows 000.50/00.25. The V5 manual instead
                        # documents four decimal places.
                        scale = 100
                        display_integer_digits = 3 if code == "F11.07" else 2
                    minimum, maximum = infer_limits(
                        value_range,
                        scale,
                        display_width,
                    )
                    minimum, maximum = include_numeric_default(
                        default,
                        minimum,
                        maximum,
                    )
                    if code == "F00.25":
                        # The table says "same as F00.01"; its minimum-unit
                        # column is inherited poorly by PDF table extraction.
                        scale = 1
                        minimum, maximum = 0.0, 65.0

                    parameter: dict[str, object] = {
                        "code": code,
                        "description": description,
                        "range": value_range,
                        "minimum": minimum,
                        "maximum": maximum,
                        "unit": infer_unit(minimum_unit),
                        "address": (group_number << 8) | parameter_number,
                        "group": f"F{group_number:02d}",
                        "default": default,
                        "scale": scale,
                        "encoding": encoding,
                        "read_only": reserved or modification == "*",
                        "change_while_running": False if reserved else modification == "○",
                        "manual_pdf_page": page_number,
                    }
                    if encoding == "bcd":
                        parameter["digits"] = display_width
                        parameter["digit_chars"] = "0123456789"
                    elif encoding == "hex":
                        hex_default = default.upper().removesuffix("H")
                        parameter["digits"] = max(len(hex_default), display_width or 1)
                        parameter["digit_chars"] = "0123456789ABCDEF"
                        parameter["hex_suffix"] = default.upper().endswith("H")
                    elif encoding == "function_code":
                        range_match = FUNCTION_CODE_RANGE_PATTERN.fullmatch(
                            value_range.strip()
                        )
                        parameter["maximum_group"] = int(
                            range_match.group("maximum_group")
                        )
                    if display_width is not None:
                        parameter["display_width"] = display_width
                    if display_integer_digits is not None:
                        parameter["display_integer_digits"] = display_integer_digits
                    if code in {"F00.14", "F00.27"}:
                        # These fields execute reset/copy operations. Never
                        # replay a read value during a bulk write.
                        parameter["write_only_if_edited"] = True
                    parameters.append(parameter)

    codes = [parameter["code"] for parameter in parameters]
    addresses = [parameter["address"] for parameter in parameters]
    if len(codes) != len(set(codes)):
        raise RuntimeError("Duplicate EN600 parameter codes extracted")
    if len(addresses) != len(set(addresses)):
        raise RuntimeError("Duplicate EN600 Modbus addresses extracted")
    if not parameters or parameters[0]["code"] != "F00.00":
        raise RuntimeError("EN600 parameter extraction did not start at F00.00")
    if parameters[-1]["code"] != "F26.17":
        raise RuntimeError("EN600 parameter extraction did not finish at F26.17")
    if any(not math.isfinite(float(parameter["maximum"])) for parameter in parameters):
        raise RuntimeError("Non-finite EN600 validation limit extracted")
    return parameters


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manual", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--first-page", type=int, default=57)
    parser.add_argument("--last-page", type=int, default=98)
    args = parser.parse_args()

    parameters = extract_parameters(args.manual, args.first_page, args.last_page)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(parameters, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(parameters)} EN600 parameters to {args.output}")


if __name__ == "__main__":
    main()
