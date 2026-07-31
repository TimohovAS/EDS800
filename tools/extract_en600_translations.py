"""Extract the Russian EN500/EN600-compatible parameter catalogue.

The ESQ-500/600 08.04.500 Russian manual contains the same current 651-code
function table as the EN500/EN600 V5.0-A13 manual.  Pages 65-120 are parsed
directly so names and option descriptions stay traceable to the source.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pdfplumber


CODE_PATTERN = re.compile(r"F\d{2}\.\d{2}")
SOURCE_URL = (
    "https://www.elcomspb.kz/upload/iblock/b75/"
    "kur8dsapkq4n6pdy81dewj8rnt5nut39.pdf"
)
SOURCE_TITLE = "ESQ-500/600, версия 08.04.500"
DEFAULT_FIRST_PAGE = 65
DEFAULT_LAST_PAGE = 120
LEGACY_SOURCE_URL = (
    "https://sparks.su/upload/doc/p-ch-en-500-en-600/instruction-EN500.pdf"
)
LEGACY_SOURCE_TITLE = "ENC EN500/EN600, русская редакция V2"
LEGACY_FIRST_PAGE = 69
LEGACY_LAST_PAGE = 124

DEFAULT_NOTES = {
    "Base on motor": "Зависит от двигателя",
    "Base on motor type": "Зависит от типа двигателя",
    "Based on motor type": "Зависит от типа двигателя",
    "-": "—",
}

# Some control-panel glyphs have no useful text layer in the PDF.
TEXT_REPLACEMENTS = {
    "Cохранение": "Сохранение",
    "RSETSOEPT": "STOP/RESET",
    " Í ": " × ",
    "ЖК- дисплеем": "ЖК-дисплеем",
    "ПИД- регулятора": "ПИД-регулятора",
    "ПИД- регулирования": "ПИД-регулирования",
    "УВЕЛИЧЕНИЯ/ УМЕНЬШЕНИЯ": "УВЕЛИЧЕНИЯ/УМЕНЬШЕНИЯ",
    "вверх(UP)/вниз( Down)": "ВВЕРХ (UP)/ВНИЗ (DOWN)",
    "многофунк- циональной": "многофункциональной",
    "неправильное работа": "неправильная работа",
    "разгона- торможения": "разгона/торможения",
    "тime-out": "тайм-аут",
}

CURRENT_ROW_OVERRIDES = {
    # The PDF text layer omits the UP/DOWN and SHIFT button glyphs in this row.
    "F00.14": {
        "description": "Управление параметрами",
        "range": (
            "Разряд единиц: возможность изменения параметров. "
            "0: Разрешено изменять все параметры. "
            "1: Разрешено изменять только текущий параметр. "
            "2: Разрешено изменять только текущий параметр, F01.01 и F01.04. "
            "Разряд десятков: сброс до заводских настроек. "
            "0: Никаких действий. "
            "1: Сброс всех параметров, кроме записей ошибок F26. "
            "2: Сброс всех параметров, кроме параметров двигателя F15 "
            "и записей ошибок F26. "
            "3: Сброс расширенных параметров F21~F24. "
            "4: Сброс виртуальных параметров F20. "
            "5: Сброс записей ошибок F26. "
            "Разряд сотен: блокировка кнопок. "
            "0: Все кнопки заблокированы. "
            "1: Доступна только STOP/RESET. "
            "2: Доступны UP, DOWN и STOP/RESET. "
            "3: Доступны RUN и STOP/RESET. "
            "4: Доступны SHIFT и STOP/RESET. "
            "5: Блокировка отключена."
        ),
    },
}

LEGACY_ROW_OVERRIDES = {
    "F02.25": {
        "description": "Время шифрования",
        "range": "0~65535 ч",
        "source": "ru_manual_reconciled",
        "note": (
            "Перевод восстановлен по английской карте V2: "
            "в русском руководстве параметр указан как резерв."
        ),
    },
    "F19.43": {
        "description": "Коэффициент подавления перенапряжения",
        "range": "0.0~100.0%",
        "source": "ru_manual_reconciled",
        "note": (
            "Перевод восстановлен по английской карте V2: "
            "в русском руководстве параметр указан как резерв."
        ),
    },
    "F11.21": {
        "range_append": " 2: Определяется командой пуска.",
        "source": "ru_manual_reconciled",
        "note": "Вариант 2 добавлен по английской карте V2.",
    },
    "F08.18": {
        "range_append": " 27: Команда торможения постоянным током (DB).",
        "source": "ru_manual_reconciled",
        "note": "Вариант 27 добавлен по английской карте V2.",
    },
    "F09.00": {
        "range": (
            "0: Не используется; 1: Работа (RUN); "
            "2: Вращение вперёд; 3: Вращение назад; "
            "4: Торможение постоянным током; 5: Готовность к пуску; "
            "6: Команда остановки; 7: Ток отсутствует; "
            "8: Обнаружен повышенный ток; 9: Достигнут ток 1; "
            "10: Достигнут ток 2; 11: Выходная частота отсутствует; "
            "12: Достигнута частота (FAR); "
            "13: Обнаружен уровень частоты 1 (FDT1); "
            "14: Обнаружен уровень частоты 2 (FDT2); "
            "15: Достигнут верхний предел частоты (FHL); "
            "16: Достигнут нижний предел частоты (FLL); "
            "17: Достигнута частота 1; 18: Достигнута частота 2; "
            "19: Предупреждение о перегрузке (OL); "
            "20: Останов при пониженном напряжении (LU); "
            "21: Останов по внешней ошибке (EXT); 22: Ошибка; "
            "23: Авария; 24: Выполняется простая программа ПЛК; "
            "25: Завершён этап простой программы ПЛК; "
            "26: Завершён цикл простой программы ПЛК."
        ),
        "source": "ru_manual_reconciled",
        "note": (
            "Список ограничен вариантами 0~26 из английской карты V2; "
            "функции более новой русской редакции исключены."
        ),
    },
    "F10.01": {
        "range": (
            "000H~E22H. Разряд единиц — задание частоты: "
            "0: Многоступенчатая частота i (i=1~15); "
            "1: Комбинация основной и дополнительной частот; 2: Резерв. "
            "Разряд десятков — направление: 0: Вперёд; 1: Реверс; "
            "2: По команде пуска. Разряд сотен — выбор времени "
            "разгона/торможения: 0~9 — время 1~10; "
            "A~E — время 11~15."
        ),
        "source": "ru_manual_reconciled",
        "note": (
            "Описание разряда сотен добавлено по английской карте V2 "
            "и текущему руководству."
        ),
    },
}

LEGACY_F12_TRANSLATIONS = {
    "F12.00": (
        "Выбор режима поддержания постоянного давления воды",
        "0: Выключено; 1: Один ПЧ — два насоса средствами ПЧ; "
        "2: Один ПЧ — два насоса с платой расширения; "
        "3: Один ПЧ — три насоса с платой расширения; "
        "4: Один ПЧ — четыре насоса с платой расширения",
    ),
    "F12.01": (
        "Задание постоянного давления",
        "0.000~верхний предел диапазона датчика давления",
    ),
    "F12.02": (
        "Частота перехода в режим сна",
        "0.00 Гц~верхнее ограничение частоты",
    ),
    "F12.03": (
        "Давление выхода из режима сна",
        "0.000~верхний предел диапазона датчика давления",
    ),
    "F12.04": ("Задержка перехода в режим сна", "0.0~6000.0 с"),
    "F12.05": ("Задержка выхода из режима сна", "0.0~6000.0 с"),
    "F12.06": ("Диапазон датчика давления", "0.001~9.999 МПа"),
    "F12.07": (
        "Допустимое отклонение частоты при включении или отключении насоса",
        "0.1~100.0%",
    ),
    "F12.08": (
        "Время определения необходимости переключения насоса",
        "0.2~999.9 с",
    ),
    "F12.09": (
        "Задержка переключения электромагнитного контактора",
        "0.1~10.0 с",
    ),
    "F12.10": (
        "Интервал автоматического чередования насосов",
        "0000~65535 мин",
    ),
    "F12.11": (
        "Выбор режима выхода из сна",
        "0: По значению F12.03; 1: По значению F12.12 × F12.01",
    ),
    "F12.12": ("Коэффициент давления для выхода из сна", "0.01~0.99"),
}


def normalize(value: str | None) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    for source, target in TEXT_REPLACEMENTS.items():
        value = value.replace(source, target)
    value = re.sub(r"\bF\s+(\d{2}\.\d{2})", r"F\1", value)
    return value


def extract_manual_rows(
    manual_path: Path,
    first_page: int,
    last_page: int,
) -> dict[str, dict[str, object]]:
    """Extract code, Russian name and Russian options from the function table."""
    rows: dict[str, dict[str, object]] = {}
    with pdfplumber.open(manual_path) as pdf:
        if first_page < 1 or last_page > len(pdf.pages):
            raise ValueError(
                f"Page range {first_page}-{last_page} is outside "
                f"the {len(pdf.pages)}-page manual"
            )
        for page_number in range(first_page, last_page + 1):
            page = pdf.pages[page_number - 1]
            for table in page.extract_tables():
                for row in table:
                    cells = [normalize(cell) for cell in row]
                    if not cells or not CODE_PATTERN.fullmatch(cells[0]):
                        continue
                    rows.setdefault(
                        cells[0],
                        {
                            "description": cells[1],
                            "range": cells[2] if len(cells) > 2 else "",
                            "source": "ru_manual_table",
                            "manual_pdf_page": page_number,
                        },
                    )
    return rows


def build_catalogue(
    manual_path: Path,
    profile_path: Path,
    first_page: int = DEFAULT_FIRST_PAGE,
    last_page: int = DEFAULT_LAST_PAGE,
    *,
    fallback_rows: dict[str, tuple[str, str]] | None = None,
    row_overrides: dict[str, dict[str, str]] | None = None,
    source_url: str = SOURCE_URL,
    source_title: str = SOURCE_TITLE,
) -> dict[str, object]:
    manual_rows = extract_manual_rows(manual_path, first_page, last_page)
    for code, (description, value_range) in (fallback_rows or {}).items():
        manual_rows.setdefault(
            code,
            {
                "description": description,
                "range": value_range,
                "source": "ru_manual_detail",
            },
        )
    for code, override in (row_overrides or {}).items():
        if code in manual_rows:
            payload = dict(override)
            range_append = payload.pop("range_append", "")
            manual_rows[code].update(payload)
            if range_append:
                manual_rows[code]["range"] += range_append
    parameters = json.loads(profile_path.read_text(encoding="utf-8"))
    translations: dict[str, dict[str, object]] = {}
    missing: list[str] = []

    for parameter in parameters:
        code = parameter["code"]
        if code not in manual_rows:
            missing.append(code)
            continue
        translated = dict(manual_rows[code])
        note = parameter.get("default_note")
        if note:
            translated["default_note"] = DEFAULT_NOTES.get(note, note)
        translations[code] = translated

    if missing:
        raise RuntimeError(
            "Russian function table does not contain: " + ", ".join(missing)
        )

    return {
        "language": "ru",
        "source_manual": source_url,
        "source_manual_title": source_title,
        "source_pages": [first_page, last_page],
        "parameters": translations,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manual", type=Path)
    parser.add_argument("profile", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--revision", choices=("v5", "v2"), default="v5")
    parser.add_argument("--first-page", type=int)
    parser.add_argument("--last-page", type=int)
    args = parser.parse_args()

    legacy = args.revision == "v2"
    first_page = args.first_page or (
        LEGACY_FIRST_PAGE if legacy else DEFAULT_FIRST_PAGE
    )
    last_page = args.last_page or (
        LEGACY_LAST_PAGE if legacy else DEFAULT_LAST_PAGE
    )
    catalogue = build_catalogue(
        args.manual,
        args.profile,
        first_page,
        last_page,
        fallback_rows=LEGACY_F12_TRANSLATIONS if legacy else None,
        row_overrides=(
            LEGACY_ROW_OVERRIDES if legacy else CURRENT_ROW_OVERRIDES
        ),
        source_url=LEGACY_SOURCE_URL if legacy else SOURCE_URL,
        source_title=LEGACY_SOURCE_TITLE if legacy else SOURCE_TITLE,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalogue, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {len(catalogue['parameters'])} Russian translations "
        f"to {args.output}"
    )


if __name__ == "__main__":
    main()
