"""Rebuild NXL ALFIFF20 v3.45 from official AB361177530779en-000301.pdf.

python tools/extract_nxl_parameters.py manual.pdf profiles/vacon_nxl
PDF tables supply IDs, limits, units and decimals. Corrections below are
explicit, not inferred from ENC/FC51. Unspecified motor-dependent limits are
read-only. Repeated menu entries share one physical parameter and list aliases.
"""
from __future__ import annotations
import argparse
from decimal import Decimal
import json
from pathlib import Path
import re

NAMES_RU = """
V1.1|Выходная частота
V1.2|Задание частоты
V1.3|Частота вращения двигателя
V1.4|Ток двигателя
V1.5|Крутящий момент двигателя
V1.6|Мощность двигателя
V1.7|Напряжение двигателя
V1.8|Напряжение звена постоянного тока
V1.9|Температура преобразователя
V1.10|Аналоговый вход 1
V1.11|Аналоговый вход 2
V1.12|Ток аналогового выхода
V1.13|Ток аналогового выхода 1 платы расширения
V1.14|Ток аналогового выхода 2 платы расширения
V1.15|Дискретные входы DIN1, DIN2, DIN3
V1.16|Входы DIE1, DIE2, DIE3 платы расширения
V1.17|Релейный выход RO1
V1.18|Релейные выходы ROE1, ROE2, ROE3
V1.19|Дискретный выход DOE1
V1.20|Задание ПИД-регулятора
V1.21|Обратная связь ПИД-регулятора
V1.22|Ошибка ПИД-регулятора
V1.23|Выход ПИД-регулятора
V1.24|Выходы чередования 1, 2, 3
V1.25|Режим работы
V1.26|Тепловая нагрузка двигателя
P2.1.1|Минимальная частота
P2.1.2|Максимальная частота
P2.1.3|Время разгона 1
P2.1.4|Время торможения 1
P2.1.5|Ограничение тока
P2.1.6|Номинальное напряжение двигателя
P2.1.7|Номинальная частота двигателя
P2.1.8|Номинальная частота вращения двигателя
P2.1.9|Номинальный ток двигателя
P2.1.10|Коэффициент мощности двигателя cos φ
P2.1.11|Способ пуска
P2.1.12|Способ останова
P2.1.13|Оптимизация U/f
P2.1.14|Источник задания при управлении с клемм
P2.1.15|Диапазон сигнала AI2
P2.1.16|Функция аналогового выхода
P2.1.17|Функция входа DIN2
P2.1.18|Функция входа DIN3
P2.1.19|Предустановленная скорость 1
P2.1.20|Предустановленная скорость 2
P2.1.21|Автоматический перезапуск
P2.1.22|Скрытие параметров
P2.2.1|Функция DIE1 платы расширения
P2.2.2|Функция DIE2 платы расширения
P2.2.3|Функция DIE3 платы расширения
P2.2.4|Функция DIN4 (AI1)
P2.2.5|Выбор сигнала AI1
P2.2.6|Диапазон сигнала AI1
P2.2.7|Нижняя точка масштабирования AI1
P2.2.8|Верхняя точка масштабирования AI1
P2.2.9|Инверсия AI1
P2.2.10|Время фильтра AI1
P2.2.11|Выбор сигнала AI2
P2.2.12|Диапазон сигнала AI2
P2.2.13|Нижняя точка масштабирования AI2
P2.2.14|Верхняя точка масштабирования AI2
P2.2.15|Инверсия AI2
P2.2.16|Время фильтра AI2
P2.2.17|Сброс памяти задания мотор-потенциометра
P2.2.18|Нижний предел масштабирования задания
P2.2.19|Верхний предел масштабирования задания
P2.2.20|Источник задания при управлении с панели
P2.2.21|Источник задания при управлении по шине
P2.3.1|Функция релейного выхода 1
P2.3.2|Функция реле 1 платы расширения
P2.3.3|Функция реле 2 платы расширения
P2.3.4|Функция дискретного выхода 1 платы расширения
P2.3.5|Функция аналогового выхода
P2.3.6|Время фильтра аналогового выхода
P2.3.7|Инверсия аналогового выхода
P2.3.8|Минимум аналогового выхода
P2.3.9|Масштаб аналогового выхода
P2.3.10|Функция аналогового выхода 1 платы расширения
P2.3.11|Функция аналогового выхода 2 платы расширения
P2.3.12|Контроль предела выходной частоты 1
P2.3.13|Контролируемое значение выходной частоты 1
P2.3.14|Контроль аналогового входа
P2.3.15|Порог отключения контроля AI
P2.3.16|Порог включения контроля AI
P2.3.17|Задержка включения реле 1
P2.3.18|Задержка отключения реле 1
P2.4.1|Форма кривой разгона и торможения 1
P2.4.2|Тормозной прерыватель
P2.4.3|Ток торможения постоянным током
P2.4.4|Время торможения постоянным током при останове
P2.4.5|Частота начала торможения постоянным током
P2.4.6|Время торможения постоянным током при пуске
P2.4.7|Торможение потоком
P2.4.8|Ток торможения потоком
P2.5.1|Нижняя граница запрещённой частоты 1
P2.5.2|Верхняя граница запрещённой частоты 1
P2.5.3|Множитель времени разгона и торможения в запрещённой зоне
P2.6.1|Режим управления двигателем
P2.6.2|Характеристика U/f
P2.6.3|Частота ослабления поля
P2.6.4|Напряжение в точке ослабления поля
P2.6.5|Частота средней точки кривой U/f
P2.6.6|Напряжение средней точки кривой U/f
P2.6.7|Выходное напряжение при нулевой частоте
P2.6.8|Частота коммутации
P2.6.9|Регулятор перенапряжения
P2.6.10|Регулятор пониженного напряжения
P2.6.11|Идентификация двигателя
P2.7.1|Реакция на потерю задания 4 мА
P2.7.2|Реакция на внешнюю ошибку
P2.7.3|Реакция на пониженное напряжение
P2.7.4|Контроль выходных фаз
P2.7.5|Защита от замыкания на землю
P2.7.6|Тепловая защита двигателя
P2.7.7|Поправка на температуру окружающей среды
P2.7.8|Охлаждение двигателя при нулевой скорости
P2.7.9|Тепловая постоянная времени двигателя
P2.7.10|Рабочий цикл двигателя
P2.7.11|Защита от заклинивания
P2.7.12|Предел тока при заклинивании
P2.7.13|Предельное время заклинивания
P2.7.14|Предел частоты при заклинивании
P2.7.15|Защита от недогрузки
P2.7.16|Порог недогрузки при номинальной частоте
P2.7.17|Порог недогрузки при нулевой частоте
P2.7.18|Задержка защиты от недогрузки
P2.7.19|Реакция на ошибку термистора
P2.7.20|Реакция на ошибку полевой шины
P2.7.21|Реакция на ошибку слота
P2.7.22|Контроль обратной связи
P2.7.23|Порог контроля обратной связи
P2.7.24|Задержка контроля обратной связи
P2.8.1|Ожидание перед повторным пуском
P2.8.2|Время попыток повторного пуска
P2.8.3|Способ автоматического повторного пуска
P2.9.1|Включение ПИД-регулятора
P2.9.2|Источник задания ПИД-регулятора
P2.9.3|Источник обратной связи
P2.9.4|Пропорциональный коэффициент ПИД
P2.9.5|Время интегрирования ПИД
P2.9.6|Время дифференцирования ПИД
P2.9.7|Нижняя точка масштаба обратной связи 1
P2.9.8|Верхняя точка масштаба обратной связи 1
P2.9.9|Инверсия ошибки ПИД
P2.9.10|Частота перехода в спящий режим
P2.9.11|Задержка перехода в спящий режим
P2.9.12|Уровень выхода из спящего режима
P2.9.13|Условие выхода из спящего режима
P2.10.1|Количество вспомогательных приводов
P2.10.2|Задержка пуска вспомогательных приводов
P2.10.3|Задержка останова вспомогательных приводов
P2.10.4|Чередование приводов
P2.10.5|Интервал чередования приводов
P2.10.6|Максимум вспомогательных приводов при чередовании
P2.10.7|Предел частоты для чередования
P2.10.8|Частота пуска вспомогательного привода 1
P2.10.9|Частота останова вспомогательного привода 1
P3.1|Источник управления
P3.3|Направление вращения с панели
R3.4|Действие кнопки STOP
"""
RU_NAMES = dict(line.split("|", 1) for line in NAMES_RU.strip().splitlines())
CODE = re.compile(r"^[PVR]\d+(?:\.\d+)+$")


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip().replace("–", "-").replace("−", "-")


def number(text):
    value = clean(text).replace(" ", "").replace(",", ".")
    return Decimal(value) if re.fullmatch(r"-?\d+(?:\.\d+)?", value) else None


def reference(text):
    match = re.search(r"(?:P\s*|[Pp]ar\.\s*)?(2\.\d+\.\d+)", clean(text))
    return "P" + match[1] if match else None


def extract(path):
    import pdfplumber
    rows = {}
    stopped_all = set()
    with pdfplumber.open(path) as pdf:
        for page_index in range(4, 16):
            page = pdf.pages[page_index]
            stopped_codes = set()
            cyan = [rect for rect in page.rects if rect.get("non_stroking_color") == (0.0, 1.0, 1.0)]
            for word in page.extract_words():
                if CODE.fullmatch(word["text"]) and any(
                    rect["x0"] <= word["x0"] and rect["x1"] >= word["x1"] and
                    rect["top"] <= word["top"] and rect["bottom"] >= word["bottom"] for rect in cyan
                ):
                    stopped_codes.add(word["text"])
            stopped_all.update(stopped_codes)
            for table in page.extract_tables():
                for row in table:
                    if not row[0] or not CODE.fullmatch(row[0]):
                        continue
                    cells = [cell for cell in row if cell is not None]
                    if cells[0].startswith("V"):
                        code, name, unit, ident, note = cells
                        rows[code] = dict(name=clean(name), unit=unit, ident=int(ident), note=clean(note),
                                          page=page_index + 1, monitor=True)
                    else:
                        cells += [""] * (9 - len(cells))
                        code, name, low, high, unit, default, _custom, ident, note = cells
                        if not ident.strip():
                            continue  # Keypad-only R3.2/R3.5/R3.6: no published ID.
                        rows[code] = dict(name=clean(name), low=low, high=high, unit=unit,
                                          default=default, ident=int(ident), note=clean(note),
                                          raw_note=note, page=page_index + 1, monitor=False,
                                          stopped=code in stopped_codes)
    # Their vertically merged cells cannot be recovered as ordinary rows.
    for code, ident, default in (("P2.2.5", 377, "10"), ("P2.2.11", 388, "11")):
        rows[code] = dict(name=f"AI{1 if code == 'P2.2.5' else 2} signal selection", low="10", high="21",
                          unit="", default=default, ident=ident, page=8, monitor=False, stopped=code in stopped_all,
                          note="10=AI1; 11=AI2; 20=Expander AI1; 21=Expander AI2", raw_note="")
    assert len(rows) == 161, f"Unexpected number of menu entries: {len(rows)}"
    return rows


RU_OPTION_LINES = """
P2.1.11|Разгон по рампе|Подхват вращающегося двигателя|Условный подхват
P2.1.12|Останов выбегом|Останов по рампе
P2.1.13|Не используется|Автоматическая компенсация момента
P2.1.14|AI1|AI2|Задание с панели|Задание по шине|Мотор-потенциометр|Выбор AI1/AI2
P2.1.16|Не используется|Выходная частота|Задание частоты|Скорость двигателя|Выходной ток|Момент двигателя|Мощность двигателя|Напряжение двигателя|Напряжение звена DC|Задание ПИД|Обратная связь ПИД|Ошибка ПИД|Выход ПИД
P2.1.17|Не используется|Пуск назад (DIN1 — вперёд)|Реверс (DIN1 — пуск)|Импульс останова (DIN1 — импульс пуска)|Внешняя ошибка, замыкание|Внешняя ошибка, размыкание|Разрешение работы|Предустановленная скорость 2|Увеличение задания мотор-потенциометра|Отключение ПИД|Блокировка 1
P2.1.18|Не используется|Реверс|Внешняя ошибка, замыкание|Внешняя ошибка, размыкание|Сброс ошибки|Разрешение работы|Предустановленная скорость 1|Предустановленная скорость 2|Торможение постоянным током|Увеличение задания мотор-потенциометра|Уменьшение задания мотор-потенциометра|Отключение ПИД|Выбор задания ПИД 2 с панели|Блокировка 2|Термисторный вход|Принудительное управление с клемм|Принудительное управление по шине|Выбор AI1/AI2
P2.1.21|Не используется|Используется
P2.1.22|Все параметры и меню видимы|Только P2.1 и меню M1–H5
P2.2.1|Не используется|Реверс|Внешняя ошибка, замыкание|Внешняя ошибка, размыкание|Сброс ошибки|Разрешение работы|Предустановленная скорость 1|Предустановленная скорость 2|Торможение постоянным током|Увеличение задания мотор-потенциометра|Уменьшение задания мотор-потенциометра|Отключение ПИД|Выбор задания ПИД 2 с панели|Блокировка 1
P2.2.9|Без инверсии|Инверсия
P2.2.17|Не сбрасывать|Сброс при останове или отключении питания|Сброс при отключении питания
P2.2.20|AI1|AI2|Задание с панели|Задание по шине|Мотор-потенциометр|ПИД-регулятор
P2.3.1|Не используется|Готов|Работа|Ошибка|Ошибка инверсная|Предупреждение о перегреве ЧП|Внешняя ошибка или предупреждение|Ошибка или предупреждение задания|Предупреждение|Реверс|Предустановленная скорость|Задание скорости достигнуто|Активен регулятор двигателя|Контроль предела частоты 1|Управление с клемм|Ошибка или предупреждение термистора|Контроль обратной связи|Чередование 1|Чередование 2|Чередование 3|Контроль AI
P2.3.8|0 мА|4 мА
P2.3.12|Без контроля|Контроль нижнего предела|Контроль верхнего предела
P2.3.14|Не используется|AI1|AI2
P2.4.7|Отключено|Включено
P2.6.1|Управление частотой|Управление скоростью
P2.6.2|Линейная|Квадратичная|Программируемая|Линейная с оптимизацией потока
P2.6.9|Не используется|Используется
P2.6.11|Нет действия|Идентификация без вращения
P2.7.1|Нет реакции|Предупреждение|Ошибка, останов по P2.1.12|Ошибка, останов выбегом
P2.7.22|Нет реакции|Предупреждение ниже порога|Предупреждение выше порога|Ошибка ниже порога|Ошибка выше порога
P2.8.3|Разгон по рампе|Подхват|Согласно P2.4.6
P2.9.1|Отключено|ПИД-регулятор|Управление насосами и вентиляторами (P2.10)
P2.9.2|AI1|AI2|Задание ПИД 1 с панели|Задание по шине (ProcessDataIN1)
P2.9.3|AI1|AI2|Шина (ProcessDataIN2)|Момент двигателя|Скорость двигателя|Ток двигателя|Мощность двигателя|AI1 минус AI2
P2.9.9|Без инверсии|Инверсия
P2.9.13|Ниже порога P2.9.12|Выше порога P2.9.12|Ниже задания ПИД|Выше задания ПИД
P2.10.4|Не используется|Чередование вспомогательных насосов|Чередование ЧП и вспомогательных насосов|Чередование и блокировки вспомогательных насосов|Чередование и блокировки ЧП и вспомогательных насосов
"""
RU_OPTIONS = {parts[0]: dict(enumerate(parts[1:])) for line in RU_OPTION_LINES.strip().splitlines()
              if (parts := line.split("|"))}
RU_OPTIONS.update({
    "P2.1.15": {1: "0–20 мА", 2: "4–20 мА", 3: "0–10 В", 4: "2–10 В"},
    "P2.2.5": {10: "AI1", 11: "AI2", 20: "AI1 платы расширения", 21: "AI2 платы расширения"},
    "P2.4.2": {0: "Не используется", 1: "Работа только в RUN", 3: "Работа в RUN и STOP"},
    "P3.1": {1: "Клеммы ввода-вывода", 2: "Панель", 3: "Полевая шина"},
    "P3.3": {0: "Вперёд", 1: "Назад"},
    "R3.4": {0: "Ограниченное действие кнопки STOP", 1: "STOP всегда разрешён"},
})
BASE_OPTIONS = {
    "P2.2.2": "P2.2.1", "P2.2.3": "P2.2.1", "P2.2.4": "P2.2.1",
    "P2.2.11": "P2.2.5", "P2.2.15": "P2.2.9", "P2.2.21": "P2.2.20",
    "P2.3.2": "P2.3.1", "P2.3.3": "P2.3.1", "P2.3.4": "P2.3.1",
    "P2.3.7": "P2.2.9", "P2.3.10": "P2.1.16", "P2.3.11": "P2.1.16",
    "P2.6.10": "P2.6.9",
    **{f"P2.7.{n}": "P2.7.1" for n in (2, 3, 4, 5, 6, 11, 15, 19, 20, 21)},
}
for code, base in BASE_OPTIONS.items():
    RU_OPTIONS[code] = dict(RU_OPTIONS[base])
for code, interlock in (("P2.2.2", 2), ("P2.2.3", 3), ("P2.2.4", 3)):
    RU_OPTIONS[code][13] = f"Блокировка {interlock}"
RU_OPTIONS["P2.2.6"] = {0: "Дискретный вход DIN4", **RU_OPTIONS["P2.1.15"]}

NOTES_RU = {
    "P2.1.2": "Если максимальная частота выше синхронной скорости двигателя, проверьте допустимость для двигателя и механизма.",
    "P2.1.6": "Значение 400 В относится к исполнению NXL5. Сверьте данные шильдика двигателя.",
    "P2.1.7": "Сверьте номинальную частоту со шильдиком двигателя.",
    "P2.1.8": "Заводское значение относится к четырёхполюсному двигателю номинального для ЧП размера.",
    "P2.1.9": "Для NXL 0007 5 в таблице 4-2 указаны IL=7.6 А и IH=5.6 А. Пределы и точность тока требуют проверки на самом устройстве.",
    "P2.2.5": "Значения — адреса входов, а не непрерывный диапазон: 10, 11, 20, 21.",
    "P2.2.6": "В таблице минимум 1, но вариант 0 (DIN4) явно описан. Для MF4 доступны также токовые диапазоны; согласуйте настройку с перемычками и режимом AI1.",
    "P2.2.18": "Не влияет на задание по шине: оно масштабируется между P2.1.1 и P2.1.2.",
    "P2.2.19": "Не влияет на задание по шине: оно масштабируется между P2.1.1 и P2.1.2.",
    "P2.4.2": "Значение 2 не описано; разрешены только 0, 1 и 3. Не включайте торможение без проверки тормозного резистора.",
    "P2.5.3": "Множитель времени разгона/торможения при прохождении запрещённой зоны.",
    "P2.6.6": "Дополнительный предел: P2.6.4. Профиль сохраняет также табличный максимум 100%.",
    "P2.6.8": "Заводское значение зависит от мощности ЧП; в таблице приведено 6.0 кГц.",
    "P2.6.11": "Команда идентификации. Записывается только после явного изменения ячейки; не воспроизводится из считанных значений.",
    "P2.9.1": "Табличный максимум 1 противоречит варианту 2. Подробное описание на стр. 46 подтверждает 2 — управление насосами и вентиляторами.",
    "P2.10.5": "При значении 0.0 включается тестовый интервал 40 секунд.",
    "P3.1": "Использована таблица приложения: 1 — клеммы, 2 — панель, 3 — шина. В разделе 7.4.7.4 руководства пользователя ошибочно указано 2 для шины. Меняйте источник управления только явно и на остановленном механизме.",
}


def options(raw):
    return {int(match[1]): clean(match[2]) for match in re.finditer(
        r"(?:^|\n)(\d+)\s*=\s*(.*?)(?=\n\d+\s*=|\Z)", raw or "", re.S)}


def group_of(code):
    return "K3" if code.startswith(("P3.", "R3.")) else code.rsplit(".", 1)[0]


def build(path):
    records = extract(path)
    records["P2.2.6"]["low"] = "0"
    records["P2.9.1"]["high"] = "2"
    records["P2.1.6"]["default"] = "400"
    en_options = {code: options(rec.get("raw_note")) for code, rec in records.items()}
    en_options["P2.2.5"] = {10: "AI1", 11: "AI2", 20: "Expander AI1", 21: "Expander AI2"}
    for code, base in BASE_OPTIONS.items():
        en_options[code] = dict(en_options[base])
    for code, interlock in (("P2.2.2", 2), ("P2.2.3", 3), ("P2.2.4", 3)):
        en_options[code][13] = f"Interlock {interlock}"
    en_options["P2.9.9"] = {0: "No inversion", 1: "Inverted"}

    def resolve(code, side, seen=()):
        if code in seen:
            raise ValueError(f"Cyclic manual bound: {code}")
        value = number(records[code][side])
        ref = reference(records[code][side])
        return resolve(ref, side, (*seen, code)) if ref else value

    parameters, translations, by_id = [], {}, {}
    for code, rec in sorted(records.items(), key=lambda pair: (pair[1]["page"], [int(n) for n in re.findall(r"\d+", pair[0])])):
        ident = rec["ident"]
        if ident in by_id:
            canonical = by_id[ident]
            canonical.setdefault("aliases", []).append(code)
            canonical["range"] += f"; also keypad {code}"
            translations[canonical["code"]]["range"] += f"; также в меню {code}"
            continue
        monitor = rec["monitor"]
        low, high = (Decimal(0), Decimal(65535)) if monitor else (resolve(code, "low"), resolve(code, "high"))
        protected = not monitor and (low is None or high is None)
        if monitor:
            scale = 10 if code == "V1.26" else 1
        elif protected:
            scale = 1
            low, high = Decimal(0), Decimal(65535)
        else:
            candidates = [number(rec[side]) for side in ("low", "high")]
            decimals = [max(0, -value.as_tuple().exponent) for value in candidates if value is not None]
            scale = 10 ** max(decimals or [max(0, -(number(rec["default"]) or Decimal(0)).as_tuple().exponent)])
        signed = low < 0
        if monitor and scale == 10:
            high = Decimal("6553.5")
        default = None if monitor else number(rec["default"])
        if code == "P2.6.8":
            default = None
        unit = rec["unit"].replace("º", "°").replace("Times", "×")
        if monitor and code != "V1.26":
            unit = ""
        if protected:
            unit = ""
        raw_display = protected or monitor and code != "V1.26"
        p = dict(code=code, description=rec["name"] + (" (raw)" if raw_display else ""),
                 minimum=float(low), maximum=float(high), unit=unit, parameter_id=ident,
                 address=ident - 1, group=group_of(code), default="" if default is None else f"{default:.{len(str(scale))-1}f}",
                 scale=scale, encoding="numeric", read_only=monitor or protected,
                 data_bits=16, signed=signed, manual_pdf_page=rec["page"],
                 change_while_running=not rec.get("stopped", False))
        ru = {"description": RU_NAMES[code] + (" (сырое значение)" if raw_display else "")}
        p["range"] = "Raw register value; source does not specify bus scaling" if monitor else f"{clean(rec['low'])} ~ {clean(rec['high'])} {unit}".strip()
        ru_unit = {"Hz": "Гц", "kHz": "кГц", "V": "В", "A": "А", "mA": "мА", "s": "с",
                   "rpm": "об/мин", "min": "мин", "h": "ч"}.get(unit, unit)
        ru["range"] = ("Сырое значение регистра; масштаб по шине в таблице не указан" if monitor else
                       f"{low:g} ~ {high:g} {ru_unit}")
        opts = en_options.get(code, {}) if not monitor and scale == 1 else {}
        if code in RU_OPTIONS:
            if set(opts) != set(RU_OPTIONS[code]):
                raise ValueError(f"Missing English options {code}: {set(opts)} vs {set(RU_OPTIONS[code])}")
            values = sorted(v for v in opts if low <= v <= high)
            p["allowed_values"] = values
            p["range"] = "; ".join(f"{v}: {opts[v]}" for v in values)
            ru["range"] = "; ".join(f"{v}: {RU_OPTIONS[code][v]}" for v in values)
        if rec.get("note"):
            p["note"] = rec["note"]
        if code in NOTES_RU:
            ru["note"] = NOTES_RU[code]
        if protected:
            p["range"] = "Raw register 0–65535; motor/drive-dependent engineering limits are not verified"
            ru["range"] = "Сырой регистр 0–65535; физические пределы зависят от двигателя/привода и не подтверждены"
            p["note"] = "Read-only safety restriction: motor/drive-dependent limits and current precision are not verified for this MF4. The value is a RAW register, not amperes. " + rec["note"]
            ru["note"] = "Ограничение безопасности профиля: только чтение. Пределы записи и точность тока не подтверждены для этого MF4. Значение показано как СЫРОЙ регистр, не в амперах. Это не означает, что параметр неизменяем в самом ЧП."
        if default is None and not monitor:
            p["default_note"] = "Depends on motor / drive"
            ru["default_note"] = "Зависит от двигателя / привода"
        if monitor:
            p["note"] = "Read-only monitoring. Use FB group for documented engineering-unit process data. " + rec["note"]
            ru["note"] = "Только чтение. Текущие значения с подтверждёнными единицами и масштабами доступны в группе FB."
            if code == "V1.26":
                p["range"] = "Motor thermal load: 1000 corresponds to 100.0%"
                ru["range"] = "Тепловая нагрузка двигателя: значение 1000 соответствует 100.0%"
                p["note"] = "Scale 0.1% explicitly stated in monitoring table 1-3."
                ru["note"] = "Шаг 0.1% прямо указан в таблице мониторинга 1-3."
        if not monitor and not protected:
            for side, field in (("low", "minimum_from"), ("high", "maximum_from")):
                if ref := reference(rec[side]):
                    p[field] = ref
            if code == "P2.6.6":
                p["maximum_from"] = "P2.6.4"
        if code in ("P2.6.11", "P3.1", "P3.3", "R3.4", "P2.1.21"):
            p["write_only_if_edited"] = True
        parameters.append(p)
        translations[code] = ru
        by_id[ident] = p
    add_process_data(parameters, translations)
    return parameters, translations


def add_process_data(parameters, translations):
    # User manual DPD01446, printed pp.79–80. All process inputs 2001–2011
    # (including RUN, direction, reset and speed reference) are deliberately
    # absent: parameter reads/backups must not become motor commands.
    rows = [
        (2101, "FB status word", "Слово состояния по шине", 1, "", False),
        (2102, "FB general status word (raw)", "Общее слово состояния (сырое)", 1, "", False),
        (2103, "FB actual speed", "Фактическая скорость по шине", 100, "%", True),
        (2104, "Output frequency", "Выходная частота", 100, "Hz", True),
        (2105, "Motor speed", "Частота вращения двигателя", 1, "rpm", True),
        (2106, "Motor current", "Ток двигателя", 10, "A", False),
        (2107, "Motor torque", "Крутящий момент двигателя", 10, "%", True),
        (2108, "Motor power", "Мощность двигателя", 10, "%", True),
        (2109, "Motor voltage", "Напряжение двигателя", 10, "V", False),
        (2110, "DC-link voltage", "Напряжение звена постоянного тока", 1, "V", False),
        (2111, "Active fault code", "Код текущей аварии", 1, "", False),
    ]
    for ident, name, ru_name, scale, unit, signed in rows:
        code = f"FB.{ident}"
        p = dict(code=code, description=name, parameter_id=ident, address=ident-1,
                 group="FB", minimum=(-32768 if signed else 0)/scale,
                 maximum=(32767 if signed else 65535)/scale, unit=unit, scale=scale,
                 encoding="numeric", default="", read_only=True, data_bits=16,
                 signed=signed, manual_pdf_page=80,
                 range="Read-only process data; built-in Modbus, user manual pp.79–80")
        parameters.append(p)
        translations[code] = {"description": ru_name,
                              "range": "Только чтение; встроенный Modbus, стр. 79–80 руководства пользователя"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manual", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    parameters, translations = build(args.manual)
    assert len(parameters) == 170
    assert len({p["parameter_id"] for p in parameters}) == len(parameters)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "translations").mkdir(exist_ok=True)
    for target, payload in ((args.output / "parameters.json", parameters),
                            (args.output / "translations/ru.json", {"parameters": translations})):
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"NXL: {len(parameters)} unique IDs, {sum(not p['read_only'] for p in parameters)} writable")


if __name__ == "__main__":
    main()
