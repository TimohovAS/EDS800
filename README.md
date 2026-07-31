# ENC Inverter Parameter Editor

**Version 3.0.1**

A Tkinter desktop application for reading, editing, backing up, and restoring
ENC inverter parameters over Modbus RTU.

## Interface

- Sidebar with the connection card (model, serial port, Modbus ID, **Test
  link**) and the group list with parameter counts; **All parameters** shows
  the complete map.
- Instant search over parameter codes and descriptions, plus a row filter
  (`All`, `Writable`, `Read-only`, `Edited`, `Errors`).
- Colour-coded table: edited cells are amber, failed reads are red, read-only
  rows are dimmed and cannot be edited.
- Details panel under the table with the address, group, writability, manual
  page and the full option list of the selected parameter.
- Status bar with the link indicator, live progress and a **Cancel** button;
  all Modbus traffic runs on a worker thread, so the window never freezes.
- English, Russian and Serbian (latin) interface. The language follows the
  system locale on first start and can be switched from the EN / RU / SR
  buttons in the header without restarting.
- Light and dark themes; the language, theme, model, port, Modbus ID and
  window size are remembered in `~/.enc_inverter_editor.json`.

Shortcuts: `F5` read group, `Ctrl+R` read all, `Ctrl+S` save to file,
`Ctrl+O` load from file, `Ctrl+F` search, `Ctrl+T` switch theme, `Esc` clear
the search or cancel a running operation.

Interface strings live in `enc_editor/i18n.py`; a new language only needs one
more entry in `TRANSLATIONS` (plural forms are ordered one / few / many) and,
optionally, a unit table. EN600 parameter names, ranges, and option lists
switch between English and Russian together with the interface. Each EN600 revision has its own Russian catalogue, so
automatic revision detection also selects the matching translated ranges and
options. The V5 catalogue comes from the current ESQ-500/600 08.04.500
function table, which contains the same 651 parameter codes and layouts.
Legacy entries that differ between the Russian and English V2 manuals are
reconciled explicitly and show a source note in the parameter details panel.

## Supported inverter profiles

- **ENC EDS800** - 198 parameters in groups `F0` through `Fd`.
- **ENC EN600-2S0007 — Auto revision** - probes `F02.26` before the first
  operation and selects the matching map automatically.
- **ENC EN600-2S0007 — V2.0-A2 (legacy)** - 562 parameters; retained for
  older firmware where `F02.26` is unavailable.
- **ENC EN600-2S0007 — V5.0-A13** - 651 parameters in 26 groups, including
  `F02.26`, F17, F21, F22, F24, and documented reserved keypad rows.

Select the inverter model before reading or loading settings. The group list,
parameter map, scaling, read-only flags, and Modbus addresses change with the
selected profile.

Auto detection reads `F02.26` without writing anything. A value in its
documented `95–115%` range selects V5.0-A13; otherwise the legacy V2.0-A2 map
is used. Saved JSON files record the detected concrete revision.

## Project layout

```
enc_editor/catalog.py     profiles loaded and validated from profiles/
           codecs.py      register bits <-> displayed text, one class per encoding
           transport.py   Modbus RTU: batched reads, writes, cancellation
           detection.py   automatic revision detection driven by a manifest
           session.py     what was read, what was edited, what may be written
           i18n.py        interface translations and unit tables
           ui/app.py      the Tk window (the only module that knows widgets)
profiles/<key>/profile.json  manifest: identity, link settings, group table
               parameters.json
               translations/<lang>.json
inverter_parameter_editor.py  entry point
```

No module contains model-specific knowledge: every parameter map, serial
setting and detection rule comes from `profiles/`.

## Adding an inverter model

1. Create `profiles/<key>/profile.json`:

```json
{
  "key": "my_model",
  "model": "MY-MODEL-1", "series": "MY", "order": 50,
  "label": { "en": "My inverter", "ru": "Мой инвертор" },
  "link": { "baudrate": 9600, "parity": "N", "stopbits": 1, "bytesize": 8,
            "timeout": 1.0, "device_id": 1, "max_read_registers": 10 },
  "groups": { "F00": 0, "F01": 1 },
  "parameters": "parameters.json",
  "translations": { "ru": "translations/ru.json" },
  "manual_url": "https://example.com/manual.pdf"
}
```

2. Put the function table in `profiles/<key>/parameters.json`. Every row needs
   `code`, `description`, `range`, `minimum`, `maximum`, `unit`, `address`,
   `group`, `default`, `scale`, `encoding`, `read_only`. Encodings `bcd` and
   `hex` also need `digits` and `digit_chars`; `function_code` needs
   `maximum_group`. A default that is not a number goes to `default_note`.
   Keypad fields where each digit selects a setting carry `digit_limits`, the
   highest value per digit in the manual's own `0000~2112` notation, with `*`
   for a digit the manual leaves unconstrained. `tools/build_digit_limits.py`
   derives them from the printed option lists.
3. Optional: a Russian catalogue in `translations/ru.json` as
   `{"language": "ru", "parameters": {"F00.00": {"description": "...", "range": "..."}}}`.
4. Run the tests. `tests/test_catalog.py` checks the new model automatically:
   unique codes and addresses, addresses matching the group table, known
   encodings with their required fields, defaults that pass validation, and
   translations covering every code.

A model whose revision must be probed adds a `detect` block instead of its own
table - see `profiles/en600_auto/profile.json`. A new encoding is a class in
`enc_editor/codecs.py` plus one `register()` call.

Settings files are written as `format_version` 3 and are only read back at that
version; a file whose `profile` key no longer exists is rejected with a clear
message instead of being guessed at.

## Requirements

- Windows with Python 3.10 or newer (including Tcl/Tk)
- pymodbus 3.10 or newer, which is where the Modbus calls take `device_id`
- A supported inverter connected through a USB-to-RS485 adapter
- Default connection settings: 9600 baud, 8 data bits, no parity, 1 stop bit
- Modbus device address 1

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

```powershell
.\.venv\Scripts\python.exe inverter_parameter_editor.py
```

The program can be opened without an inverter. A COM port is required only for
read/write operations. Both the COM port and Modbus device ID are selectable.

## Test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

## Parameter handling

- EDS800 examples: `F0.03 = 0x0003`, `F2.11 = 0x020B`, and
  `Fd.14 = 0x0D0E`.
- EN600 uses `PPnn` addressing: the group is the high byte and the decimal
  function number is the low byte. Examples: `F05.03 = 0x0503` and
  `F26.17 = 0x1A11`.
- Decimal values are scaled according to the manual. For example, `50.25 Hz`
  is stored as register value `5025`.
- Packed-BCD keypad fields are decoded using their actual display width and
  nibble position on EN600 (`F00.14: 0x0500 → 500`,
  `F01.16: 0x1000 → 1000`, `F13.14: 0x0011 → 011`,
  `F14.14: 0x2000 → 2000`). Hexadecimal selection fields such as `F10.01`
  retain their hexadecimal notation.
- Function-code references are decoded from packed register form; for example,
  `F05.18: 0x2500 → 25.00` instead of treating decimal `9472` as a scaled
  number.
- Device-verified V5 PID gain formatting overrides the printed manual:
  `F11.07: 50 → 000.50` and `F11.08: 25 → 00.25`.
- Keypad fields are checked digit by digit, not just against their alphabet:
  `F14.14` rejects `2222` because the manual documents `0000~2112`, and
  `F10.01` rejects `FFF` against `000H~E22H`. `F06.21` holds five 0/1 settings
  as a decimal register, so it accepts `10101` but not `22222`.
- Every edited value must also fit one 16-bit holding register; a profile whose
  documented maximum for a writable row exceeds `65535` fails to load.
- `Fd` fault-history parameters and `F2.52` accumulated run time are read-only
  on EDS800. Group `F26` is read-only on EN600.
- Saved JSON files include the inverter profile and Modbus ID. Loading a file
  automatically selects the matching profile and prevents cross-model writes.
- Contiguous parameters are read in Modbus batches, with automatic fallback to
  single-register reads when a model-specific register is unavailable. EN600
  batches are limited to the documented maximum of 10 registers.

## EN600 communication setup

For the default application connection, verify these keypad parameters:

- `F05.00 = 0` - Modbus protocol.
- `F05.01` units digit `5` - 9600 baud (displayed as BCD `005`).
- `F05.02` units digit `0` - RTU, 8 data bits, no parity, 1 stop bit.
- `F05.03` - inverter address; select the same value in **Modbus ID**.

Password group `F27` and monitor group `C` are excluded. Rows explicitly
marked reserved in the V5 manual remain visible so the map matches the keypad,
but they are strictly read-only (for example, `F07.17 = 00000`).

## Regenerating the EN600 parameter data

The checked-in `profiles/en600_v5/parameters.json` is generated from pages
57-98 of the V5.0-A13 manual. The legacy V2 map lives in
`profiles/en600_v2/parameters.json`:

```powershell
python -m pip install -r requirements-dev.txt
python tools\extract_en600_parameters.py EN500-EN600-Series-Manual-V5.0-A13.pdf profiles\en600_v5\parameters.json
```

Per-digit limits for keypad fields are derived from the same tables:

```powershell
python toolsuild_digit_limits.py            # report only
python toolsuild_digit_limits.py --write    # update the profiles
```

The two Russian EN600 catalogues are generated independently from their
matching manuals:

```powershell
python tools\extract_en600_translations.py esq-500-600-ru.pdf profiles\en600_v5\parameters.json profiles\en600_v5	ranslations
u.json
python tools\extract_en600_translations.py instruction-EN500-RU.pdf profiles\en600_v2\parameters.json profiles\en600_v2	ranslations
u.json --revision v2
```

## Safety

Writing inverter parameters can start, stop, or materially change motor
behaviour. Disconnect the motor from hazardous loads, keep an original JSON
backup, and verify model-specific motor values in group `F8` before using
**Write all**. For EN600, verify motor group `F15`. Every write asks for
confirmation and lists how many values were edited; values outside the
documented range are reported and skipped.

**Write edited** writes only cells edited in the current table. EN600 action
parameters `F00.14` (reset/protection operations) and `F00.27`
(upload/download) are never replayed by a bulk write unless explicitly edited.

Parameter sources:

- [ENC EDS800 Series Service Manual](https://thanglongautomation.com/upload/files/ENC-EDS800%20Manual.pdf)
- [ENC EN500/EN600 V5.0-A13 User Manual](https://konel.ba/wp-content/uploads/2024/05/EN500-EN600-Series-Manual-V5.0-A13.pdf)
- [ESQ-500/600 08.04.500 Russian User Manual](https://www.elcomspb.kz/upload/iblock/b75/kur8dsapkq4n6pdy81dewj8rnt5nut39.pdf)
- [ENC EN500/EN600 legacy Russian User Manual](https://sparks.su/upload/doc/p-ch-en-500-en-600/instruction-EN500.pdf)
