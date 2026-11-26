"""Rebuild VH5-45P5-B from XINJE INVC0620240409EN1.3.3, PDF pp. 42-80.

python tools/extract_vh5_parameters.py manual.pdf profiles/xinje_vh5
Requires pdfplumber only for generation. The 5.5 kW model uses the <=55 kW
motor-data resolution. Ambiguous or context-scaled fields remain raw/read-only.
No control-command registers are exported. Output is deterministic.
"""
from __future__ import annotations
import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import re

CODE = re.compile(r"^[PAU][0-9A-F]-\d{2}$")
NUMBER = r"[+-]?\d+(?:\.\d+)?"
UNIT = r"(?:Hz|kHz|kW|KW|mH|mA|Min|min|rpm|RPM|ms|V|A|s|h|m|%|Ω|Ω|℃|°)?"
RANGE = re.compile(rf"^\s*({NUMBER})\s*({UNIT})\s*[~～-]\s*({NUMBER})\s*({UNIT})")
NUMERIC_DEFAULT = re.compile(rf"^({NUMBER})\s*({UNIT})$")
GROUPS = {
    "P0": ("Basic operation", "Основные настройки"), "P1": ("Motor 1", "Двигатель 1"),
    "P2": ("Input terminals", "Входы"), "P3": ("Output terminals", "Выходы"),
    "P4": ("Start / stop", "Пуск и останов"), "P5": ("V/F control", "Управление U/f"),
    "P6": ("Vector control", "Векторное управление"), "P7": ("Faults / protection", "Аварии и защита"),
    "P8": ("Keypad / display", "Панель и индикация"), "P9": ("Communication", "Связь"),
    "PA": ("Process PID", "ПИД-регулятор"), "PB": ("Multi-speed / simple PLC", "Ступенчатые скорости и ПЛК"),
    "PC": ("Auxiliary operation", "Дополнительные функции"), "PE": ("User parameters", "Пользовательские параметры"),
    "PF": ("Torque control (firmware-dependent)", "Момент (зависит от прошивки)"),
    "A0": ("Textile / counters", "Качание частоты и счётчики"), "A1": ("Virtual I/O", "Виртуальные входы и выходы"),
    "A2": ("Motor 2", "Двигатель 2"), "A4": ("Password countdown lock", "Блокировка по времени"),
    "A9": ("Communication address mapping", "Отображение адресов связи"),
    "AD": ("Analog calibration", "Калибровка аналоговых сигналов"),
    "U0": ("Monitoring", "Мониторинг"), "MB": ("Modbus state / fault", "Состояние и авария Modbus"),
}


def clean(value):
    return re.sub(r"[ \t]+", " ", (value or "").replace("\r", "").replace("：", ":")).strip()


def unit_name(value):
    return {"KW": "kW", "RPM": "rpm", "Min": "min", "Ω": "Ω", "℃": "°C"}.get(value, value)


def table_rows(pdf):
    """Expand merged cells using their actual bounding boxes, not text guesses."""
    records = []
    previous = None
    for page_no in range(42, 81):
        page = pdf.pages[page_no - 1]
        for table in page.find_tables():
            rows = table.extract(x_tolerance=1)
            for index, row in enumerate(rows):
                code = clean(row[0])
                if not CODE.fullmatch(code):
                    # Continued option lists at the top of the following page.
                    if previous and not code and len(row) == 6 and "Frequency instruction" not in clean(row[1]):
                        if clean(row[1]):
                            previous["description"] += " " + clean(row[1]).replace("\n", " ")
                        if clean(row[2]):
                            previous["range"] += "\n" + clean(row[2])
                    continue
                if code.startswith("U4-"):
                    continue  # The manual gives no Modbus register addresses for U4.
                if len(row) not in (5, 6):
                    raise ValueError((page_no, row))
                monitor = len(row) == 5
                address = clean(row[-1])
                if not re.fullmatch(r"[0-9A-F]{4}H", address):
                    continue  # Local-only/password rows have no documented bus address.
                span_row = table.rows[index]
                for column, value in enumerate(row):
                    if value is not None:
                        continue
                    header = next((r.cells[column] for r in table.rows if r.cells[column]), None)
                    if header:
                        x, y = (header[0] + header[2]) / 2, (span_row.bbox[1] + span_row.bbox[3]) / 2
                        cell = next((c for c in table.cells if c[0] <= x <= c[2] and c[1] <= y <= c[3]), None)
                        if cell:
                            row[column] = page.crop(cell).extract_text(x_tolerance=1)
                previous = dict(code=code, description=clean(row[1]).replace("\n", " "),
                                range=clean(row[3] if monitor else row[2]),
                                factory="" if monitor else clean(row[3]).replace("\n", " "),
                                modify="-" if monitor else clean(row[4]), address=int(address[:-1], 16),
                                monitor_unit=clean(row[2]) if monitor else "", manual_pdf_page=page_no)
                records.append(previous)
    return records


def parse_parameter(row, variants):
    code = row["code"]
    text = row["range"]
    group = code.split("-")[0]
    param = dict(code=code, description=row["description"], range=text, minimum=0, maximum=65535,
                 unit="", address=row["address"], group=group, default="", scale=1, encoding="numeric",
                 read_only=row["modify"] not in ("○", "×"), change_while_running=row["modify"] == "○",
                 manual_pdf_page=row["manual_pdf_page"])
    reasons = []
    if row["address"] != ((int(group[1], 16) + (0xA0 if group[0] == "A" else 0x70 if group[0] == "U" else 0)) << 8) | int(code[-2:]):
        reasons.append("The printed Modbus address conflicts with the appendix formula; raw/read-only until hardware verification.")
    if group == "PF" and code not in ("PF-00", "PF-02"):
        reasons.append("Torque fields depend on firmware revision; raw/read-only until that revision is confirmed.")
    if len(variants) > 1 and code not in ("PF-00", "PF-02"):
        reasons.append("The meaning/options differ between firmware editions; raw register only.")
        param["description"] = f"{code}: firmware-dependent raw register"
        param["range"] = "\n\n".join(f"PDF p.{v['manual_pdf_page']}: {v['description']}\n{v['range']}" for v in variants)
    if group in ("PE", "A9", "A4"):
        reasons.append("Mapping/lock configuration is intentionally read-only in this profile.")
    if re.search(r"\b(?:Ones|Tens|Ten|Hundreds|Thousands)\s+bit", text, re.I):
        reasons.append("Digit-packed field: wire packing is not specified unambiguously; raw register only.")
    if "PC-09" in text or "Depend on" in text or "/0.01Hz" in row["monitor_unit"]:
        reasons.append("Resolution depends on another setting; raw register only.")
    if code in {f"PC-{i:02}" for i in range(1, 9)} or "s(h)" in text:
        reasons.append("Time unit/resolution is configurable; raw register only.")
    # All motor-dependent units in the selected power class are explicit.
    if "VFD power" in text:
        text = text.split("\n")[0]
    parsed = False
    match = RANGE.match(text)
    if match:
        lo, u1, hi, u2 = match.groups()
        decimals = max(len(x.partition(".")[2]) for x in (lo, hi))
        param.update(minimum=float(lo), maximum=float(hi), scale=10 ** decimals, unit=unit_name(u2 or u1))
        parsed = True
    else:
        # Frequency/current bounds referring to a known parameter.
        match = re.match(rf"^({NUMBER})\s*({UNIT})\s*[~～]\s*(.*)", text)
        if match and ("max output frequency" in match[3].lower() or "upper limit frequency" in match[3].lower()):
            lo = match[1]
            param.update(minimum=float(lo), maximum=600, scale=10 ** len(lo.partition(".")[2]), unit=unit_name(match[2]))
            param["maximum_from"] = "P0-15" if "upper limit frequency" in match[3].lower() else "P0-13"
            parsed = True
        elif code == "P0-15":
            param.update(minimum=0, maximum=600, scale=100, unit="Hz",
                         minimum_from="P0-17", maximum_from="P0-13")
            parsed = True
        elif code in ("P1-10", "A2-10"):
            param.update(minimum=0.01, maximum=655.35, scale=100, unit="A", maximum_from=group + "-03")
            parsed = True
        else:
            options = [int(x) for x in re.findall(r"(?:^|\n)\s*(\d+)\s*:", text)]
            if options and not re.search(r"\d\s*[~～]\s*\d", text):
                param.update(minimum=min(options), maximum=max(options), allowed_values=sorted(set(options)))
                parsed = True
    if group == "U0":
        precision = re.fullmatch(rf"({NUMBER})\s*({UNIT})", row["monitor_unit"])
        if precision:
            step = Decimal(precision[1])
            if step > 0:
                param["scale"] = int(1 / step)
                param["unit"] = unit_name(precision[2])
                if not parsed:
                    param["maximum"] = 65535 / param["scale"]
                parsed = True
    if not parsed:
        reasons.append("Bounds/resolution are not unambiguous in the source; raw register only.")
    if param["minimum"] < 0:
        param["signed"] = True
    limit = 32767 if param.get("signed") else 65535
    if not param["read_only"] and Decimal(str(param["maximum"])) * param["scale"] > limit:
        reasons.append("The stated range exceeds one documented register at this resolution; raw register only.")
    # Firmware/table transcription inconsistencies must not enable guessed writes.
    if code in ("P8-20", "P1-35", "A2-35", "P8-02"):
        reasons.append("Ambiguous precision or action parameter; writing is disabled.")
    if reasons:
        param.update(minimum=0, maximum=65535, scale=1, unit="", read_only=True)
        for key in ("signed", "allowed_values", "minimum_from", "maximum_from"):
            param.pop(key, None)
        param["note"] = " ".join(dict.fromkeys(reasons)) + " Source range retained above."
        if "raw register" not in param["description"]:
            param["description"] += " (raw register)"
    factory = NUMERIC_DEFAULT.fullmatch(row["factory"])
    if factory and not reasons:
        param["default"] = factory[1]
    elif row["factory"] and row["factory"] != "-":
        param["default_note"] = row["factory"]
    if group == "P9":
        param["write_only_if_edited"] = True
    return param


def extract(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        rows = table_rows(pdf)
    by_code = {}
    for row in rows:
        by_code.setdefault(row["code"], []).append(row)
    # PC-41/42 are printed at the same addresses as unrelated PC-28/29.
    # Omit them rather than guess a correction or show a misleading alias.
    parameters = [parse_parameter(variants[-1], variants) for code, variants in by_code.items()
                  if code not in ("PC-41", "PC-42")]
    # P9-03 continues across a page break; the factory table, not the prose typo
    # "1~4", specifies codes 0/1/2/3 and factory code 1 (8E1).
    for parameter in parameters:
        if parameter["code"] in ("P0-18", "P0-19"):
            parameter.update(
                description=parameter["description"].removesuffix(" (raw register)"),
                minimum=0, maximum=65000, maximum_raw=65000, scale=1, unit="s",
                scale_from="PC-09", scale_values={"0": 1, "1": 10, "2": 100},
                data_bits=16, read_only=False,
                note="Shown in seconds using PC-09 (0: 1 s; 1: 0.1 s; 2: 0.01 s). "
                     "Read together with PC-09; its live value is checked before writing.")
        if parameter["code"] == "P9-03":
            parameter.update(minimum=0, maximum=3, allowed_values=[0, 1, 2, 3])
        if parameter["code"] in ("P9-01", "P9-04"):
            parameter.update(minimum=1 if parameter["code"] == "P9-01" else 0,
                             maximum=247 if parameter["code"] == "P9-01" else 60,
                             scale=1 if parameter["code"] == "P9-01" else 10,
                             unit="" if parameter["code"] == "P9-01" else "s",
                             read_only=False, default="1" if parameter["code"] == "P9-01" else "0.0")
            parameter.pop("note", None)
    for number, description in ((0, "Operating state"), (16, "Active fault code")):
        parameters.append(dict(code=f"MB.{number:02}", description=description,
                               range="1: Forward; 2: Reverse; 3: Stopped" if number == 0 else "0: No fault; see decoded status",
                               minimum=0, maximum=65535, unit="", address=0x1200 + number, group="MB", default="",
                               scale=1, encoding="numeric", read_only=True, manual_pdf_page=194))
    try:
        from .vh5_support import apply_support
    except ImportError:  # script entry point
        from vh5_support import apply_support
    apply_support(parameters)
    for parameter in parameters:
        code = parameter["code"]
        source = by_code.get(code, [])
        if parameter["read_only"] and (any(r["modify"] in ("○", "×") for r in source) or code == "A1-11"):
            parameter["support_blocked"] = True
        if parameter["group"] == "P9":
            parameter["write_last"] = {"P9-02": 1, "P9-03": 2, "P9-01": 3, "P9-00": 4}.get(code, 0)
    return parameters, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    parameters, rows = extract(args.pdf)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "parameters.json").write_text(json.dumps(parameters, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    groups = dict.fromkeys(p["group"] for p in parameters)
    manifest = dict(key="xinje_vh5", manufacturer="XINJE", model="VH5-45P5-B — 5.5 kW / 380 V", series="VH5",
                    type_code="VH5-45P5-B", order=70,
                    label={"en": "VH5-45P5-B — 5.5 kW / 380 V", "ru": "VH5-45P5-B — 5.5 кВт / 380 В",
                           "sr": "VH5-45P5-B — 5.5 kW / 380 V"},
                    addressing="explicit", link=dict(protocol="modbus_rtu", baudrate=19200, bytesize=8,
                         parity="E", stopbits=1, timeout=1.0, device_id=1, device_id_limit=247, max_read_registers=12),
                    protocols={"modbus_rtu": dict(baudrate=19200, parity="E", stopbits=1,
                          baudrates=[300, 600, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200])},
                    groups={g: next(p["address"] >> 8 for p in parameters if p["group"] == g) for g in groups},
                    group_labels={lang: {g: GROUPS[g][index] for g in groups} for index, lang in enumerate(("en", "ru"))},
                    parameters="parameters.json", translations={"ru": "translations/ru.json"}, diagnostics="diagnostics.json",
                    manual_url="https://cdn-en.xinje.com/VH5%20frequency%20inverter%20manual.pdf",
                    source="XINJE INVC0620240409EN1.3.3, function tables PDF pp.42–80 and Modbus pp.190–195. "
                           "P9-03 factory code 1 selects 8E1, despite the appendix overview saying no parity. "
                           "No addresses are invented for local-only P8/A4 or U4. Reviewed dependent scales, units, bounds and hex masks are supported. "
                           "PF layout follows functional version P8-16, not P8-15; ambiguous revision encoding blocks writes. Unconfirmed digit packing stays read-only. "
                           "Only parameter FC06 EEPROM writes are used; no start, stop, speed-reference or reset commands are exposed.")
    (args.output / "profile.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from vh5_metadata import metadata
    ru, diagnostic = metadata(parameters)
    (args.output / "translations").mkdir(exist_ok=True)
    (args.output / "translations/ru.json").write_text(
        json.dumps({"parameters": {p["code"]: ru.get(p["code"], {}) for p in parameters}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "diagnostics.json").write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Extracted", len(parameters), "parameters; writable", sum(not p["read_only"] for p in parameters))
    print("Groups", dict(Counter(p["group"] for p in parameters)))
    print("Unsupported writes", [p["code"] for p in parameters if p.get("support_blocked")])
    # Source rows are a temporary audit, never a runtime dependency.
    (args.pdf.parent / "vh5-source-rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
