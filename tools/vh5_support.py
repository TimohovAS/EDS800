"""Reviewed VH5 definitions from INVC0620240409EN1.3.3.

Only published addresses are used. Decimal/BCD packing is never guessed.
These overrides are part of the reproducible profile generation pipeline.
"""
from __future__ import annotations
import re


def numeric(parameter, minimum, maximum, scale=1, unit="", **fields):
    previous_default = parameter.get("default_note", "")
    for name in ("note", "default_note", "signed", "allowed_values", "digit_limits",
                 "scale_from", "scale_values", "maximum_raw", "minimum_raw", "minimum_from", "maximum_from"):
        parameter.pop(name, None)
    parameter.update(description=parameter["description"].removesuffix(" (raw register)"),
                     minimum=minimum, maximum=maximum, scale=scale, unit=unit,
                     encoding="numeric", read_only=False, data_bits=16, **fields)
    if minimum < 0:
        parameter["signed"] = True
    if not parameter.get("default") and (match := re.fullmatch(r"([+-]?\d+(?:\.\d+)?)(?:[A-Za-z%/ΩΩ]+)?", previous_default)):
        parameter["default"] = match[1]


def apply_support(parameters):
    by_code = {p["code"]: p for p in parameters}

    def define(code, minimum, maximum, scale=1, unit="", **fields):
        p = by_code.get(code)
        if p is not None:
            numeric(p, minimum, maximum, scale, unit, **fields)
        return p

    def frequency(code, minimum_from=None, maximum_from="P0-13", maximum=600):
        fields = dict(maximum_from=maximum_from) if maximum_from else {}
        if minimum_from:
            fields["minimum_from"] = minimum_from
        return define(code, 0, maximum, 100, "Hz", **fields)

    # Four ramp groups share PC-09 (PDF 85, 134).
    for code in ("P0-18", "P0-19", *(f"PC-{n:02}" for n in range(3, 9))):
        p = define(code, 0 if code.startswith("P0") else 1, 65000, unit="s",
                   scale_from="PC-09", scale_values={"0": 1, "1": 10, "2": 100},
                   minimum_raw=0 if code.startswith("P0") else 1, maximum_raw=65000)
        if p:
            p["default_note"] = "Model setting"
            p["note"] = "Shown in seconds using PC-09 (0: 1 s; 1: 0.1 s; 2: 0.01 s). Read together with PC-09; its live value is checked before writing."
    # Jog is not one of the four groups governed by PC-09 (PDF 133-134).
    for code in ("PC-01", "PC-02"):
        p = define(code, 0, 6500, 10, "s")
        if p:
            p["default"] = "20.0"
    for number in range(17, 48, 2):
        p = define(f"PB-{number:02}", 0, 6500, 10, "s",
                   unit_from="PB-50", unit_values={"0": "s", "1": "h"})
        if p:
            p.update(default="0.0", note="PB-50 selects seconds/hours. Its live value is checked before writing; change the unit separately and reread times.")

    define("P2-11", 0.001, 50, 1000, "Hz/s", default="1.000")
    # Field-specific packing confirmed by read-only snapshot + panel on 37.44:
    # P2-54 raw 801 -> H.321; P7-39 and P8-22 raw 11 -> decimal 11.
    for code in ("P2-54", "P2-55", "P7-39", "P8-22"):
        p = define(code, 0 if code != "P8-22" else 10,
                   {"P2-54": 4095, "P2-55": 4095, "P7-39": 11, "P8-22": 22}[code],
                   variants_from="P8-16", variants_decoder="version",
                   variants=[{"minimum": 1, "maximum": 3743, "unsupported": True},
                             {"minimum": 3744, "maximum": 3744, "fields": {}},
                             {"minimum": 3745, "unsupported": True}],
                   write_only_if_edited=True, verify_current=True)
        if not p:
            continue
        p["note"] = "Packing confirmed against the panel and snapshot on functional 37.44 only; other revisions stay locked. Only explicitly edited values are written."
        if code == "P2-54":
            p.update(encoding="hex", digits=3, digit_chars="0123456789ABCDEF", hex_prefix=True,
                     digit_limits="**5", digit_minimums="001", preserve_mask=0xFFF0, default="321")
            p["note"] += " On 37.44 only the ones digit (1..5) is active; the historical tens digit and all higher bits must stay unchanged."
        elif code == "P2-55":
            p.update(encoding="hex", digits=3, digit_chars="0123456789ABCDEF", hex_prefix=True,
                     digit_limits="**1", preserve_mask=0xFFFE, default="000")
            p["note"] = "Panel H.000 and raw 0 confirmed on 37.44. Only the documented ones selector 0/1 may change, whose wire value is unambiguous; all higher bits are preserved. Only explicitly edited values are written."
        elif code == "P7-39":
            p.update(display_width=2, digit_limits="11", allowed_values=[0, 1, 10, 11],
                     preserve_mask=0xFFF0, default="11")
        else:
            p.update(display_width=2, digit_limits="22", allowed_values=[10, 11, 12, 20, 21, 22],
                     preserve_mask=0xFFE0, default="11")
    # Zero does not establish the encoding of the higher decimal positions.
    # Preserve panel width for read-only raw display without enabling writes.
    for code, width in (("P0-05", 2), ("P0-20", 2), ("P2-16", 5), ("P3-11", 5)):
        if code in by_code:
            by_code[code]["display_width"] = width
            by_code[code]["note"] += " Panel zero width confirmed on 37.44; zero alone does not confirm higher-digit wire packing. Writing stays blocked."
    curves = ((18, 20), (22, 24), (26, 28), (30, 32, 34, 36), (38, 40, 42, 44))
    for curve in curves:
        for index, number in enumerate(curve):
            fields = {}
            if index:
                fields["minimum_from"] = f"P2-{curve[index - 1]:02}"
            if index + 1 < len(curve):
                fields["maximum_from"] = f"P2-{curve[index + 1]:02}"
            p = define(f"P2-{number:02}", -10 if curve[0] == 38 else 0, 10, 100, "V", **fields)
            if p:
                p["default"] = "10.00" if number in (20, 24, 28, 32, 36, 40, 44) else "0.00"
    if "P2-26" in by_code:
        # On the supplied 37.44 drive, panel -10.00 is raw 64536 (0xFC18).
        # Decode signed registers on all revisions; only the observed revision
        # extends the writable lower bound beyond the printed table's 0 V.
        by_code["P2-26"].update(signed=True, variants_from="P8-16", variants_decoder="version",
            variants=[{"minimum": 1, "maximum": 3743, "fields": {"minimum": 0}},
                      {"minimum": 3744, "maximum": 3744, "fields": {"minimum": -10,
                       "range": "-10.00 V ~ P2-28", "range_ru": "-10.00 В ~ P2-28"}},
                      {"minimum": 3745, "fields": {"minimum": 0}}],
            note="Signed raw value confirmed against panel -10.00 V on functional 37.44. Negative writes are enabled only for that verified revision.")
    for code, peer in (("P4-20", "P4-21"), ("P4-21", "P4-20")):
        define(code, 0, 100, 10, "%", default="30.0", maximum_from=peer,
               maximum_from_factor=-1, maximum_from_offset=100)
    frequency("P4-23")
    frequency("P5-01", maximum_from="P5-03")
    frequency("P5-03", minimum_from="P5-01", maximum_from="P5-05")
    if "P5-05" in by_code:
        # Self-referencing lower bound appears in table AND prose. Decode the
        # known scale for neighbours, without inventing permission to write.
        by_code["P5-05"].update(scale=100, maximum=600, unit="Hz", default="0.00",
            description=by_code["P5-05"]["description"].removesuffix(" (raw register)"),
            note="P5-05 lower bound refers to itself in both table and prose (PDF 51/105); writing remains blocked pending clarification.")
    for code in ("P5-07", "A2-38"):
        p = define(code, 0, 30, 10, "%")
        if p:
            p["default_note"] = "Model setting"
    frequency("P5-08")
    define("P5-10", 0, 690, unit="V", default="0", maximum_from="P1-02")
    for first, second in (("P6-04", "P6-05"), ("A2-45", "A2-46")):
        p = frequency(first, maximum_from=second)
        if p:
            p["default"] = "5.00"
        p = frequency(second, minimum_from=first)
        if p:
            p["default"] = "10.00"
    # One 0/1 digit is identical in decimal and BCD.
    for code in ("P6-06", "A2-47"):
        define(code, 0, 1, default="0", allowed_values=[0, 1])
    # The table prints integer endpoints but a 760.0 V factory setting.
    # User's read-only snapshot for functional 37.44 contains raw 7600.
    define("P7-56", 650, 800, 10, "V", default="760.0",
           note="0.1 V resolution follows the 760.0 V factory value (PDF 58) and raw 7600 in the supplied functional-37.44 snapshot.")
    for code in ("P8-07", "P8-08", "P8-09"):
        p = define(code, 0, 65535)
        if p:
            p.update(encoding="hex", digits=4, digit_chars="0123456789ABCDEF", digit_limits="FFFF",
                     default={"P8-07": "001F", "P8-08": "0000", "P8-09": "0033"}[code],
                     note="Hexadecimal bit mask explicitly described in PDF 122-123; all 16 bits are retained.")
    define("P8-20", 0, 200, 100, "%", default="100.00",
           note="Resolution 0.01% follows the detailed parameter description (PDF 124).")
    define("PA-14", 0, 100, 10, "%", default="20.0", maximum_from="PA-15")
    define("PA-15", 0, 100, 10, "%", default="80.0", minimum_from="PA-14")
    define("PA-27", 0, 100, 10, "%", default="0.0")
    frequency("PC-00")
    define("PC-40", 0, 300, 10, "%", default="200.0")
    # Raw 8100/3500 verified against panel 0810.0/350.0, not integer volts.
    define("PC-44", 540, 810, 10, "V", default="810.0")  # 380 V model
    define("PC-45", 200, 537, 10, "V", default="350.0")
    define("PC-56", 0, 10, default="0")
    frequency("PC-57", minimum_from="PC-59")
    frequency("PC-59", maximum_from="PC-57")
    for code in ("PC-65", "PC-66"):
        define(code, 0, 6553.5, 10, "V", default="500.0" if code == "PC-65" else "50.0",
               note="Documented unit: 0.1 V. The profile limit is unsigned 16-bit storage; additional hardware limits are enforced by the drive.")
    define("PC-67", 0.5, 16, 10, "kHz", default_note="Model setting")
    for number in range(12, 16):
        define(f"A1-{number:02}", 0, 42, default="00")
    for number in range(1, 29):
        p = define(f"A9-{number:02}", 0, 65535,
                   write_guards=[{"code": "A9-00", "allowed_values": [0]}], write_only_if_edited=True)
        if p:
            p.update(encoding="hex", digits=4, digit_chars="0123456789ABCDEF", digit_limits="FFFF", default="0000",
                     variants_from="P8-16", variants_decoder="version",
                     variants=[{"minimum": 1, "maximum": 3719, "unsupported": True}, {"minimum": 3720, "fields": {}}],
                     note="Only editable while A9-00=0; checked live before writing. Mapping activation is never sent by bulk write.")
    for number in (1, 3, 4, 5, 6, 7, 8):
        code = f"PF-{number:02}"
        if code in by_code:
            p = by_code[code]
            numeric(p, 0, 65535)
            p.update(default="", variants_from="P8-16", variants_decoder="version", variants=pf_variants(number),
                     note="Read functional version P8-16 (not performance version P8-15) to resolve the PF layout; meanings change at firmware 3720.")
    for code in ("P8-15", "P8-16"):
        if code in by_code:
            by_code[code].update(encoding="version", description="Performance version" if code == "P8-15" else "Functional version",
                                 note="Panel uXX.XX. Decimal/BCD decoding is used only when unambiguous; raw values remain unchanged in backups.")
    return parameters


def pf_variants(number):
    names = {
        "torque": ("Upper limit source of driving torque", "Источник ограничения момента"),
        "forward_source": ("Forward torque frequency limit source", "Источник предела частоты вперёд в режиме момента"),
        "reverse_source": ("Reverse torque frequency limit source", "Источник предела частоты назад в режиме момента"),
        "forward_frequency": ("Forward torque frequency limit", "Предел частоты вперёд в режиме момента"),
        "reverse_frequency": ("Reverse torque frequency limit", "Предел частоты назад в режиме момента"),
        "acceleration": ("Torque acceleration time", "Время разгона в режиме момента"),
        "deceleration": ("Torque deceleration time", "Время торможения в режиме момента"),
    }

    def fields(kind, modern_ai=False):
        en, ru = names[kind]
        result = dict(description=en, description_ru=ru, minimum=0, encoding="numeric", default="")
        if kind.endswith("frequency"):
            result.update(maximum=600, scale=100, unit="Hz", maximum_from="P0-13", default="50.00",
                          range="0.00 Hz ~ P0-13", range_ru="0.00 Гц ~ P0-13")
        elif kind in ("acceleration", "deceleration"):
            result.update(maximum=650, scale=100, unit="s", default="0.00", range="0.00 ~ 650.00 s", range_ru="0.00 ~ 650.00 с")
        else:
            ai = 1 if modern_ai else 2
            result.update(maximum=5, scale=1, unit="", default="0", allowed_values=[0, ai, 5],
                          range=f"0: Digital; {ai}: AI; 5: Communication",
                          range_ru=f"0: Цифровое задание; {ai}: AI; 5: По связи")
        return result

    old_kind = {1: "torque", 3: "forward_frequency", 4: "reverse_frequency", 5: "acceleration", 6: "deceleration"}.get(number)
    new_kind = {1: "torque", 3: "forward_source", 4: "forward_frequency", 5: "reverse_source",
                6: "reverse_frequency", 7: "acceleration", 8: "deceleration"}[number]
    variants = [{"minimum": 1, "maximum": 3719, "fields": fields(old_kind)}] if old_kind else [
        {"minimum": 1, "maximum": 3719, "unsupported": True}]
    variants += [{"minimum": 3720, "maximum": 3743, "fields": fields(new_kind)},
                 {"minimum": 3744, "fields": fields(new_kind, modern_ai=True)}]
    return variants
