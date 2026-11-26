"""Build the FC 51 catalogue from Danfoss MG02C602, not an ENC register map.

Usage: python tools/extract_fc51_parameters.py EN.pdf RU.pdf profiles/danfoss_fc51
The English parameter-list tables supply bus types/conversion indices. Curated
limits below resolve ambiguities in the four-column overview. The older Russian
manual supplies names only: its ranges must not replace the newer English map.
pdfplumber is needed only when regenerating the catalogue.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

CODE = re.compile(r"^(\d{1,2}-\d{2})\s+(.+)")

# Engineering limits, independently checked against the detailed descriptions.
# Bus precision comes from the conversion-index tables, not printed decimals.
RANGES = """
0-31|0|9999|
0-32|0|9999|
0-60|0|999|
1-22|50|999|V
1-23|20|400|Hz
1-24|0.01|100|A
1-25|100|9999|rpm
1-30|0|655.35|Ω
1-33|0|42949672.95|Ω
1-35|0|42949672.95|Ω
1-50|0|300|%
1-52|0|10|Hz
1-55|0|999|V
1-56|0|400|Hz
1-60|0|199|%
1-61|0|199|%
1-62|-400|399|%
1-63|0.05|5|s
1-71|0|10|s
1-82|0|20|Hz
2-00|0|150|%
2-01|0|150|%
2-02|0|60|s
2-04|0|400|Hz
2-11|5|5000|Ω
2-16|0|150|%
2-20|0|100|A
2-22|0|400|Hz
3-02|-4999|4999|
3-03|-4999|4999|
3-10|-100|100|%
3-11|0|400|Hz
3-12|0|100|%
3-14|-100|100|%
3-41|0.05|3600|s
3-42|0.05|3600|s
3-51|0.05|3600|s
3-52|0.05|3600|s
3-80|0.05|3600|s
3-81|0.05|3600|s
4-12|0|400|Hz
4-14|0.1|400|Hz
4-16|0|400|%
4-17|0|400|%
4-40|0|400|Hz
4-41|0|400|Hz
4-50|0|100|A
4-51|0|100|A
4-54|-4999|4999|
4-55|-4999|4999|
4-56|-4999|4999|
4-57|-4999|4999|
4-61|0|400|Hz
4-63|0|400|Hz
5-34|0|600|s
5-35|0|600|s
5-41|0|600|s
5-42|0|600|s
5-55|20|4999|Hz
5-56|21|5000|Hz
5-57|-4999|4999|
5-58|-4999|4999|
6-00|1|99|s
6-10|0|9.9|V
6-11|0.1|10|V
6-12|0|19.9|mA
6-13|0.1|20|mA
6-14|-4999|4999|
6-15|-4999|4999|
6-16|0.01|10|s
6-22|0|19.9|mA
6-23|0.1|20|mA
6-24|-4999|4999|
6-25|-4999|4999|
6-26|0.01|10|s
6-81|-4999|4999|
6-82|-4999|4999|
6-93|0|200|%
6-94|0|200|%
7-32|0|200|Hz
7-33|0|10|
7-34|0.1|9999|s
7-38|0|400|%
7-39|0|200|%
8-03|0.1|6500|s
8-31|1|247|
8-35|0.001|0.5|s
8-36|0.01|10|s
8-94|-32768|32767|
13-12|-9999|9999|
13-20|0|3600|s
14-21|0|600|s
14-41|40|75|%
15-00|0|65535|days
15-01|0|2147483647|h
15-02|0|65535|kWh
15-03|0|2147483647|
15-04|0|65535|
15-05|0|65535|
15-30|0|255|
16-00|0|65535|
16-01|-4999|4999|
16-02|-200|200|%
16-03|0|65535|
16-05|-100|100|%
16-09|0|9999|
16-10|0|99|kW
16-11|0|99|hp
16-12|0|999.9|V
16-13|0|400|Hz
16-14|0|655|A
16-15|-100|100|%
16-18|0|100|%
16-30|0|10000|V
16-34|0|255|°C
16-35|0|100|%
16-36|0.01|655|A
16-37|0.1|655|A
16-38|0|255|
16-50|-200|200|%
16-51|-200|200|%
16-52|-4999|4999|
16-60|0|65535|
16-61|0|1|
16-62|0|10|V
16-63|0|20|mA
16-64|0|20|mA
16-65|0|20|mA
16-68|20|5000|Hz
16-71|0|1|
16-72|-32768|32767|
16-73|-32768|32767|
16-86|-32768|32767|
16-90|0|4294967295|
16-92|0|4294967295|
16-94|0|4294967295|
"""

ARRAYS = {
    "1-55": 6, "1-56": 6, "3-10": 8, "4-61": 2, "4-63": 2,
    "8-43": 16, "13-10": 4, "13-11": 4, "13-12": 4, "13-20": 3,
    "13-40": 4, "13-41": 4, "13-42": 4, "13-43": 4, "13-44": 4,
    "13-51": 20, "13-52": 20, "15-30": 10,
}
ACTION_ONLY = set("0-03 0-10 0-11 0-12 0-50 0-51 1-29 8-06 8-30 8-31 8-32 8-33 8-94 13-03 14-22 15-06 15-07".split())
INHERIT_OPTIONS = {
    **{c: "5-10" for c in ("5-11", "5-12", "5-13", "5-15")},
    "6-92": "5-40", **{f"8-{n}": "8-50" for n in range(51, 57)},
    "13-02": "13-01", "13-40": "13-01", "13-42": "13-01",
    "13-44": "13-01", "13-51": "13-01", "13-43": "13-41",
}
# Concise option labels; the numeric selectors are the values sent over Modbus.
ENUMS = """
0-03|0:International=Международные;1:US=США
0-04|0:Resume=Возобновить;1:Stop, keep reference=Останов, сохранить задание;2:Stop, zero reference=Останов, обнулить задание
0-10|1:Set-up 1=Набор 1;2:Set-up 2=Набор 2;9:Multi set-up=Несколько наборов
0-11|1:Set-up 1=Набор 1;2:Set-up 2=Набор 2;9:Active set-up=Активный набор
0-12|0:Not linked=Не связаны;20:Linked=Связаны
0-40|0:Disabled=Запрещено;1:Enabled=Разрешено
0-41|0:Disable all=Запретить всё;1:Enable all=Разрешить всё;2:Reset only=Только сброс
0-42|0:Disabled=Запрещено;1:Enabled=Разрешено
0-50|0:No copy=Не копировать;1:All to LCP=Всё в LCP;2:All from LCP=Всё из LCP;3:Size-independent from LCP=Из LCP без параметров мощности
0-51|0:No copy=Не копировать;1:From set-up 1=Из набора 1;2:From set-up 2=Из набора 2;9:Factory set-up=Заводской набор
0-61|0:Full access=Полный доступ;1:LCP read only=Чтение с LCP;2:No LCP access=Нет доступа с LCP
1-00|0:Speed open loop=Скорость без обратной связи;3:Process=Регулирование процесса
1-01|0:U/f=U/f;1:VVC+=VVC+
1-03|0:Constant torque=Постоянный момент;2:Automatic energy optimisation=Автоматическая оптимизация энергии
1-05|0:Speed open loop=Скорость без обратной связи;2:As parameter 1-00=Как в параметре 1-00
1-29|0:Off=Выключено;2:Enable AMT=Включить автонастройку двигателя
1-72|0:DC hold during delay=Удержание постоянным током;1:DC brake during delay=Торможение постоянным током;2:Coast during delay=Выбег во время задержки
1-73|0:Disabled=Запрещено;1:Enabled=Разрешено
1-80|0:Coast=Выбег;1:DC hold=Удержание постоянным током
1-90|0:No protection=Без защиты;1:Thermistor warning=Предупреждение термистора;2:Thermistor trip=Отключение по термистору;3:ETR warning=Предупреждение ЭТР;4:ETR trip=Отключение по ЭТР
1-93|0:None=Нет;1:Analog input 53=Аналоговый вход 53;6:Digital input 29=Дискретный вход 29
2-10|0:Off=Выключено;1:Resistor brake=Резистивное торможение;2:AC brake=Торможение переменным током
2-17|0:Disabled=Запрещено;1:Enabled except at stop=Включено кроме останова;2:Enabled=Включено
3-00|0:Minimum to maximum=От минимума до максимума;1:Negative maximum to maximum=От минус максимума до максимума
3-15|0:No function=Нет функции;1:Analog input 53=Аналоговый вход 53;2:Analog input 60=Аналоговый вход 60;8:Pulse input 33=Импульсный вход 33;11:Local bus reference=Задание по шине;21:LCP potentiometer=Потенциометр LCP
3-40|0:Linear=Линейный;2:Sine squared=Синусоидальный S-образный
3-50|0:Linear=Линейный;2:Sine squared=Синусоидальный S-образный
4-10|0:Clockwise=По часовой стрелке;1:Counterclockwise=Против часовой стрелки;2:Both directions=Оба направления
4-58|0:Off=Выключено;1:On=Включено
5-10|0:No function=Нет функции;1:Reset=Сброс;2:Coast inverse=Выбег, инверсный;3:Coast and reset inverse=Выбег и сброс, инверсные;4:Quick stop inverse=Быстрый останов, инверсный;5:DC brake inverse=Торможение пост. током, инверсное;6:Stop inverse=Останов, инверсный;8:Start=Пуск;9:Latched start=Импульсный пуск;10:Reversing=Реверс;11:Start reversing=Пуск с реверсом;12:Enable forward start=Разрешить прямой пуск;13:Enable reverse start=Разрешить обратный пуск;14:Jog=Фиксированная скорость;16:Preset reference bit 0=Бит 0 заданной скорости;17:Preset reference bit 1=Бит 1 заданной скорости;18:Preset reference bit 2=Бит 2 заданной скорости;19:Freeze reference=Зафиксировать задание;20:Freeze output=Зафиксировать выход;21:Speed up=Увеличить скорость;22:Speed down=Уменьшить скорость;23:Set-up select bit 0=Бит 0 выбора набора;26:Precise stop inverse=Точный останов, инверсный;27:Start, precise stop=Пуск, точный останов;28:Catch up=Увеличить задание;29:Slow down=Уменьшить задание;32:Pulse input=Импульсный вход;34:Ramp select bit 0=Бит выбора темпа;60:Counter A up=Счётчик A вверх;61:Counter A down=Счётчик A вниз;62:Reset counter A=Сброс счётчика A;63:Counter B up=Счётчик B вверх;64:Counter B down=Счётчик B вниз;65:Reset counter B=Сброс счётчика B
5-40|0:No operation=Нет функции;1:Control ready=Управление готово;2:Drive ready=Привод готов;3:Drive ready, remote=Привод готов, дистанционно;4:Enable, no warning=Разрешение без предупреждения;5:Drive running=Привод работает;6:Running, no warning=Работа без предупреждения;7:In range, no warning=В диапазоне без предупреждения;8:On reference, no warning=На задании без предупреждения;9:Alarm=Авария;10:Alarm or warning=Авария или предупреждение;12:Current outside range=Ток вне диапазона;13:Current below minimum=Ток ниже минимума;14:Current above maximum=Ток выше максимума;16:Frequency below minimum=Частота ниже минимума;17:Frequency above maximum=Частота выше максимума;19:Feedback below minimum=Обратная связь ниже минимума;20:Feedback above maximum=Обратная связь выше максимума;21:Thermal warning=Тепловое предупреждение;22:Ready, no thermal warning=Готов без теплового предупреждения;23:Remote ready, no thermal warning=Дистанционно готов без теплового предупреждения;24:Ready, voltage OK=Готов, напряжение в норме;25:Reverse=Реверс;26:Bus OK=Связь в норме;28:Brake, no warning=Торможение без предупреждения;29:Brake ready, no fault=Тормоз готов без ошибки;30:Brake IGBT fault=Ошибка IGBT тормоза;32:Mechanical brake control=Управление механическим тормозом;36:Control word bit 11=Бит 11 командного слова;41:Reference below minimum=Задание ниже минимума;42:Reference above maximum=Задание выше максимума;51:Local reference=Местное задание;52:Remote reference=Дистанционное задание;53:No alarm=Нет аварии;54:Start command active=Активна команда пуска;55:Running reverse=Работа с реверсом;56:Hand mode=Ручной режим;57:Auto mode=Автоматический режим;60:Comparator 0=Компаратор 0;61:Comparator 1=Компаратор 1;62:Comparator 2=Компаратор 2;63:Comparator 3=Компаратор 3;70:Logic rule 0=Логическое правило 0;71:Logic rule 1=Логическое правило 1;72:Logic rule 2=Логическое правило 2;73:Logic rule 3=Логическое правило 3;81:SL digital output B=Дискретный выход B контроллера SL
6-01|0:Off=Выключено;1:Freeze output=Зафиксировать выход;2:Stop=Останов;3:Jog=Фиксированная скорость;4:Maximum speed=Максимальная скорость;5:Stop and trip=Останов и отключение
6-19|0:Voltage mode=Режим напряжения;1:Current mode=Режим тока
6-80|0:Disabled=Запрещено;1:Enabled=Разрешено
6-90|0:0–20 mA=0–20 мА;1:4–20 mA=4–20 мА;2:Digital output=Дискретный выход
6-91|0:No operation=Нет функции;10:Output frequency=Выходная частота;11:Reference=Задание;12:Feedback=Обратная связь;13:Motor current=Ток двигателя;16:Power=Мощность;20:Bus reference=Задание по шине
7-20|0:No function=Нет функции;1:Analog input 53=Аналоговый вход 53;2:Analog input 60=Аналоговый вход 60;8:Pulse input 33=Импульсный вход 33;11:Local bus reference=Задание по шине
7-30|0:Normal=Прямое;1:Inverse=Инверсное
7-31|0:Disabled=Выключено;1:Enabled=Включено
8-01|0:Digital and control word=Входы и командное слово;1:Digital only=Только входы;2:Control word only=Только командное слово
8-02|0:None=Нет;1:FC RS-485=FC RS-485
8-04|0:Off=Выключено;1:Freeze output=Зафиксировать выход;2:Stop=Останов;3:Jog=Фиксированная скорость;4:Maximum speed=Максимальная скорость;5:Stop and trip=Останов и отключение
8-06|0:No function=Нет функции;1:Reset=Сбросить
8-30|0:FC protocol=Протокол FC;2:Modbus RTU=Modbus RTU
8-32|0:2400 baud=2400 бод;1:4800 baud=4800 бод;2:9600 baud=9600 бод;3:19200 baud=19200 бод;4:38400 baud=38400 бод
8-33|0:Even parity, 1 stop bit=Чётность, 1 стоп-бит;1:Odd parity, 1 stop bit=Нечётность, 1 стоп-бит;2:No parity, 1 stop bit=Без чётности, 1 стоп-бит;3:No parity, 2 stop bits=Без чётности, 2 стоп-бита
8-50|0:Digital input=Дискретный вход;1:Bus=Шина;2:Logical AND=Логическое И;3:Logical OR=Логическое ИЛИ
13-00|0:Off=Выключено;1:On=Включено
13-01|0:False=Ложь;1:True=Истина;2:Running=Работа;3:In range=В диапазоне;4:On reference=На задании;7:Current outside range=Ток вне диапазона;8:Current below minimum=Ток ниже минимума;9:Current above maximum=Ток выше максимума;16:Thermal warning=Тепловое предупреждение;17:Mains outside range=Сеть вне диапазона;18:Reversing=Реверс;19:Warning=Предупреждение;20:Trip=Аварийное отключение;21:Trip lock=Отключение с блокировкой;22:Comparator 0=Компаратор 0;23:Comparator 1=Компаратор 1;24:Comparator 2=Компаратор 2;25:Comparator 3=Компаратор 3;26:Logic rule 0=Логическое правило 0;27:Logic rule 1=Логическое правило 1;28:Logic rule 2=Логическое правило 2;29:Logic rule 3=Логическое правило 3;33:Digital input 18=Дискретный вход 18;34:Digital input 19=Дискретный вход 19;35:Digital input 27=Дискретный вход 27;36:Digital input 29=Дискретный вход 29;38:Digital input 33=Дискретный вход 33;39:Start command=Команда пуска;40:Drive stopped=Привод остановлен
13-03|0:Do not reset=Не сбрасывать;1:Reset SLC=Сбросить контроллер SLC
13-10|0:Disabled=Выключено;1:Reference=Задание;2:Feedback=Обратная связь;3:Motor speed=Скорость двигателя;4:Motor current=Ток двигателя;6:Motor power=Мощность двигателя;7:Motor voltage=Напряжение двигателя;8:DC link voltage=Напряжение звена пост. тока;12:Analog input 53=Аналоговый вход 53;13:Analog input 60=Аналоговый вход 60;18:Pulse input 33=Импульсный вход 33;20:Alarm number=Номер аварии;30:Counter A=Счётчик A;31:Counter B=Счётчик B
13-11|0:Less than=Меньше;1:Approximately equal=Приблизительно равно;2:Greater than=Больше
13-41|0:Disabled=Выключено;1:AND=И;2:OR=ИЛИ;3:AND NOT=И НЕ;4:OR NOT=ИЛИ НЕ;5:NOT AND=НЕ И;6:NOT OR=НЕ ИЛИ;7:NOT AND NOT=НЕ И НЕ;8:NOT OR NOT=НЕ ИЛИ НЕ
13-52|0:Disabled=Выключено;1:No action=Нет действия;2:Select set-up 1=Выбрать набор 1;3:Select set-up 2=Выбрать набор 2;10:Preset reference 0=Заданная скорость 0;11:Preset reference 1=Заданная скорость 1;12:Preset reference 2=Заданная скорость 2;13:Preset reference 3=Заданная скорость 3;14:Preset reference 4=Заданная скорость 4;15:Preset reference 5=Заданная скорость 5;16:Preset reference 6=Заданная скорость 6;17:Preset reference 7=Заданная скорость 7;18:Select ramp 1=Выбрать темп 1;19:Select ramp 2=Выбрать темп 2;22:Run=Пуск;23:Run reverse=Пуск с реверсом;24:Stop=Останов;25:Quick stop=Быстрый останов;26:DC stop=Останов постоянным током;27:Coast=Выбег;28:Freeze output=Зафиксировать выход;29:Start timer 0=Запустить таймер 0;30:Start timer 1=Запустить таймер 1;31:Start timer 2=Запустить таймер 2;32:Digital output 42 low=Выход 42 выключен;33:Relay low=Реле выключено;38:Digital output 42 high=Выход 42 включён;39:Relay high=Реле включено;60:Reset counter A=Сбросить счётчик A;61:Reset counter B=Сбросить счётчик B
14-01|0:2 kHz=2 кГц;1:4 kHz=4 кГц;2:8 kHz=8 кГц;4:16 kHz=16 кГц
14-03|0:Off=Выключено;1:On=Включено
14-12|0:Trip=Отключение;1:Warning=Предупреждение;2:Disabled=Выключено
14-22|0:Normal operation=Нормальная работа;2:Initialisation=Инициализация
14-26|0:Trip=Отключение;1:Warning=Предупреждение
15-06|0:Do not reset=Не сбрасывать;1:Reset counter=Сбросить счётчик
15-07|0:Do not reset=Не сбрасывать;1:Reset counter=Сбросить счётчик
"""


def enum_catalogue():
    labels = {}
    for line in ENUMS.strip().splitlines():
        code, entries = line.split("|", 1)
        labels[code] = {}
        for entry in entries.split(";"):
            value, text = entry.split(":", 1)
            labels[code][int(value)] = tuple(text.split("=", 1))
    for code, source in INHERIT_OPTIONS.items():
        labels[code] = dict(labels[source])
    for code in ("3-16", "3-17", "3-18"):
        labels[code] = dict(labels["3-15"])
    for code in ("5-10", "5-11", "5-12", "5-13"):
        for value in (26, 27, 32):
            labels[code].pop(value, None)
    labels["6-92"][80] = ("SL digital output A", "Дискретный выход A контроллера SL")
    for code in ("13-02", "13-40", "13-42", "13-44", "13-51"):
        labels[code].update({30 + n: (f"Timer {n} elapsed", f"Таймер {n} истёк") for n in range(3)})
    powers = (0.09, 0.12, 0.18, 0.25, 0.37, 0.55, 0.75, 1.1, 1.5, 2.2, 3, 3.7, 4, 5.5, 7.5, 11, 15, 18.5, 22, 30)
    labels["1-20"] = {n: (f"{power:g} kW", f"{power:g} кВт") for n, power in enumerate(powers, 1)}
    labels["14-20"] = {0: ("Manual reset", "Ручной сброс"), **{n: (f"Auto reset {n} times", f"Автосброс {n} раз") for n in range(1, 11)}, 11: ("Auto reset 15 times", "Автосброс 15 раз"), 12: ("Auto reset 20 times", "Автосброс 20 раз"), 13: ("Infinite auto reset", "Неограниченный автосброс"), 14: ("Reset at power-up", "Сброс при включении питания")}
    pcd_codes = ("None", "15-00", "15-01", "15-02", "16-00", "16-01", "16-02", "16-03", "16-05", "16-09", "16-10", "16-11", "16-12", "16-13", "16-14", "16-15", "16-18", "16-30", "16-34", "16-35", "16-38", "16-50", "16-51", "16-52", "16-60", "16-61", "16-62", "16-63", "16-64", "16-65", "16-68", "16-71", "16-72", "16-73", "16-90", "16-92", "16-94")
    labels["8-43"] = {n: (code, code) if n else ("None", "Нет") for n, code in enumerate(pcd_codes)}
    return labels
def normal(text):
    return re.sub(r"\s+", " ", text or "").strip()


def metadata(manual):
    rows = {}
    for pdf_page, page in enumerate(manual.pages[56:64], 57):
        for table in page.extract_tables():
            for row in table:
                if len(row) == 7 and re.fullmatch(r"\d{1,2}-\d{2}", row[0] or ""):
                    rows[row[0]] = [normal(c) for c in row] + [pdf_page]
    if len(rows) < 200:
        raise ValueError("Expected the MG02C602 English parameter-list tables")
    return rows


def russian_names(manual):
    names = {}
    for page in manual.pages[15:92]:
        for line in (page.extract_text() or "").splitlines():
            if match := CODE.match(line):
                names.setdefault(match[1], normal(match[2]))
    return names


def extract(english_pdf, russian_pdf):
    import pdfplumber

    limits = {code: (float(low), float(high), unit) for code, low, high, unit in
              (line.split("|") for line in RANGES.strip().splitlines())}
    with pdfplumber.open(english_pdf) as manual:
        rows = metadata(manual)
    enums = enum_catalogue()
    with pdfplumber.open(russian_pdf) as manual:
        ru_names = russian_names(manual)
    # Names added after the older Russian translation, or misleading source names.
    ru_names.update({
        "0-03": "Региональные настройки",
        "0-04": "Состояние после включения питания в ручном режиме",
        "0-31": "Минимальный масштаб пользовательской индикации",
        "0-32": "Максимальный масштаб пользовательской индикации",
        "0-61": "Доступ к главному и быстрому меню без пароля",
        "3-10": "Предустановленное задание",
        "3-12": "Шаг увеличения/уменьшения задания",
        "3-41": "Время разгона 1",
        "1-35": "Главное индуктивное сопротивление (Xh)",
        "1-93": "Вход подключения термистора",
        "4-16": "Предел момента в двигательном режиме",
        "4-17": "Предел момента в генераторном режиме",
        "5-40": "Функция релейного выхода",
        "4-40": "Предупреждение: низкая частота",
        "4-41": "Предупреждение: высокая частота",
        "4-54": "Предупреждение: низкое задание",
        "4-55": "Предупреждение: высокое задание",
        "4-56": "Предупреждение: низкая обратная связь",
        "4-57": "Предупреждение: высокая обратная связь",
        "5-34": "Задержка включения дискретного выхода 42",
        "5-35": "Задержка выключения дискретного выхода 42",
        "5-41": "Задержка включения реле",
        "5-42": "Задержка выключения реле",
        "6-26": "Клемма 60, постоянная времени фильтра",
        "6-80": "Разрешение потенциометра LCP",
        "7-30": "Прямое или инверсное действие ПИ-регулятора",
        "7-31": "Ограничение интегральной составляющей ПИ-регулятора",
        "7-32": "Начальная частота ПИ-регулятора",
        "7-33": "Пропорциональный коэффициент ПИ-регулятора",
        "7-34": "Время интегрирования ПИ-регулятора",
        "7-38": "Коэффициент прямой связи ПИ-регулятора",
        "8-43": "Конфигурация чтения PCD порта FC",
        "13-12": "Порог сравнения",
        "13-42": "Булева переменная логического соотношения 2",
        "15-02": "Счётчик электроэнергии, кВт·ч",
        "15-06": "Сброс счётчика электроэнергии",
        "14-26": "Действие при неисправности инвертора",
        "15-43": "Версия программного обеспечения",
        "16-72": "Счётчик A", "16-73": "Счётчик B",
        "16-09": "Пользовательская индикация",
        "16-35": "Тепловая нагрузка инвертора",
        "16-36": "Номинальный ток инвертора",
        "16-37": "Максимальный ток инвертора",
        "16-38": "Состояние контроллера Smart Logic",
        "16-50": "Внешнее задание",
        "16-51": "Импульсное задание",
        "16-52": "Обратная связь, единицы процесса",
        "16-60": "Состояние дискретных входов 18, 19, 27, 33",
        "16-61": "Состояние дискретного входа 29",
        "16-62": "Аналоговый вход 53, напряжение",
        "16-63": "Аналоговый вход 53, ток",
        "16-64": "Аналоговый вход 60",
        "16-65": "Аналоговый выход 42",
        "16-68": "Частота импульсного входа 33",
        "16-71": "Состояние релейного выхода",
        "16-86": "Задание 1 порта FC",
        "16-90": "Слово аварий",
        "16-92": "Слово предупреждений",
        "16-94": "Расширенное слово состояния",
    })
    parameters, translations = [], {}
    for code, row in rows.items():
        _, name, default, setup, running, conversion, data_type, pdf_page = row
        group, number = code.split("-")
        text_type = data_type == "VisibleString"
        bits = 160 if text_type else int(re.search(r"\d+", data_type)[0])
        scale = 10 ** -(0 if conversion == "-" else int(conversion.rstrip("-") or "0"))
        labels = enums.get(code, {})
        options = sorted(labels)
        is_enum = conversion == "-" or code == "8-30"
        if is_enum and not options:
            raise ValueError(f"{code}: missing enum options")
        if text_type:
            low, high, unit = 0, 0, ""
        elif is_enum:
            low, high, unit = min(options), max(options), ""
        else:
            if code not in limits:
                raise ValueError(f"{code}: no verified engineering limits")
            low, high, unit = limits[code]
        # Defaults are values, never a unit-bearing source string.
        found_default = re.match(r"\[([-+\d.]+)\]|([-+\d.]+)", default)
        default_value = (found_default[1] or found_default[2]) if found_default else ""
        default_note = ""
        if code in ("1-20", "1-22", "1-24", "1-25", "1-30", "1-33", "1-35", "1-55", "1-56", "4-51", "8-32"):
            default_value = ""
            default_note = "Depends on motor, drive size, regional settings or protocol"
        if code == "0-32":
            default_value = "100"  # detailed description, not the erroneous 0 in list 5.8
        if code == "2-11":
            default_value = "5"
        p = dict(code=code, description=name, range=("; ".join(f"{n}: option {n}" for n in options) if is_enum else f"{low:g} ~ {high:g}"),
                 minimum=low, maximum=high, unit=unit, address=10 * (int(group) * 100 + int(number)) - 1,
                 group=group, default=default_value, scale=scale, encoding="text" if text_type else "numeric",
                 read_only=(group == "16" or group == "15" and code not in ("15-06", "15-07")),
                 register_count=10 if text_type else max(1, bits // 16), data_bits=bits,
                 signed=data_type.startswith("Int"), change_while_running=running == "TRUE",
                 setup=setup, conversion_index=conversion, data_type=data_type,
                 manual_pdf_page=pdf_page)
        if default_note:
            p["default_note"] = default_note
        if is_enum:
            p["allowed_values"] = options
            p["range"] = "; ".join(f"{n}: {labels[n][0]}" for n in options)
        if code in ACTION_ONLY:
            p["write_only_if_edited"] = True
        if code in ("8-30", "8-31", "8-32", "8-33"):
            p["write_last"] = 1
        ru_name = ru_names.get(code)
        if not ru_name:
            raise ValueError(f"{code}: missing Russian name")
        # Numeric ranges are language-independent; enum labels are refined below.
        ru = {"description": ru_name, "range": "; ".join(f"{n}: {labels[n][1]}" for n in options) if is_enum else p["range"]}
        if text_type:
            p["range"] = "ASCII text, up to 20 characters"
            ru["range"] = "Текст ASCII, до 20 символов"
        if default_note:
            ru["default_note"] = "Зависит от двигателя, мощности привода, региона или протокола"
        if code in ("1-30", "1-33", "1-35"):
            p["note"] = "The manual specifies no numeric limit; the shown bounds are the bus data-type capacity."
            ru["note"] = "В руководстве числовые границы не заданы; показана ёмкость типа данных протокола."
        if code in ("1-55", "1-56"):
            p["note"] = "Bus precision follows conversion index 0 in table 5.9. Where descriptions disagree, the common range is used. Confirm against the keypad before editing."
            ru["note"] = "Точность обмена взята из индекса 0 таблицы 5.9. При расхождении описаний используется общий диапазон. Перед изменением сверьте с панелью."
        if code in ("6-10", "6-11", "6-12", "6-13", "6-22", "6-23"):
            p["note"] = "The overview and detailed descriptions disagree at the endpoints. The common range is used."
            ru["note"] = "Границы в сводной таблице и подробном описании расходятся. Использован общий диапазон обоих источников."
        if code in ("16-10", "16-11", "16-12", "16-15"):
            p["note"] = "The printed range/precision disagrees with the bus type or conversion index in table 5.20. Decoding follows table 5.20; this parameter is read-only."
            ru["note"] = "Диапазон или точность описания расходится с типом данных либо индексом таблицы 5.20. Декодирование следует таблице 5.20; параметр только для чтения."
        count = ARRAYS.get(code)
        for index in range(count or 1):
            item, translated = copy.deepcopy(p), copy.deepcopy(ru)
            if count:
                item["code"] = f"{code}[{index}]"
                item["array_index"] = index
                item["description"] += f" [{index}]"
                translated["description"] += f" [{index}]"
            if code == "8-43" and index < 2:
                item["read_only"] = True
                item["default"] = str(7 + index)
            parameters.append(item)
            translations[item["code"]] = translated
    by_code = {p["code"]: p for p in parameters}
    for low_code, high_code in (("3-02", "3-03"), ("4-12", "4-14"), ("4-40", "4-41"),
                               ("4-50", "4-51"), ("4-54", "4-55"), ("4-56", "4-57"),
                               ("5-55", "5-56"), ("6-10", "6-11"), ("6-12", "6-13"), ("6-22", "6-23")):
        by_code[low_code]["maximum_from"] = high_code
        by_code[high_code]["minimum_from"] = low_code
    for index in range(5):
        by_code[f"1-56[{index}]"]["maximum_from"] = f"1-56[{index + 1}]"
        by_code[f"1-56[{index + 1}]"]["minimum_from"] = f"1-56[{index}]"
    return parameters, translations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("english", type=Path)
    parser.add_argument("russian", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    parameters, translations = extract(args.english, args.russian)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "translations").mkdir(exist_ok=True)
    (args.output / "parameters.json").write_text(json.dumps(parameters, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "translations/ru.json").write_text(json.dumps({"language": "ru", "parameters": translations}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Extracted {len(parameters)} rows from {len({p['code'].split('[')[0] for p in parameters})} parameters")


if __name__ == "__main__":
    main()
