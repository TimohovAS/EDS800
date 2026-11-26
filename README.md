# Inverter Parameter Editor

**Version 3.8.0**

A Tkinter desktop application for reading, editing, backing up, and restoring
ENC, Danfoss, VACON and XINJE inverter parameters over Modbus RTU or native Danfoss FC.

## Interface

- Full-height group sidebar with localized manual group names and parameter
  counts; **All parameters** shows the complete map. Drag the divider to change
  the sidebar width. The compact workspace fits a 1100×660 laptop window.
- The gear in the blue header opens **Connection settings** for manufacturer,
  model, serial port, device address, protocol, baud rate, parity, stop bits and
  response timeout. Hover over or focus the gear to see the full link summary.
  **Test link** and **Alarms / diagnostics** are in the bottom status bar.
  It also opens on first launch. **Apply** saves PC settings without contacting
  the drive; **Test link** checks the dialog's current draft by reading one
  parameter (plus revision detection for an automatic profile). The dialog stays
  open and displays the tested port/frame/address and the result or error as
  borderless text in the free space below the device address. Long messages are
  available in full on hover; results do not enlarge the dialog.
  Testing never applies settings, clears edits, or changes drive parameters;
  use **Apply** or **Work offline** to commit the draft. Fields are locked during
  the test; **Cancel test** interrupts it without closing the dialog. Changing a
  field clears the previous result. Eight data bits are fixed. Serial settings
  are saved per profile and never reconfigure the drive. Changing the target or
  serial settings clears cached values, with confirmation if there are edits;
  **Cancel** and applying unchanged settings preserve edits. An unplugged saved
  port is kept, never silently replaced by a different adapter.
  FC uses addresses 1–126; Modbus normally uses 1–247, with
  VACON NXL's documented extension to 255 supported by its profile.
- The folder and floppy-disk buttons in the blue header load and save settings
  files (Ctrl+O / Ctrl+S). Hover over or focus an icon for a localized tooltip;
  both buttons are disabled while communication is in progress. There is no
  separate menu bar taking up vertical space.
- **Work offline** in the connection dialog allows editing without a drive.
  The load/save icons (Ctrl+O / Ctrl+S) load a settings file or export known
  writable values with validated edits; unknown values are not filled in.
  Offline export does not read the drive or mark edits as written. In online mode,
  Save keeps the existing backup behavior: read writable parameters from the drive
  and save that snapshot. Offline device actions reopen connection setup without
  opening a port.
- Instant search over parameter codes and descriptions, plus a row filter
  (`All`, `Writable`, `Read-only`, `Edited`, `Errors`).
- Colour-coded table: edited cells are amber, failed reads are red, read-only
  rows are dimmed and cannot be edited. The factory cell turns violet where the
  drive no longer holds the manual's default, so a commissioned inverter can be
  compared against the works settings at a glance. The comparison is made on
  the register, not the text, so `0.0500` and `000.05` count as the same
  setting; a parameter whose default depends on the motor is never marked.
- Details panel under the table with the address, group, writability, manual page
  and full option list, expanded by default (including upgrades from the old
  collapsed default). Use the labeled **Hide / Show description** button to
  collapse or expand it; drag the horizontal divider to resize. Its height and
  an explicit visibility choice are remembered.
  Search/actions wrap onto two rows when the workspace is narrow.
- FC 51 diagnostics: decoded alarm/warning/status words and all ten fault-log
  entries in the read-only **Decoded status** column and **Alarms / diagnostics**
  window. This works over RS485 without an LCP keypad. Unknown bits/codes stay
  explicit; a failed read is never shown as "no alarms". The window reads a
  timestamped snapshot, not a continuous monitor; refresh it after changes.
- **Reset trip** pulses only FC control bit 7 (wire coil 7), with confirmation,
  fresh safety checks and a status reread. It refuses RUN/JOG, running/auto-start,
  trip lock, failed status reads, or an ignored control word (bit 10 = 0).
  It never enables an ignored control word, changes the control source, writes
  Start/speed, clears history or restores factory defaults. Remove external RUN
  commands before reset: clearing a fault can otherwise permit a restart.
  This command is available over **Modbus RTU only**. Native FC deliberately
  exposes only the parameter channel: a reset would require a valid process
  control word and would also replace the motor's bus speed reference.
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

### XINJE VH5-45P5-B

Select manufacturer **XINJE**, model **VH5-45P5-B — 5.5 kW / 380 V**.
The profile comes from the official XINJE VH5 manual INVC0620240409EN1.3.3:
548 parameters, 22 groups, 427 settings supported for writing (some require a
successfully read selector/version), Russian names and group titles,
and read-only state/fault decoding (including communication timeout and overcurrent).
Detailed ranges remain in the source language. Default PC communication is
**Modbus RTU, 19200 baud, 8E1, address 1**, based on P9-01/02/03; the appendix's
generic no-parity sentence contradicts the explicit P9-03 factory code 1.

Reads use at most 12 registers per same-group request. Parameter writes use
FC06 and the documented power-off-memory addresses; process-command registers
(start/stop/jog, bus reference and reset) are not exposed. P9 communication
settings are written only when explicitly edited, never replayed by bulk restore.
All four ramp groups (P0-18/19 and PC-03..08) use PC-09 resolution. Jog ramps
PC-01/02 retain their documented fixed 0.1 s unit. PLC step times follow PB-50
(seconds/hours); changing that unit and its times in one batch is rejected.
Reads automatically include selectors and referenced bounds; writes verify the
live selector/version/guard values before sending dependent parameters.
PF meanings follow **functional version P8-16**, not performance version P8-15.
The panel's `uXX.XX` register is decoded only when decimal/BCD interpretations
are unambiguous. Unknown/unsupported revisions block PF writes.
Reviewed AI voltage curves, U/f/PID/frequency bounds, S-curve sum constraints,
hex display masks and 380 V model voltage limits are included. A9 address
entries are editable only on supported firmware with A9-00 disabled, and only
when explicitly edited. A9 activation is not a normal/bulk write.
62 configuration rows remain blocked (61 marked writable in the manual plus
A1-11, whose modification column is blank). Their exact codes and reasons are
listed in `VH5_SUPPORT_STATUS.md`; the app header also states this limitation.
Unconfirmed digit packing, parameter-reference packing, service actions and
contradictory addresses are not guessed. Group A4 explicitly cannot be written
over communication according to the detailed manual.
JSON backups now include all read results, including read-only/unsupported raw
registers and versions. Loading a backup never makes a read-only row writable.
The complete functional-37.44 snapshot and panel confirmation corrected PC-44/45
to 0.1 V resolution and P2-26 to signed voltage. Negative P2-26 writes are
enabled only on the confirmed 37.44 revision; other revisions retain the manual's
0 V lower limit. P2-54 uses panel-style `H.321` hex, P2-55 shows `H.000`, whereas
P7-39/P8-22 use decimal digits. These four are enabled only on confirmed functional 37.44,
only when explicitly edited, with live-value and reserved-bit checks before
any batch writes. P2-54/55 only allow changes to the active ones digit;
historical/inactive digits stay unchanged. Zero-only panel samples for P0-05/20,
P2-16 and P3-11 do not unlock their unconfirmed higher-digit packing.
Fixture-based tests preserve the original raw readings.
PC-41/42 are omitted because the table duplicates unrelated PC-28/29 addresses;
local-only P8/A4 and U4 rows without published bus addresses are not invented.
Hardware communication and firmware compatibility still require verification on
the actual drive. A successful read does not prove the firmware-dependent rows
are supported. The generator is `tools/extract_vh5_parameters.py`.

- **ENC EDS800** - 198 parameters in 11 groups with English and Russian
  explanations, option values, and fault history decoding.
- **ENC EN600-2S0007 — Auto revision** - probes `F02.26` before the first
  operation and selects the matching map automatically.
- **ENC EN600-2S0007 — V2.0-A2 (legacy)** - 562 parameters; retained for
  older firmware where `F02.26` is unavailable.
- **ENC EN600-2S0007 — V5.0-A13** - 651 parameters in 26 groups, including
  `F02.26`, F17, F21, F22, F24, and documented reserved keypad rows.
- **Danfoss VLT Micro Drive FC 51 — 5.5 kW / T4** - type code
  `FC-051P5K5T4E20HXBXCXXXSXXX`; 227 parameters from the MG02C602
  typed parameter lists, displayed as 334 rows including array elements in
  13 groups. English and Russian names, options and group titles are included.

Choose **Manufacturer** first; the model list shows only that manufacturer's
profiles. The saved profile also restores the manufacturer on the next launch.

Select the inverter model before reading or loading settings. The group list,
parameter map, scaling, read-only flags, and Modbus addresses change with the
selected profile.

Auto detection reads `F02.26` without writing anything. A value in its
documented `95–115%` range selects V5.0-A13; otherwise the legacy V2.0-A2 map
is used. Saved JSON files record the detected concrete revision.

### ENC EDS800 — справочник по функциям

Выберите модель **ENC EDS800** и язык **RU**. В таблице появятся русские названия,
а в панели **Показать описание** — назначение выбранного параметра, варианты
значений, связанные коды и номер страницы PDF. Поиск находит коды и текст
описаний на русском и английском.

| Группа | Что в ней настраивается |
|---|---|
| `F0` | Источник задания частоты и команд пуска, направление, разгон и замедление, кривая V/F |
| `F1` | Пусковая частота, способ останова и торможение постоянным током |
| `F2` | Режим JOG, настройки RS-485, наборы разгона и замедления, ступени и пропуски частот |
| `F3` | ПИД-регулятор, поддержание давления, режим сна и назначение реле |
| `F4` | Режим встроенного ПЛК и семь ступеней с заданной длительностью |
| `F5` | Назначение входов X1–X5 и выходов OC, AO, DO, режим FWD/REV, счётчик и таймер |
| `F6` | Траверса — периодическое качание частоты |
| `F7` | Масштабирование задания по VCI, CCI и импульсным сигналам |
| `F8` | Номинальные данные двигателя и поправка индикации частоты |
| `F9` | Перегрузка, предотвращение перенапряжения, ограничение тока и автосброс |
| `Fd` | Шесть записей об авариях и рабочие показания на момент последней аварии |

Для прочитанных `Fd.00`–`Fd.05` редактор показывает код `E001`–`E023` и его
расшифровку. Описания сверены с разделами 5.2, 6.1–6.11 и 7.1–7.2.
[Руководство ENC EDS800 V3.0-A4](https://thanglongautomation.com/upload/files/ENC-EDS800%20Manual.pdf)

### Connecting a Danfoss FC 51

For an unconfigured drive without an LCP keypad, select **Danfoss**, **VLT Micro
Drive FC 51**, the USB–RS485 COM port and device address **1**. The profile now
defaults to **Danfoss FC, 9600 8E1**, matching the factory settings. Use **Test
link**. **Settings…** lets you match a drive configured differently; the program
does not scan devices or automatically change their protocol.

For an already configured Modbus drive, choose **Modbus RTU** in **Settings…**
(preset **19200 8E1**), then match its actual baud rate, parity and address.
On the drive, Modbus requires `8-30 = 2`; `8-31` is the address, `8-32` selects
the baud rate and `8-33` the parity/stop bits. Changing `8-30` requires a power
cycle before the new protocol takes effect. A PC-side protocol selection does
not change `8-30`. No physical connection to the user's drive was available
for the native FC implementation; validate it on the actual hardware before
commissioning or restoring settings.

The native FC transport implements the parameter channel from MG02K402:
STX/LGE/ADR framing, XOR BCC, PNU/subindex correlation, word/double-word values,
indexed values, read-only text and explicit EEPROM word/double-word writes.
Parameter telegrams always carry **CTW=0 / REF=0 (Data valid=0)**, never a valid
Start/Jog/control command. Echoes, malformed packets, mismatched replies and
unconfirmed write values are not treated as success. Writes are never retried.
Reading indexed values uses IND, not Modbus index-register writes.

FC 51 has a different register map from ENC: bus addresses are `10 × PNU − 1`
(for example `3-03` starts at address 3029). The editor handles signed values,
one- and two-register numbers, and read-only ASCII identification fields.
Indexed values such as `3-10[0]` through `3-10[7]` select their index through
holding register 9 (bus address 8). Parameter writes enable nonvolatile
storage through coil 65 (bus address 64); failed index/storage selection stops
the affected operation instead of using stale settings.

Reset, tuning, copying and communication-change commands are written only
after an explicit edit; a bulk restore does not replay their read-back values.
Communication changes are sent after ordinary settings.

Sources are the official Danfoss
[Programming Guide MG02C602](https://assets.danfoss.com/documents/273445/AU361182403098en-000301.pdf)
(software 2.7X) and
[Design Guide MG02K402](https://assets.danfoss.com/documents/273509/AJ361178983102en-000401.pdf).
The older Russian MG02C250 supplies names, not bus types or ranges.
Disagreements between overview tables and detailed descriptions are noted in
parameter details; writable ranges use their intersection. Rows `8-80`–`8-83`
and `18-80`–`18-81` have no bus-type entry in these typed lists and are omitted
rather than assigned a guessed register layout. Hardware communication must
still be checked on the particular drive and firmware.

### Connecting a VACON NXL NXL00075C5H1SSS00

Select **VACON → NXL00075C5H1SSS00 — Multi-Control v3.45**, the USB–RS485
port and matching device address. The PC preset is **Modbus RTU, 9600 8N1,
address 1**. Match the actual drive settings in **Settings…**. On the keypad,
check `P6.10.2 = 1` (Modbus), `P6.10.3` (address), `P6.10.4 = 5` (9600),
`P6.10.5 = 0` (one stop bit) and `P6.10.6 = 0` (no parity). Do not change the
control place merely to read/edit parameters. Application table `P3.1` uses
1=I/O, 2=keypad, 3=fieldbus; the user manual's process-data paragraph saying
2=fieldbus is inconsistent with that application table.

This profile is specifically **Multi-Control ALFIFF20 v3.45**, not an arbitrary
NXL application. Verify the application/version before writing. The type code
identifies a 380–500 V, MF4/IP54 drive with internal brake chopper; the rating
table lists IL=7.6 A and IH=5.6 A. Hardware operation has not been verified.

There are **170 unique register IDs in 13 groups, 128 writable**. The two
duplicate menu entries (`P2.2.12`/`P2.1.15`, `P2.3.5`/`P2.1.16`) are stored once,
with searchable aliases listed in their ranges. IDs lacking a published bus
address (keypad-only `R3.2`, `R3.5`, `R3.6`, system-menu settings) are not guessed.
Wire addresses are **ID − 1**, and read batches are limited to eleven words.
No FC51 EEPROM coil or index-register operation is used.

The **FB** group has documented engineering-unit readouts, current status and
the active fault with its own 28-code fault decoder. Other menu-V1 values whose
bus scale is not specified are explicitly labelled **raw**, without engineering
units; `V1.26` has its documented 0.1% scale. Fault history H5 and remote reset
are not exposed, and process-control inputs 2001–2011 are absent.

Five motor/drive-dependent current parameters (`P2.1.5`, `P2.1.9`, `P2.4.3`,
`P2.4.8`, `P2.7.12`) are deliberately **read-only raw values** until write limits
and bus precision are verified on this MF4. This is a profile safety restriction,
not a claim that the drive itself cannot change them. Identification, control
place, direction, Stop-button mode and automatic restart require explicit edits;
a backup/bulk restore never replays their read-back values automatically.

The generator includes source corrections explicitly: `P2.9.1` accepts option 2,
`P2.2.6` accepts option 0, AI selectors accept only 10/11/20/21, and brake chopper
selection accepts only 0/1/3. Russian names, choices and group titles are included.

Sources: [NXL Multi-Control application manual](https://assets.danfoss.com/documents/272960/AB361177530779en-000301.pdf),
[NXL user manual](https://assets.danfoss.com/documents/273274/BC361182955783en-000301.pdf),
and [NX Modbus addressing examples](https://assets.danfoss.com/documents/latest/270758/BC361182933763en-000101.pdf).
Regenerate the map with:

```powershell
.\.venv\Scripts\python.exe tools\extract_nxl_parameters.py NXL-Multi-Control.pdf profiles\vacon_nxl
```

## Project layout

```
enc_editor/catalog.py     profiles loaded and validated from profiles/
           connection.py   validated per-profile PC connection settings
           fc_protocol.py  native Danfoss FC parameter channel
           codecs.py      register bits <-> displayed text, one class per encoding
           dependencies.py  bounds between parameters: write order and refusals
           transport.py   Modbus RTU: batched reads, writes, cancellation
           detection.py   automatic revision detection driven by a manifest
           session.py     what was read, what was edited, what may be written
           i18n.py        interface translations and unit tables
           ui/app.py      the Tk window (the only module that knows widgets)
profiles/<key>/profile.json  manifest: identity, link settings, group table
               parameters.json
               translations/<lang>.json
inverter_parameter_editor.py  entry point
packaging/enc_editor.spec     PyInstaller build
          installer.iss       Inno Setup installer
          build.ps1           both of the above, in one command
```

No module contains model-specific knowledge: every parameter map, serial
setting and detection rule comes from `profiles/`.

## Adding an inverter model

1. Create `profiles/<key>/profile.json`:

```json
{
  "key": "my_model",
  "manufacturer": "My manufacturer",
  "model": "MY-MODEL-1", "series": "MY", "order": 50,
  "label": { "en": "My inverter", "ru": "Мой инвертор" },
  "link": { "baudrate": 9600, "parity": "N", "stopbits": 1, "bytesize": 8,
            "timeout": 1.0, "device_id": 1, "max_read_registers": 10 },
  "groups": { "F00": 0, "F01": 1 },
  "group_labels": {
    "en": { "F00": "System parameters", "F01": "Basic run functions" },
    "ru": { "F00": "Системные параметры", "F01": "Основные функции работы" }
  },
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
   derives them from the printed option lists. A row whose limit is another
   parameter (`0.00Hz~upper limit frequency`) carries `minimum_from` /
   `maximum_from` with that parameter's code, which is what drives the write
   order; `tools/build_dependencies.py` derives those from the printed ranges.
   Other register layouts may specify `register_count`, `data_bits`, `signed`
   and `array_index`. The FC 51 manifest uses `addressing: "danfoss_pnu"`,
   `link.index_register` and `link.persist_coil`; ENC retains one-register
   addressing by default. Sparse selections use `allowed_values`; `text`
   fields are read-only ASCII packed in `register_count` registers.
3. Optional: a Russian catalogue in `translations/ru.json` as
   `{"language": "ru", "parameters": {"F00.00": {"description": "...", "range": "..."}}}`.
   The optional `help` field in either catalogue supplies the explanation and
   option list in the details panel and is included in search.
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

## Build the installer

For machines without Python. Needs the dev requirements and Inno Setup 6
(`winget install JRSoftware.InnoSetup`):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

The result is `packaging\output\ENC-Inverter-Editor-<version>-Setup.exe`. The
version is read from `enc_editor.VERSION`, so bumping it there is enough - it
reaches the executable's file properties, the installer name and the entry in
Programs and Features. `-SkipInstaller` stops after the frozen executable in
`packaging\dist\`, which is also usable as a portable copy.

The installer offers Russian and English, installs machine-wide by default and
under the user profile when run without admin rights, and creates Start menu
and optional desktop shortcuts. Installing a newer version replaces the old
one. The profiles stay readable JSON in `_internal\profiles\`, so a model can
be added to an installed copy without rebuilding.

`packaging\enc_editor.ico` is generated by `packaging\make_icon.py`; run it
again only if the brand colours in `enc_editor/ui/theme.py` change.

## Update from GitHub

Open **Updates** in the top bar to check GitHub Releases, read the release notes
and download the Windows installer. Installed copies also check at startup by
default. Turn this off in the Updates window. Downloads can be cancelled and
are checked against the size and SHA-256 published by GitHub. **Install and
close** starts Setup after the editor exits and uses the existing installation
folder and scope. In the portable build or when running from source, the dialog
shows the path to the verified installer for manual use.

Pushing a version tag such as `v3.8.0` runs the Windows installer workflow. The
workflow tests the code, checks the tag against `enc_editor.VERSION`, builds
the installer and attaches it to a draft release. Publish the draft as a stable
release to make it available in the app. A manual workflow run produces a
build artifact for review.

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
- Some limits are other parameters rather than numbers, and the drive checks
  them at the moment of the write, not at the end of the batch. Writing
  `F01.01 = 90.00` is refused while the upper limit `F01.11` still reads
  `50.00`, even when the same batch raises that limit - the table would
  otherwise reach `F01.01` first, because it writes in address order. The
  editor reorders the batch instead: a bound that has to widen is written
  first, one that has to narrow last. A value no ordering can rescue - above a
  limit nothing in the batch moves - is reported before anything reaches the
  drive, naming the parameter and its current value.
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
