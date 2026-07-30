"""Function-code metadata for the ENC EDS800 inverter.

The values below are transcribed from section 5.2 of the EDS800 Series
Service Manual.  Modbus parameter addresses use the function group in the
high byte and the decimal function number in the low byte (for example,
F2.11 -> 0x020B).
"""

from __future__ import annotations

from typing import Any


_GROUP_IDS = {
    "F0": 0x00,
    "F1": 0x01,
    "F2": 0x02,
    "F3": 0x03,
    "F4": 0x04,
    "F5": 0x05,
    "F6": 0x06,
    "F7": 0x07,
    "F8": 0x08,
    "F9": 0x09,
    "Fd": 0x0D,
}

PARAMETERS: list[dict[str, Any]] = []


def _add(
    group: str,
    number: int,
    description: str,
    value_range: str,
    unit: str,
    default: str,
    scale: int = 1,
    *,
    encoding: str = "numeric",
    digits: int | None = None,
    digit_chars: str = "0123456789",
    read_only: bool = False,
) -> None:
    code = f"{group}.{number:02d}"
    minimum_text, maximum_text = value_range.split("~", maxsplit=1)
    parameter = {
        "code": code,
        "description": description,
        "unit": unit,
        "address": (_GROUP_IDS[group] << 8) | number,
        "group": group,
        "default": default,
        "scale": scale,
        "range": value_range,
        "minimum": float(minimum_text),
        "maximum": float(maximum_text),
        "encoding": encoding,
        "read_only": read_only,
        "change_while_running": True,
    }
    if digits is not None:
        parameter["digits"] = digits
        parameter["digit_chars"] = digit_chars
    PARAMETERS.append(parameter)


# F0 - basic run function parameters
_add("F0", 0, "Frequency input channel selection", "0~11", "", "1")
_add("F0", 1, "Frequency digital setting", "0~400", "Hz", "50.00", 100)
_add("F0", 2, "Run command channel selection", "0~4", "", "0")
_add(
    "F0",
    3,
    "Run direction setting",
    "000~111",
    "",
    "000",
    encoding="bcd",
    digits=3,
    digit_chars="01",
)
_add("F0", 4, "Acceleration/deceleration mode", "0~1", "", "0")
_add("F0", 5, "S-curve start section time", "10~50", "%", "20.0", 10)
_add("F0", 6, "S-curve rise time", "10~70", "%", "60.0", 10)
_add("F0", 7, "Acceleration/deceleration time unit", "0~1", "", "0")
_add("F0", 8, "Acceleration time 1", "0.1~6000", "s/min", "20.0", 10)
_add("F0", 9, "Deceleration time 1", "0.1~6000", "s/min", "20.0", 10)
_add("F0", 10, "Upper frequency limit", "0~400", "Hz", "50.00", 100)
_add("F0", 11, "Lower frequency limit", "0~400", "Hz", "0.00", 100)
_add("F0", 12, "Lower-limit frequency run mode", "0~1", "", "0")
_add("F0", 13, "Torque boost mode", "0~1", "", "0")
_add("F0", 14, "Torque boost", "0~20", "%", "4.0", 10)
_add("F0", 15, "V/F curve setting", "0~4", "", "0")


# F1 - start, stop and braking parameters
_add("F1", 0, "Start-up run mode", "0~2", "", "0")
_add("F1", 1, "Start-up frequency", "0~10", "Hz", "0.00", 100)
_add("F1", 2, "Start-up frequency duration", "0~20", "s", "0.0", 10)
_add("F1", 3, "Zero-frequency DC braking voltage", "0~15", "%", "0")
_add("F1", 4, "Zero-frequency DC braking time", "0~20", "s", "0.0", 10)
_add("F1", 5, "Stop mode", "0~2", "", "0")
_add("F1", 6, "DC braking start frequency at stop", "0~15", "Hz", "0.00", 100)
_add("F1", 7, "DC braking time at stop", "0~20", "s", "0.0", 10)
_add("F1", 8, "DC braking voltage at stop", "0~15", "%", "0")


# F2 - auxiliary run parameters
_add("F2", 0, "Analog filter time constant", "0~30", "s", "0.20", 100)
_add("F2", 1, "Forward/reverse dead time", "0~3600", "s", "0.1", 10)
_add("F2", 2, "Automatic energy-saving run", "0~1", "", "0")
_add("F2", 3, "Automatic voltage regulation (AVR)", "0~2", "", "0")
_add("F2", 4, "Slip frequency compensation", "0~150", "%", "0")
_add("F2", 5, "Carrier frequency", "2~15", "kHz", "Device-specific", 10)
_add("F2", 6, "Jog frequency", "0.1~50", "Hz", "5.00", 100)
_add("F2", 7, "Jog acceleration time", "0.1~60", "s", "20.0", 10)
_add("F2", 8, "Jog deceleration time", "0.1~60", "s", "20.0", 10)
_add("F2", 9, "Frequency input channel combination", "0~28", "", "0")
_add("F2", 10, "Master/slave frequency proportion", "0~500", "%", "100")
_add(
    "F2",
    11,
    "LED display control 1",
    "0000~1111",
    "",
    "1111",
    encoding="bcd",
    digits=4,
    digit_chars="01",
)
_add(
    "F2",
    12,
    "LED display control 2",
    "0000~1111",
    "",
    "1111",
    encoding="bcd",
    digits=4,
    digit_chars="01",
)
_add(
    "F2",
    13,
    "Parameter operation control",
    "000~432",
    "",
    "000",
    encoding="bcd",
    digits=3,
    digit_chars="01234",
)
_add(
    "F2",
    14,
    "Communication configuration",
    "000~125",
    "",
    "003",
    encoding="bcd",
    digits=3,
    digit_chars="012345",
)
_add("F2", 15, "Local Modbus address", "0~127", "", "1")
_add("F2", 16, "Communication timeout", "0~1000", "s", "0.0", 10)
_add("F2", 17, "Local response delay", "0~200", "ms", "5")

for number in range(18, 30):
    time_number = ((number - 18) // 2) + 2
    action = "Acceleration" if number % 2 == 0 else "Deceleration"
    _add("F2", number, f"{action} time {time_number}", "0.1~6000", "s/min", "20.0", 10)

_MULTISECTION_DEFAULTS = (
    "5.00",
    "10.00",
    "20.00",
    "30.00",
    "40.00",
    "45.00",
    "50.00",
    "5.00",
    "10.00",
    "20.00",
    "30.00",
    "40.00",
    "45.00",
    "50.00",
    "50.00",
)
for section, default in enumerate(_MULTISECTION_DEFAULTS, start=1):
    _add(
        "F2",
        29 + section,
        f"Multi-section frequency {section}",
        "0~400",
        "Hz",
        default,
        100,
    )

for jump in range(1, 4):
    base = 43 + (jump * 2)
    _add("F2", base, f"Jump frequency {jump}", "0~400", "Hz", "0.00", 100)
    _add("F2", base + 1, f"Jump frequency {jump} range", "0~30", "Hz", "0.00", 100)
_add("F2", 51, "Set run time", "0~65535", "h", "0")
_add("F2", 52, "Accumulated run time", "0~65535", "h", "0", read_only=True)


# F3 - closed-loop control parameters
_add("F3", 0, "Closed-loop control selection", "0~2", "", "0")
_add("F3", 1, "Setpoint channel selection", "0~3", "", "0")
_add("F3", 2, "Feedback channel selection", "0~6", "", "0")
_add("F3", 3, "Digital setpoint", "0~9.999", "V", "0.200", 1000)
_add("F3", 4, "Minimum setpoint", "0~100", "%", "0.0", 10)
_add("F3", 5, "Feedback at minimum setpoint", "0~100", "%", "0.0", 10)
_add("F3", 6, "Maximum setpoint", "0~100", "%", "100.0", 10)
_add("F3", 7, "Feedback at maximum setpoint", "0~100", "%", "100.0", 10)
_add("F3", 8, "Proportional gain Kp", "0~9.999", "", "0.150", 1000)
_add("F3", 9, "Integral gain Ki", "0~9.999", "", "0.150", 1000)
_add("F3", 10, "Differential gain Kd", "0~9.999", "", "0.000", 1000)
_add("F3", 11, "Sampling period T", "0.01~1", "s", "0.10", 100)
_add("F3", 12, "Deviation margin", "0~20", "%", "2.0", 10)
_add("F3", 13, "Integral separation threshold", "0~100", "%", "100.0", 10)
_add("F3", 14, "Closed-loop preset frequency", "0~400", "Hz", "0.00", 100)
_add("F3", 15, "Closed-loop preset holding time", "0~6000", "s", "0.0", 10)
_add("F3", 16, "Sleep frequency threshold", "0~400", "Hz", "0.01", 100)
_add("F3", 17, "Wake-up frequency threshold", "0~400", "Hz", "0.01", 100)
_add("F3", 18, "Sleep delay", "0~6000", "s", "0.0", 10)
_add("F3", 19, "Wake-up delay", "0~6000", "s", "0.0", 10)
_add("F3", 21, "Remote pressure gauge range", "0.001~9.999", "MPa", "1.000", 1000)
_add("F3", 26, "Water-supply monitoring display", "0~1", "", "0")
_add("F3", 27, "Closed-loop adjustment characteristic", "0~1", "", "0")
_add("F3", 28, "Initial monitoring parameter", "0~14", "", "1")
_add("F3", 29, "YCI input delay / feedback-loss delay", "0~9.999", "s", "0.0", 10)
_add("F3", 30, "Fault relay function selection", "0~24", "", "15")


# F4 - simple PLC parameters
_add(
    "F4",
    0,
    "Simple PLC run setting",
    "0000~3212",
    "",
    "0000",
    encoding="bcd",
    digits=4,
    digit_chars="0123",
)
for section in range(1, 8):
    setting_number = (section * 2) - 1
    _add(
        "F4",
        setting_number,
        f"PLC section {section} setting",
        "000~621",
        "",
        "000",
        encoding="bcd",
        digits=3,
        digit_chars="0123456",
    )
    _add(
        "F4",
        setting_number + 1,
        f"PLC section {section} run time",
        "0~6000",
        "s/min",
        "10.0",
        10,
    )


# F5 - terminal functions
for terminal in range(1, 6):
    _add("F5", terminal - 1, f"Input terminal X{terminal} function", "0~42", "", "0")
_add("F5", 8, "FWD/REV terminal control mode", "0~3", "", "0")
_add("F5", 9, "UP/DOWN speed", "0.01~99.99", "Hz/s", "1.00", 100)
_add("F5", 10, "Open-collector output function", "0~24", "", "0")
_add("F5", 14, "Frequency-arrival detection range", "0~50", "Hz", "5.00", 100)
_add("F5", 15, "FDT1 frequency level", "0~400", "Hz", "10.00", 100)
_add("F5", 16, "FDT1 hysteresis", "0~50", "Hz", "1.00", 100)
_add("F5", 17, "Analog output selection", "0~9", "", "0")
_add("F5", 18, "Analog output gain", "0~2", "", "1.00", 100)
_add("F5", 19, "Analog output offset", "0~10", "V", "0.00", 100)
_add("F5", 23, "DO terminal output selection", "0~9", "", "0")
_add("F5", 24, "DO maximum pulse frequency", "0.1~20", "kHz", "10.0", 10)
_add("F5", 25, "Counter final value", "0~9999", "", "0")
_add("F5", 26, "Counter specified value", "0~9999", "", "0")
_add("F5", 27, "Internal timer setting", "0.1~6000", "s", "60.0", 10)


# F6 - traverse function parameters
_add("F6", 0, "Traverse function selection", "0~1", "", "0")
_add(
    "F6",
    1,
    "Traverse run mode",
    "00~11",
    "",
    "00",
    encoding="bcd",
    digits=2,
    digit_chars="01",
)
_add("F6", 2, "Traverse amplitude", "0~50", "%", "0.0", 10)
_add("F6", 3, "Jump frequency", "0~50", "%", "0.0", 10)
_add("F6", 4, "Traverse cycle", "0.1~999.9", "s", "10.0", 10)
_add("F6", 5, "Triangle-wave rise time", "0~98", "%", "50.0", 10)
_add("F6", 6, "Traverse preset frequency", "0~400", "Hz", "0.00", 100)
_add("F6", 7, "Traverse preset delay", "0~6000", "s", "0.0", 10)


# F7 - frequency input scaling
_add("F7", 0, "VCI minimum input", "0~10", "V", "0.00", 100)
_add("F7", 1, "VCI minimum-input frequency", "0~400", "Hz", "0.00", 100)
_add("F7", 2, "VCI maximum input", "0~10", "V", "10.00", 100)
_add("F7", 3, "VCI maximum-input frequency", "0~400", "Hz", "50.00", 100)
_add("F7", 4, "CCI minimum input", "0~10", "V", "0.00", 100)
_add("F7", 5, "CCI minimum-input frequency", "0~400", "Hz", "0.00", 100)
_add("F7", 6, "CCI maximum input", "0~10", "V", "10.00", 100)
_add("F7", 7, "CCI maximum-input frequency", "0~400", "Hz", "50.00", 100)
_add("F7", 8, "Maximum PWM input pulse width", "0.1~999.9", "ms", "100.0", 10)
_add("F7", 9, "Minimum PWM setting pulse width", "0~999.9", "ms", "0.0", 10)
_add("F7", 10, "Minimum PWM setting frequency", "0~400", "Hz", "0.00", 100)
_add("F7", 11, "Maximum PWM setting pulse width", "0~999.9", "ms", "100.0", 10)
_add("F7", 12, "Maximum PWM setting frequency", "0~400", "Hz", "50.00", 100)
_add("F7", 13, "PULSE maximum input frequency", "0.1~20", "kHz", "10.0", 10)
_add("F7", 14, "PULSE minimum setting", "0~20", "kHz", "0.0", 10)
_add("F7", 15, "PULSE minimum setting frequency", "0~400", "Hz", "0.00", 100)
_add("F7", 16, "PULSE maximum setting", "0~20", "kHz", "10.0", 10)
_add("F7", 17, "PULSE maximum setting frequency", "0~400", "Hz", "50.00", 100)


# F8 - motor parameters
_add("F8", 1, "Motor rated voltage", "1~480", "V", "Device-specific")
_add("F8", 2, "Motor rated current", "0.1~999.9", "A", "Device-specific", 10)
_add("F8", 3, "Motor rated frequency", "1~400", "Hz", "Device-specific", 100)
_add("F8", 4, "Motor rated speed", "1~9999", "r/min", "Device-specific")
_add("F8", 5, "Motor pole count", "2~14", "", "Device-specific")
_add("F8", 6, "Motor rated power", "0.1~999.9", "kW", "Device-specific", 10)
_add("F8", 16, "Frequency display offset", "0~2", "Hz", "0.20", 100)


# F9 - protection parameters
_add("F9", 0, "Power-loss restart delay", "0~10", "s", "0.0", 10)
_add("F9", 1, "Automatic fault-reset attempts", "0~10", "", "0")
_add("F9", 2, "Automatic fault-reset interval", "0.5~20", "s", "5.0", 10)
_add("F9", 3, "Motor overload protection mode", "0~1", "", "1")
_add("F9", 4, "Motor overload protection coefficient", "20~120", "%", "100.0", 10)
_add("F9", 5, "Overload warning threshold", "20~200", "%", "130")
_add("F9", 6, "Overload warning delay", "0~20", "s", "5.0", 10)
_add("F9", 7, "Overvoltage stall selection", "0~1", "", "1")
_add("F9", 8, "Overvoltage stall point", "120~150", "%", "140")
_add("F9", 9, "Automatic current-limit level", "110~200", "%", "150")
_add("F9", 10, "Current-limit frequency reduction rate", "0~99.99", "Hz/s", "10.00", 100)
_add("F9", 11, "Current limiting during constant speed", "0~1", "", "0")


# Fd - read-only fault history
for failure_index in range(6):
    labels = ("latest", "second", "third", "fourth", "fifth", "sixth")
    _add(
        "Fd",
        failure_index,
        f"{labels[failure_index].capitalize()} fault record",
        "0~23",
        "",
        "0",
        read_only=True,
    )
_add("Fd", 6, "Set frequency at latest fault", "0~400", "Hz", "0", 100, read_only=True)
_add("Fd", 7, "Output frequency at latest fault", "0~400", "Hz", "0", 100, read_only=True)
_add("Fd", 8, "Output current at latest fault", "0~999.9", "A", "0", 10, read_only=True)
_add("Fd", 9, "Output voltage at latest fault", "0~999", "V", "0", read_only=True)
_add("Fd", 10, "DC bus voltage at latest fault", "0~800", "V", "0", read_only=True)
_add("Fd", 11, "Motor speed at latest fault", "0~9999", "r/min", "0", read_only=True)
_add("Fd", 12, "Module temperature at latest fault", "0~100", "°C", "0", read_only=True)
_add("Fd", 13, "Input terminal state at latest fault", "0~65535", "", "0", read_only=True)
_add("Fd", 14, "Accumulated run time at latest fault", "0~65535", "h", "0", read_only=True)


_codes = [parameter["code"] for parameter in PARAMETERS]
_addresses = [parameter["address"] for parameter in PARAMETERS]
if len(_codes) != len(set(_codes)):
    raise RuntimeError("Duplicate EDS800 function codes in parameter table")
if len(_addresses) != len(set(_addresses)):
    raise RuntimeError("Duplicate EDS800 Modbus addresses in parameter table")
