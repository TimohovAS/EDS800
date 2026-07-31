"""User interface translations for the ENC inverter parameter editor.

The application chrome is translated into all supported languages. EN600
parameter descriptions and option lists also have revision-specific Russian
catalogues that remain traceable to the manufacturer's manuals.

Values are either a single string or a tuple of plural forms.  Plural forms are
ordered one / few / many; English only uses the first two.
"""

from __future__ import annotations

import os
import warnings

LANGUAGES = (
    ("en", "EN", "English"),
    ("ru", "RU", "Русский"),
    ("sr", "SR", "Srpski"),
)

DEFAULT_LANGUAGE = "en"

# Engineering units as printed in the manuals, per language.  Languages that
# keep the international symbols (English, Serbian) need no table.
UNITS: dict[str, dict[str, str]] = {
    "ru": {
        "A": "А",
        "h": "ч",
        "Hour": "ч",
        "Hz": "Гц",
        "Hz/s": "Гц/с",
        "K": "К",
        "kHz": "кГц",
        "KHz": "кГц",
        "kW": "кВт",
        "KW": "кВт",
        "kwh": "кВт·ч",
        "m": "м",
        "cm": "см",
        "mH": "мГн",
        "min": "мин",
        "Min": "мин",
        "MPa": "МПа",
        "Mpa": "МПа",
        "ms": "мс",
        "r/min": "об/мин",
        "s": "с",
        "s/min": "с/мин",
        "V": "В",
        "°C": "°С",
        "℃": "°С",
        "Ω": "Ом",
        "-": "—",
    },
}


TRANSLATIONS: dict[str, dict[str, str | tuple[str, ...]]] = {
    "en": {
        # --- shell -----------------------------------------------------
        "app.name": "ENC Inverter Parameter Editor",
        "header.subtitle": "{model}  ·  {parameters}  ·  {groups}  ·  v{version}",
        "count.parameters": ("{n} parameter", "{n} parameters"),
        "count.groups": ("{n} group", "{n} groups"),
        # --- actions ---------------------------------------------------
        "action.manual": "Manual",
        "action.theme_dark": "Dark theme",
        "action.theme_light": "Light theme",
        "action.test_link": "Test link",
        "action.read_group": "↓ Read group",
        "action.write_edited": "↑ Write edited",
        "action.read_all": "↓ Read all",
        "action.write_all": "↑ Write all",
        "action.load": "Load…",
        "action.save": "Save…",
        "action.cancel": "Cancel",
        # --- sidebar ---------------------------------------------------
        "sidebar.connection": "CONNECTION",
        "sidebar.model": "Inverter model",
        "sidebar.port": "Serial port",
        "sidebar.device_id": "Modbus ID",
        "sidebar.groups": "PARAMETER GROUPS",
        "sidebar.files": "SETTINGS FILE",
        # --- table -----------------------------------------------------
        "table.search": "Search: code or description",
        "column.code": "Code",
        "column.parameter": "Parameter",
        "column.value": "Value",
        "column.unit": "Unit",
        "column.default": "Default",
        "column.range": "Range / options",
        "group.all": "All parameters",
        "filter.all": "All",
        "filter.writable": "Writable",
        "filter.readonly": "Read-only",
        "filter.edited": "Edited",
        "filter.errors": "Errors",
        # --- details ---------------------------------------------------
        "details.none": "No parameter selected",
        "details.writable": "Writable",
        "details.readonly": "Read-only",
        "details.group": "group {group}",
        "details.running_yes": "changeable while running",
        "details.running_no": "stop before changing",
        "details.manual_page": "manual p.{page}",
        "details.default": "Default {value}",
        "details.translation_note": "Source note: {note}",
        # --- status bar ------------------------------------------------
        "status.ready": "Ready",
        "status.counts_shown": "{shown} of {total} shown",
        "status.counts_edited": "{n} edited",
        "status.counts_errors": ("{n} error", "{n} errors"),
        "status.ports_available": ("{n} serial port available", "{n} serial ports available"),
        "status.no_ports": "No serial ports found",
        "status.busy": "Another operation is still running",
        "status.wait_operation": "Wait for the current operation to finish",
        "status.manual_opened": "Opened the manual in your browser",
        "status.no_manual": "No manual link for this model",
        "status.profile_loaded": "Loaded parameter map for {model}",
        "status.profile_missing": "Saved model {profile} is no longer available; using {model}",
        "status.revision_detected": "Detected {model} (F02.26 = {value})",
        "status.progress": "{title} — {done}/{total}",
        "status.working": "{title}…",
        "status.cancelling": "Cancelling…",
        "status.cancelled": "{title} cancelled",
        "status.failed": "{title} failed: {error}",
        "status.link_ok": "Link OK — {code} = {value}",
        "status.read_result": "Read {ok} of {total} parameters",
        "status.write_result": ("Wrote {n} parameter", "Wrote {n} parameters"),
        "status.write_partial": "Wrote {written}, {failed} failed",
        "status.saved": "Saved {n} settings to {file}",
        "status.save_failed": "Could not save file: {error}",
        "status.loaded": "Loaded {n} settings from {file}{note}",
        "status.loaded_note": (", {n} unknown code ignored", ", {n} unknown codes ignored"),
        "status.load_failed": "Could not load file: {error}",
        "link.idle": "Idle",
        "link.no_port": "no port",
        "link.summary": "{port}  ·  {link}  ·  ID {device_id}",
        # --- background tasks ------------------------------------------
        "task.detect": "Detecting inverter revision",
        "task.test_link": "Testing link",
        "task.read_group": "Reading {group}",
        "task.read_all": "Reading all {n} parameters",
        "task.write": "Writing {scope}",
        "task.read_for_save": "Reading settings to save",
        "scope.group": "group {group}",
        "scope.all_groups": "all groups",
        "scope.all_parameters": "all parameters",
        # --- dialogs ---------------------------------------------------
        "dialog.serial_ports.title": "Serial ports",
        "dialog.serial_ports.body": "No COM ports found",
        "dialog.select_port.title": "Serial port",
        "dialog.select_port.body": "Select a COM port first",
        "dialog.device_id.title": "Modbus ID",
        "dialog.device_id.body": "Modbus ID must be between 1 and 247",
        "dialog.connection.title": "Connection",
        "dialog.nothing_to_read.title": "Nothing to read",
        "dialog.nothing_to_read.body": "This group has no parameters",
        "dialog.invalid_value.title": "Invalid value",
        "dialog.invalid_value.body": "{code}: {problem}",
        "dialog.invalid_values.title": "Invalid values",
        "dialog.invalid_values.none": "Nothing can be written:\n\n{problems}",
        "dialog.invalid_values.skip": (
            "{n} value cannot be written:\n\n{problems}\n\n"
            "Skip it and write the remaining {rest}?",
            "{n} values cannot be written:\n\n{problems}\n\n"
            "Skip them and write the remaining {rest}?",
        ),
        "dialog.more": "\n…and {n} more",
        "dialog.nothing_to_write.title": "Nothing to write",
        "dialog.nothing_to_write.body": (
            "No values to write yet. Read the inverter or load a settings file first."
        ),
        "dialog.confirm_write.title": "Confirm write",
        "dialog.confirm_write.body": (
            "Write {count} of {scope} to {model}\n"
            "on {port} (Modbus ID {device_id})?\n\n"
            "{edited} edited in the table."
        ),
        "dialog.confirm_write.count": ("{n} parameter", "{n} parameters"),
        "dialog.confirm_write.edited": ("{n} value", "{n} values"),
        "dialog.write_errors.title": "Write errors",
        "dialog.write_errors.body": ("{n} parameter failed:\n\n{details}", "{n} parameters failed:\n\n{details}"),
        "dialog.save.title": "Save settings to file",
        "dialog.load.title": "Load settings from file",
        "dialog.json_files": "JSON files",
        "dialog.all_files": "All files",
        "dialog.save_failed.title": "Save failed",
        "dialog.load_failed.title": "Load failed",
        "dialog.closing.title": "Operation running",
        "dialog.closing.body": "A Modbus operation is still running. Close anyway?",
        # --- validation ------------------------------------------------
        "valid.read_only": "read-only parameter",
        "valid.number": "must be a number",
        "valid.between": "must be between {minimum} and {maximum}{unit}",
        "valid.bcd_digits": "must contain exactly {digits} digits from {chars}",
        "valid.hex_digits": "must contain exactly {digits} hexadecimal digits from {chars}",
        "valid.function_code": "must be a function code such as 25.00",
        "valid.function_group": "function group must be between 00 and {maximum}",
        "valid.function_number": "function number must be between 00 and 99",
        "valid.digit_limits": "digits must not exceed {pattern} (one setting per digit)",
        "valid.maximum_from": "must not exceed {code}, which is {limit}{unit}",
        "valid.minimum_from": "must not be below {code}, which is {limit}{unit}",
        "valid.register_range": "does not fit one 16-bit register (0-{maximum})",
        "valid.problem": "{code}  —  {problem} (got '{value}')",
        "valid.encode_problem": "{code}  —  {problem}",
        # --- errors raised while loading a file ------------------------
        "error.open_port": "Could not open {port}",
        "error.unknown_profile": "Unknown inverter profile in file: {profile}",
        "error.not_a_settings_file": "The file does not contain an inverter settings block",
        "error.unsupported_version": "Unsupported settings file version: {version}",
        "error.raw_out_of_range": "Raw value for {code} is outside 0..65535",
        "error.invalid_value": "Invalid value: {value}",
        "error.invalid_function_code": "Invalid function code: {value}",
    },
    "ru": {
        "header.subtitle": "{model}  ·  {parameters}  ·  {groups}  ·  v{version}",
        "count.parameters": ("{n} параметр", "{n} параметра", "{n} параметров"),
        "count.groups": ("{n} группа", "{n} группы", "{n} групп"),
        "action.manual": "Руководство",
        "action.theme_dark": "Тёмная тема",
        "action.theme_light": "Светлая тема",
        "action.test_link": "Проверить связь",
        "action.read_group": "↓ Читать группу",
        "action.write_edited": "↑ Записать правки",
        "action.read_all": "↓ Читать всё",
        "action.write_all": "↑ Записать всё",
        "action.load": "Загрузить…",
        "action.save": "Сохранить…",
        "action.cancel": "Отмена",
        "sidebar.connection": "ПОДКЛЮЧЕНИЕ",
        "sidebar.model": "Модель инвертора",
        "sidebar.port": "COM-порт",
        "sidebar.device_id": "Modbus ID",
        "sidebar.groups": "ГРУППЫ ПАРАМЕТРОВ",
        "sidebar.files": "ФАЙЛ НАСТРОЕК",
        "table.search": "Поиск: код или описание",
        "column.code": "Код",
        "column.parameter": "Параметр",
        "column.value": "Значение",
        "column.unit": "Ед.",
        "column.default": "Завод.",
        "column.range": "Диапазон / варианты",
        "group.all": "Все параметры",
        "filter.all": "Все",
        "filter.writable": "Для записи",
        "filter.readonly": "Только чтение",
        "filter.edited": "Изменённые",
        "filter.errors": "Ошибки",
        "details.none": "Параметр не выбран",
        "details.writable": "Изменяемый",
        "details.readonly": "Только чтение",
        "details.group": "группа {group}",
        "details.running_yes": "меняется на ходу",
        "details.running_no": "менять только на остановке",
        "details.manual_page": "рук. стр. {page}",
        "details.default": "Заводское {value}",
        "details.translation_note": "Примечание к источнику: {note}",
        "status.ready": "Готово",
        "status.counts_shown": "показано {shown} из {total}",
        "status.counts_edited": "изменено: {n}",
        "status.counts_errors": ("{n} ошибка", "{n} ошибки", "{n} ошибок"),
        "status.ports_available": (
            "доступен {n} COM-порт",
            "доступно {n} COM-порта",
            "доступно {n} COM-портов",
        ),
        "status.no_ports": "COM-порты не найдены",
        "status.busy": "Другая операция ещё выполняется",
        "status.wait_operation": "Дождитесь завершения текущей операции",
        "status.manual_opened": "Руководство открыто в браузере",
        "status.no_manual": "Для этой модели нет ссылки на руководство",
        "status.profile_loaded": "Загружена карта параметров {model}",
        "status.profile_missing": "Сохранённая модель {profile} больше недоступна; выбрана {model}",
        "status.revision_detected": "Определена ревизия {model} (F02.26 = {value})",
        "status.progress": "{title} — {done}/{total}",
        "status.working": "{title}…",
        "status.cancelling": "Отмена…",
        "status.cancelled": "{title}: отменено",
        "status.failed": "{title}: ошибка — {error}",
        "status.link_ok": "Связь есть — {code} = {value}",
        "status.read_result": "Прочитано {ok} из {total} параметров",
        "status.write_result": (
            "Записан {n} параметр",
            "Записано {n} параметра",
            "Записано {n} параметров",
        ),
        "status.write_partial": "Записано {written}, с ошибкой {failed}",
        "status.saved": "Сохранено настроек: {n} → {file}",
        "status.save_failed": "Не удалось сохранить файл: {error}",
        "status.loaded": "Загружено настроек: {n} из {file}{note}",
        "status.loaded_note": (
            ", пропущен {n} неизвестный код",
            ", пропущено {n} неизвестных кода",
            ", пропущено {n} неизвестных кодов",
        ),
        "status.load_failed": "Не удалось открыть файл: {error}",
        "link.idle": "Нет связи",
        "link.no_port": "порт не выбран",
        "link.summary": "{port}  ·  {link}  ·  ID {device_id}",
        "task.detect": "Определение ревизии",
        "task.test_link": "Проверка связи",
        "task.read_group": "Чтение: {group}",
        "task.read_all": "Чтение всех параметров ({n})",
        "task.write": "Запись: {scope}",
        "task.read_for_save": "Чтение настроек для сохранения",
        "scope.group": "группа {group}",
        "scope.all_groups": "все группы",
        "scope.all_parameters": "все параметры",
        "dialog.serial_ports.title": "COM-порты",
        "dialog.serial_ports.body": "COM-порты не найдены",
        "dialog.select_port.title": "COM-порт",
        "dialog.select_port.body": "Сначала выберите COM-порт",
        "dialog.device_id.title": "Modbus ID",
        "dialog.device_id.body": "Modbus ID должен быть от 1 до 247",
        "dialog.connection.title": "Подключение",
        "dialog.nothing_to_read.title": "Нечего читать",
        "dialog.nothing_to_read.body": "В этой группе нет параметров",
        "dialog.invalid_value.title": "Недопустимое значение",
        "dialog.invalid_value.body": "{code}: {problem}",
        "dialog.invalid_values.title": "Недопустимые значения",
        "dialog.invalid_values.none": "Записывать нечего:\n\n{problems}",
        "dialog.invalid_values.skip": (
            "{n} значение нельзя записать:\n\n{problems}\n\n"
            "Пропустить его и записать остальные ({rest})?",
            "{n} значения нельзя записать:\n\n{problems}\n\n"
            "Пропустить их и записать остальные ({rest})?",
            "{n} значений нельзя записать:\n\n{problems}\n\n"
            "Пропустить их и записать остальные ({rest})?",
        ),
        "dialog.more": "\n…и ещё {n}",
        "dialog.nothing_to_write.title": "Нечего записывать",
        "dialog.nothing_to_write.body": (
            "Значений пока нет. Сначала прочитайте инвертор или загрузите файл настроек."
        ),
        "dialog.confirm_write.title": "Подтверждение записи",
        "dialog.confirm_write.body": (
            "Записать {count} ({scope}) в {model}\n"
            "через {port} (Modbus ID {device_id})?\n\n"
            "Изменено в таблице: {edited}."
        ),
        "dialog.confirm_write.count": ("{n} параметр", "{n} параметра", "{n} параметров"),
        "dialog.confirm_write.edited": ("{n} значение", "{n} значения", "{n} значений"),
        "dialog.write_errors.title": "Ошибки записи",
        "dialog.write_errors.body": (
            "Не записан {n} параметр:\n\n{details}",
            "Не записано {n} параметра:\n\n{details}",
            "Не записано {n} параметров:\n\n{details}",
        ),
        "dialog.save.title": "Сохранить настройки в файл",
        "dialog.load.title": "Загрузить настройки из файла",
        "dialog.json_files": "Файлы JSON",
        "dialog.all_files": "Все файлы",
        "dialog.save_failed.title": "Сохранение не удалось",
        "dialog.load_failed.title": "Загрузка не удалась",
        "dialog.closing.title": "Операция выполняется",
        "dialog.closing.body": "Операция Modbus ещё выполняется. Всё равно закрыть?",
        "valid.read_only": "параметр только для чтения",
        "valid.number": "должно быть числом",
        "valid.between": "должно быть от {minimum} до {maximum}{unit}",
        "valid.bcd_digits": "должно содержать ровно {digits} цифр из {chars}",
        "valid.hex_digits": "должно содержать ровно {digits} шестнадцатеричных цифр из {chars}",
        "valid.function_code": "должно быть кодом функции, например 25.00",
        "valid.function_group": "группа функции должна быть от 00 до {maximum}",
        "valid.function_number": "номер функции должен быть от 00 до 99",
        "valid.digit_limits": "разряды не должны превышать {pattern} (по одной настройке на разряд)",
        "valid.maximum_from": "не должно превышать {code}, а там {limit}{unit}",
        "valid.minimum_from": "не должно быть меньше {code}, а там {limit}{unit}",
        "valid.register_range": "не помещается в 16-битный регистр (0-{maximum})",
        "valid.problem": "{code}  —  {problem} (введено «{value}»)",
        "valid.encode_problem": "{code}  —  {problem}",
        "error.open_port": "Не удалось открыть {port}",
        "error.unknown_profile": "Неизвестный профиль инвертора в файле: {profile}",
        "error.not_a_settings_file": "Файл не содержит блок настроек инвертора",
        "error.unsupported_version": "Неподдерживаемая версия файла настроек: {version}",
        "error.raw_out_of_range": "Значение регистра для {code} вне диапазона 0..65535",
        "error.invalid_value": "Недопустимое значение: {value}",
        "error.invalid_function_code": "Недопустимый код функции: {value}",
    },
    "sr": {
        "header.subtitle": "{model}  ·  {parameters}  ·  {groups}  ·  v{version}",
        "count.parameters": ("{n} parametar", "{n} parametra", "{n} parametara"),
        "count.groups": ("{n} grupa", "{n} grupe", "{n} grupa"),
        "action.manual": "Uputstvo",
        "action.theme_dark": "Tamna tema",
        "action.theme_light": "Svetla tema",
        "action.test_link": "Test veze",
        "action.read_group": "↓ Očitaj grupu",
        "action.write_edited": "↑ Upiši izmene",
        "action.read_all": "↓ Očitaj sve",
        "action.write_all": "↑ Upiši sve",
        "action.load": "Učitaj…",
        "action.save": "Sačuvaj…",
        "action.cancel": "Otkaži",
        "sidebar.connection": "VEZA",
        "sidebar.model": "Model invertora",
        "sidebar.port": "Serijski port",
        "sidebar.device_id": "Modbus ID",
        "sidebar.groups": "GRUPE PARAMETARA",
        "sidebar.files": "DATOTEKA SA PODEŠAVANJIMA",
        "table.search": "Pretraga: šifra ili opis",
        "column.code": "Šifra",
        "column.parameter": "Parametar",
        "column.value": "Vrednost",
        "column.unit": "Jed.",
        "column.default": "Fabrički",
        "column.range": "Opseg / opcije",
        "group.all": "Svi parametri",
        "filter.all": "Sve",
        "filter.writable": "Za upis",
        "filter.readonly": "Samo čitanje",
        "filter.edited": "Izmenjeni",
        "filter.errors": "Greške",
        "details.none": "Nijedan parametar nije izabran",
        "details.writable": "Za upis",
        "details.readonly": "Samo čitanje",
        "details.group": "grupa {group}",
        "details.running_yes": "menja se u radu",
        "details.running_no": "menjati samo u mirovanju",
        "details.manual_page": "uputstvo str. {page}",
        "details.default": "Fabrički {value}",
        "details.translation_note": "Napomena o izvoru: {note}",
        "status.ready": "Spremno",
        "status.counts_shown": "prikazano {shown} od {total}",
        "status.counts_edited": "izmenjeno: {n}",
        "status.counts_errors": ("{n} greška", "{n} greške", "{n} grešaka"),
        "status.ports_available": (
            "dostupan {n} serijski port",
            "dostupna {n} serijska porta",
            "dostupno {n} serijskih portova",
        ),
        "status.no_ports": "Nema serijskih portova",
        "status.busy": "Druga operacija je još u toku",
        "status.wait_operation": "Sačekajte da se trenutna operacija završi",
        "status.manual_opened": "Uputstvo je otvoreno u pregledaču",
        "status.no_manual": "Nema linka ka uputstvu za ovaj model",
        "status.profile_loaded": "Učitana mapa parametara za {model}",
        "status.profile_missing": "Sačuvani model {profile} više nije dostupan; koristi se {model}",
        "status.revision_detected": "Otkrivena revizija {model} (F02.26 = {value})",
        "status.progress": "{title} — {done}/{total}",
        "status.working": "{title}…",
        "status.cancelling": "Otkazivanje…",
        "status.cancelled": "{title}: otkazano",
        "status.failed": "{title}: greška — {error}",
        "status.link_ok": "Veza radi — {code} = {value}",
        "status.read_result": "Očitano {ok} od {total} parametara",
        "status.write_result": (
            "Upisan {n} parametar",
            "Upisana {n} parametra",
            "Upisano {n} parametara",
        ),
        "status.write_partial": "Upisano {written}, neuspešno {failed}",
        "status.saved": "Sačuvano podešavanja: {n} → {file}",
        "status.save_failed": "Čuvanje datoteke nije uspelo: {error}",
        "status.loaded": "Učitano podešavanja: {n} iz {file}{note}",
        "status.loaded_note": (
            ", preskočena {n} nepoznata šifra",
            ", preskočene {n} nepoznate šifre",
            ", preskočeno {n} nepoznatih šifri",
        ),
        "status.load_failed": "Učitavanje datoteke nije uspelo: {error}",
        "link.idle": "Nema veze",
        "link.no_port": "port nije izabran",
        "link.summary": "{port}  ·  {link}  ·  ID {device_id}",
        "task.detect": "Prepoznavanje revizije",
        "task.test_link": "Provera veze",
        "task.read_group": "Čitanje: {group}",
        "task.read_all": "Čitanje svih parametara ({n})",
        "task.write": "Upis: {scope}",
        "task.read_for_save": "Čitanje podešavanja za čuvanje",
        "scope.group": "grupa {group}",
        "scope.all_groups": "sve grupe",
        "scope.all_parameters": "svi parametri",
        "dialog.serial_ports.title": "Serijski portovi",
        "dialog.serial_ports.body": "Nema pronađenih COM portova",
        "dialog.select_port.title": "Serijski port",
        "dialog.select_port.body": "Prvo izaberite COM port",
        "dialog.device_id.title": "Modbus ID",
        "dialog.device_id.body": "Modbus ID mora biti između 1 i 247",
        "dialog.connection.title": "Veza",
        "dialog.nothing_to_read.title": "Nema šta da se očita",
        "dialog.nothing_to_read.body": "Ova grupa nema parametre",
        "dialog.invalid_value.title": "Neispravna vrednost",
        "dialog.invalid_value.body": "{code}: {problem}",
        "dialog.invalid_values.title": "Neispravne vrednosti",
        "dialog.invalid_values.none": "Nema šta da se upiše:\n\n{problems}",
        "dialog.invalid_values.skip": (
            "{n} vrednost ne može da se upiše:\n\n{problems}\n\n"
            "Preskočiti je i upisati preostale ({rest})?",
            "{n} vrednosti ne mogu da se upišu:\n\n{problems}\n\n"
            "Preskočiti ih i upisati preostale ({rest})?",
            "{n} vrednosti ne može da se upiše:\n\n{problems}\n\n"
            "Preskočiti ih i upisati preostale ({rest})?",
        ),
        "dialog.more": "\n…i još {n}",
        "dialog.nothing_to_write.title": "Nema šta da se upiše",
        "dialog.nothing_to_write.body": (
            "Još nema vrednosti. Prvo očitajte invertor ili učitajte datoteku sa podešavanjima."
        ),
        "dialog.confirm_write.title": "Potvrda upisa",
        "dialog.confirm_write.body": (
            "Upisati {count} ({scope}) u {model}\n"
            "preko {port} (Modbus ID {device_id})?\n\n"
            "Izmenjeno u tabeli: {edited}."
        ),
        "dialog.confirm_write.count": ("{n} parametar", "{n} parametra", "{n} parametara"),
        "dialog.confirm_write.edited": ("{n} vrednost", "{n} vrednosti", "{n} vrednosti"),
        "dialog.write_errors.title": "Greške pri upisu",
        "dialog.write_errors.body": (
            "Nije upisan {n} parametar:\n\n{details}",
            "Nisu upisana {n} parametra:\n\n{details}",
            "Nije upisano {n} parametara:\n\n{details}",
        ),
        "dialog.save.title": "Sačuvaj podešavanja u datoteku",
        "dialog.load.title": "Učitaj podešavanja iz datoteke",
        "dialog.json_files": "JSON datoteke",
        "dialog.all_files": "Sve datoteke",
        "dialog.save_failed.title": "Čuvanje nije uspelo",
        "dialog.load_failed.title": "Učitavanje nije uspelo",
        "dialog.closing.title": "Operacija u toku",
        "dialog.closing.body": "Modbus operacija je još u toku. Ipak zatvoriti?",
        "valid.read_only": "parametar samo za čitanje",
        "valid.number": "mora biti broj",
        "valid.between": "mora biti između {minimum} i {maximum}{unit}",
        "valid.bcd_digits": "mora sadržati tačno {digits} cifara iz {chars}",
        "valid.hex_digits": "mora sadržati tačno {digits} heksadecimalnih cifara iz {chars}",
        "valid.function_code": "mora biti šifra funkcije, na primer 25.00",
        "valid.function_group": "grupa funkcije mora biti između 00 i {maximum}",
        "valid.function_number": "broj funkcije mora biti između 00 i 99",
        "valid.digit_limits": "cifre ne smeju biti veće od {pattern} (jedno podešavanje po cifri)",
        "valid.maximum_from": "ne sme biti veće od {code}, gde stoji {limit}{unit}",
        "valid.minimum_from": "ne sme biti manje od {code}, gde stoji {limit}{unit}",
        "valid.register_range": "ne staje u 16-bitni registar (0-{maximum})",
        "valid.problem": "{code}  —  {problem} (uneto „{value}“)",
        "valid.encode_problem": "{code}  —  {problem}",
        "error.open_port": "Nije moguće otvoriti {port}",
        "error.unknown_profile": "Nepoznat profil invertora u datoteci: {profile}",
        "error.not_a_settings_file": "Datoteka ne sadrži blok podešavanja invertora",
        "error.unsupported_version": "Nepodržana verzija datoteke sa podešavanjima: {version}",
        "error.raw_out_of_range": "Vrednost registra za {code} je izvan opsega 0..65535",
        "error.invalid_value": "Neispravna vrednost: {value}",
        "error.invalid_function_code": "Neispravna šifra funkcije: {value}",
    },
}


def _plural_index(language: str, count: int) -> int:
    """Return the plural form index for ``count`` in ``language``."""
    if language == "en":
        return 0 if count == 1 else 1
    tens, hundreds = count % 10, count % 100
    if tens == 1 and hundreds != 11:
        return 0
    if 2 <= tens <= 4 and not 12 <= hundreds <= 14:
        return 1
    return 2


def system_language(default: str = DEFAULT_LANGUAGE) -> str:
    """Guess the interface language from the environment, English otherwise."""
    candidates = [
        value
        for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")
        if (value := os.environ.get(name))
    ]
    try:
        import locale

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            code = locale.getdefaultlocale()[0]
        if code:
            candidates.append(code)
    except Exception:  # pragma: no cover - platform specific
        pass

    for candidate in candidates:
        name = candidate.split(".")[0].replace("-", "_").lower()
        if name.startswith(("ru", "russian")):
            return "ru"
        if name.startswith(("sr", "serbian")):
            return "sr"
        if name.startswith(("en", "english")):
            return "en"
    return default


class Translator:
    """Look up interface strings for the selected language."""

    def __init__(self, language: str | None = None):
        self.language = DEFAULT_LANGUAGE
        self.set_language(language or system_language())

    def set_language(self, language: str) -> str:
        self.language = language if language in TRANSLATIONS else DEFAULT_LANGUAGE
        return self.language

    def __call__(self, key: str, **params) -> str:
        text = self._lookup(key)
        if isinstance(text, tuple):
            text = text[0]
        return text.format(**params) if params else text

    def plural(self, key: str, count: int, **params) -> str:
        forms = self._lookup(key)
        if isinstance(forms, str):
            forms = (forms,)
        index = min(_plural_index(self.language, count), len(forms) - 1)
        return forms[index].format(n=count, **params)

    def unit(self, unit: str) -> str:
        """Engineering unit in the active language, unchanged if not listed."""
        return UNITS.get(self.language, {}).get(unit, unit)

    def _lookup(self, key: str) -> str | tuple[str, ...]:
        table = TRANSLATIONS.get(self.language, {})
        if key in table:
            return table[key]
        return TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key)
