"""Inverter profiles, loaded from the ``profiles`` directory.

One directory per model::

    profiles/en600_v5/profile.json        manifest: identity, link, groups
                     /parameters.json     the function table
                     /translations/ru.json optional per-language catalogue

Adding a model means adding such a directory - no Python change.  The manifest
is validated on load, so a malformed table fails loudly at start-up instead of
misbehaving against a live drive.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, Mapping

from . import codecs, dependencies, diagnostics

PROFILES_DIRECTORY = Path(__file__).resolve().parent.parent / "profiles"
MANIFEST_NAME = "profile.json"

REQUIRED_PARAMETER_FIELDS = frozenset(
    {
        "code",
        "description",
        "range",
        "minimum",
        "maximum",
        "unit",
        "address",
        "group",
        "default",
        "scale",
        "encoding",
        "read_only",
    }
)

# Fields each encoding needs on top of the common ones.
ENCODING_FIELDS = {
    "bcd": ("digits", "digit_chars"),
    "hex": ("digits", "digit_chars"),
    "function_code": ("maximum_group",),
    "text": ("register_count",),
}

TRANSLATABLE_FIELDS = ("description", "range", "default_note", "help", "note")

# Russian manuals print decimal commas ("0,01 Гц") while the value column always
# uses a dot; normalise the catalogue so both read consistently.
DECIMAL_COMMA = re.compile(r"(?<=\d),(?=(?:\d{2,}|\d\s*(?:%|Гц|кГц|МПа|В|А|с|мин|ч|~|～)))")


class CatalogError(RuntimeError):
    """A profile directory is missing something or contradicts itself."""


@dataclass(frozen=True)
class LinkSettings:
    """Serial settings and Modbus limits of one model."""

    baudrate: int = 9600
    parity: str = "N"
    stopbits: int = 1
    bytesize: int = 8
    timeout: float = 1.0
    device_id: int = 1
    max_read_registers: int = 50
    index_register: int | None = None
    persist_coil: int | None = None
    protocol: str = "modbus_rtu"
    device_id_limit: int = 247

    @property
    def maximum_device_id(self) -> int:
        return 126 if self.protocol == "danfoss_fc" else self.device_id_limit

    @property
    def frame(self) -> str:
        """Short link description such as ``9600 8N1``."""
        return f"{self.baudrate} {self.bytesize}{self.parity}{self.stopbits}"


@dataclass(frozen=True)
class InverterProfile:
    key: str
    model: str
    series: str
    labels: Mapping[str, str]
    parameters: tuple[dict[str, Any], ...]
    link: LinkSettings = field(default_factory=LinkSettings)
    manual_url: str = ""
    group_ids: Mapping[str, int] = field(default_factory=dict)
    group_labels: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    translations: Mapping[str, Mapping[str, Mapping[str, str]]] = field(default_factory=dict)
    detect: Mapping[str, Any] | None = None
    order: int = 100
    directory: Path | None = None
    addressing: str = "group_byte"
    manufacturer: str = "ENC"
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    protocols: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    @property
    def supported_protocols(self) -> tuple[str, ...]:
        return tuple(self.protocols) or (self.link.protocol,)

    def link_for_protocol(self, protocol: str) -> LinkSettings:
        if protocol not in self.supported_protocols:
            raise ValueError(f"Unsupported protocol {protocol}")
        options = self.protocols.get(protocol, {})
        fields = {key: options[key] for key in ("baudrate", "parity", "stopbits", "bytesize", "timeout")
                  if key in options}
        return replace(self.link, protocol=protocol, **fields)

    # -- identity ------------------------------------------------------
    def label(self, language: str) -> str:
        return self.labels.get(language) or self.labels.get("en") or self.model

    @property
    def groups(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(parameter["group"] for parameter in self.parameters))

    def group_label(self, group: str, language: str) -> str:
        """Localized manual title for a parameter group, with English fallback."""
        return (
            self.group_labels.get(language, {}).get(group)
            or self.group_labels.get("en", {}).get(group)
            or group
        )

    def by_code(self) -> dict[str, dict[str, Any]]:
        return {parameter["code"]: parameter for parameter in self.parameters}

    # -- localized text ------------------------------------------------
    def text(self, parameter: Mapping[str, Any], field_name: str, language: str) -> str:
        """Manual text for ``field_name`` in ``language``, English otherwise."""
        if field_name in parameter.get("_variant_fields", ()) or f"{field_name}_{language}" in parameter.get("_variant_fields", ()):
            override = parameter.get(f"{field_name}_{language}") or parameter.get(field_name)
            if override:
                return override
        catalogue = self.translations.get(language)
        if catalogue:
            translated = catalogue.get(parameter["code"], {}).get(field_name)
            if translated:
                return translated
        return parameter.get(field_name, "")

    def range_text(self, parameter: Mapping[str, Any], language: str) -> str:
        """Localized range with every structured cross-reference made visible.

        Manuals often say only "upper limit frequency" or "same as above".
        The profile already knows the exact related function codes, so append
        them in a language-independent mathematical form instead of leaving the
        operator to guess which parameter controls the limit.
        """
        text = self.text(parameter, "range", language)
        references: list[str] = []
        if parameter.get("same_as"):
            references.append(f"= {parameter['same_as']}")
        if parameter.get("minimum_from"):
            references.append(f"≥ {parameter['minimum_from']}")
        if parameter.get("maximum_from"):
            factor = parameter.get("maximum_from_factor", 1)
            offset = parameter.get("maximum_from_offset", 0)
            bound = parameter["maximum_from"]
            if factor == -1 and offset:
                bound = f"{offset:g} - {bound}"
            references.append(f"≤ {bound}")
        if references:
            text = f"{text}  [{'; '.join(references)}]"
        return text

    def searchable(self, parameter: Mapping[str, Any]) -> str:
        """Everything a search query may match, in every loaded language."""
        parts = [parameter["code"], parameter["description"], parameter["range"]]
        parts.append(parameter.get("help", ""))
        parts.extend(parameter.get("aliases", ()))
        for catalogue in self.translations.values():
            translated = catalogue.get(parameter["code"], {})
            parts.extend(translated.get(name, "") for name in ("description", "range", "help"))
        return " ".join(parts).lower()

    @property
    def translated_languages(self) -> tuple[str, ...]:
        return tuple(self.translations)


class Catalog:
    """All profiles found on disk, in manifest order."""

    def __init__(self, profiles: list[InverterProfile]):
        self._profiles = {profile.key: profile for profile in profiles}

    def __iter__(self) -> Iterator[InverterProfile]:
        return iter(sorted(self._profiles.values(), key=lambda p: (p.order, p.key)))

    def __len__(self) -> int:
        return len(self._profiles)

    def __contains__(self, key: object) -> bool:
        return key in self._profiles

    def __getitem__(self, key: str) -> InverterProfile:
        return self.resolve(key)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(profile.key for profile in self)

    def resolve(self, key: str | None) -> InverterProfile:
        """Look up a profile by key."""
        if key in self._profiles:
            return self._profiles[key]
        raise KeyError(key)

    def get(self, key: str | None, default: InverterProfile | None = None):
        try:
            return self.resolve(key)
        except KeyError:
            return default

    @property
    def manufacturers(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(profile.manufacturer for profile in self))

    def labels(self, language: str, manufacturer: str | None = None) -> dict[str, str]:
        """Combobox contents: displayed label -> profile key."""
        return {
            profile.label(language): profile.key for profile in self
            if manufacturer is None or profile.manufacturer == manufacturer
        }


# ----------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------
def _read_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream)
    except OSError as exc:
        raise CatalogError(f"{path.name}: cannot be read ({exc})") from exc
    except ValueError as exc:
        raise CatalogError(f"{path.name}: invalid JSON ({exc})") from exc


def _split_code(code: str) -> tuple[str, int]:
    xinje = re.fullmatch(r"([PAU][0-9A-F])-(\d{2})", code)
    if xinje:
        return xinje[1], int(xinje[2])
    menu = re.fullmatch(r"([PVR])(\d+(?:\.\d+)*)\.(\d+)", code)
    if menu:
        group = "K3" if menu[1] in ("P", "R") and menu[2] == "3" else menu[1] + menu[2]
        return group, int(menu[3])
    match = re.fullmatch(r"(\d{1,2})-(\d{2})(?:\[(\d+)\])?", code)
    if match:
        return match[1], int(match[2])
    group, _, number = code.partition(".")
    if not number.isdigit():
        raise CatalogError(f"{code}: expected a code like F05.03")
    return group, int(number)


def _validate_parameters(
    key: str, parameters: list[dict[str, Any]], group_ids: Mapping[str, int],
    addressing: str = "group_byte",
) -> None:
    codes: set[str] = set()
    addresses: set[tuple[int, int | None]] = set()
    references: list[tuple[str, str, str]] = []
    for parameter in parameters:
        code = parameter.get("code", "?")
        missing = REQUIRED_PARAMETER_FIELDS - parameter.keys()
        if missing:
            raise CatalogError(f"{key}: {code} is missing {sorted(missing)}")
        if code in codes:
            raise CatalogError(f"{key}: duplicate parameter code {code}")
        codes.add(code)
        location = (parameter["address"], parameter.get("array_index"))
        if location in addresses:
            raise CatalogError(f"{key}: duplicate address for {code}")
        addresses.add(location)
        register_count = parameter.get("register_count", 1)
        if type(register_count) is not int or not 1 <= register_count <= 10:
            raise CatalogError(f"{key}: {code} invalid register_count")
        if not 0 <= parameter["address"] <= 65536 - register_count:
            raise CatalogError(f"{key}: {code} register address is out of range")
        data_bits = parameter.get("data_bits", 16 * register_count)
        if data_bits not in (8, 16, 32, 160) or data_bits > 16 * register_count:
            raise CatalogError(f"{key}: {code} invalid data_bits")
        array_index = parameter.get("array_index")
        if array_index is not None:
            match = re.fullmatch(r"\d{1,2}-\d{2}\[(\d+)\]", code)
            if type(array_index) is not int or not 0 <= array_index <= 65535 or not match or int(match[1]) != array_index:
                raise CatalogError(f"{key}: {code} invalid array_index")

        group, number = _split_code(code)
        if group != parameter["group"]:
            raise CatalogError(f"{key}: {code} declares group {parameter['group']!r}")
        if addressing == "parameter_id":
            identifier = parameter.get("parameter_id")
            if type(identifier) is not int or not 1 <= identifier <= 65535:
                raise CatalogError(f"{key}: {code} requires a valid parameter_id")
            if parameter["address"] != identifier - 1:
                raise CatalogError(f"{key}: {code} address must be parameter_id - 1")
        if group_ids:
            if group not in group_ids:
                raise CatalogError(f"{key}: {code} uses group {group} missing from the manifest")
            expected = (
                parameter["parameter_id"] - 1 if addressing == "parameter_id" else
                10 * (group_ids[group] * 100 + number) - 1
                if addressing == "danfoss_pnu"
                else (group_ids[group] << 8) | number
            )
            if addressing != "explicit" and parameter["address"] != expected:
                raise CatalogError(
                    f"{key}: {code} address 0x{parameter['address']:04X} "
                    f"does not match 0x{expected:04X}"
                )

        encoding = parameter["encoding"]
        if encoding in ("text", "version") and not parameter.get("read_only"):
            raise CatalogError(f"{key}: {code} text parameters must be read-only")
        if encoding not in codecs.CODECS:
            raise CatalogError(f"{key}: {code} uses unknown encoding {encoding!r}")
        for name in ENCODING_FIELDS.get(encoding, ()):
            if name not in parameter:
                raise CatalogError(f"{key}: {code} ({encoding}) is missing {name!r}")

        default = parameter["default"]
        if not isinstance(default, str):
            raise CatalogError(f"{key}: {code} default must be a string")
        if default and encoding == "numeric":
            try:
                float(default)
            except ValueError:
                raise CatalogError(
                    f"{key}: {code} has a non-numeric default {default!r}"
                ) from None
        note = parameter.get("default_note")
        if note is not None and not isinstance(note, str):
            raise CatalogError(f"{key}: {code} default_note must be a string")

        provider = parameter.get("scale_from")
        if provider is not None:
            scales = parameter.get("scale_values")
            maximum_raw = parameter.get("maximum_raw")
            if (not isinstance(provider, str) or provider == code or encoding != "numeric"
                    or parameter.get("minimum", 0) < 0 or parameter.get("signed")
                    or not isinstance(scales, dict) or not scales
                    or type(maximum_raw) is not int or not 0 < maximum_raw <= codecs.raw_maximum(parameter)):
                raise CatalogError(f"{key}: {code} invalid scale_from definition")
            for selector, scale in scales.items():
                if (not isinstance(selector, str) or not selector.isdigit()
                        or str(int(selector)) != selector or type(scale) is not int
                        or scale not in (1, 10, 100, 1000, 10000)):
                    raise CatalogError(f"{key}: {code} invalid scale_values")
            if parameter["maximum"] * parameter["scale"] != maximum_raw:
                raise CatalogError(f"{key}: {code} maximum disagrees with maximum_raw")
            minimum_raw = parameter.get("minimum_raw", 0)
            if type(minimum_raw) is not int or not 0 <= minimum_raw <= maximum_raw or parameter["minimum"] * parameter["scale"] != minimum_raw:
                raise CatalogError(f"{key}: {code} invalid minimum_raw")
            references.append((code, "scale_from", provider))

        for context_field, mapping_field in (("unit_from", "unit_values"), ("variants_from", "variants")):
            provider = parameter.get(context_field)
            if provider is None:
                continue
            if not isinstance(provider, str) or provider == code:
                raise CatalogError(f"{key}: {code} invalid {context_field}")
            references.append((code, context_field, provider))
            entries = parameter.get(mapping_field)
            if context_field == "unit_from":
                if not isinstance(entries, dict) or not entries or any(
                    not isinstance(k, str) or not k.isdigit() or not isinstance(v, str) or not v
                    for k, v in entries.items()):
                    raise CatalogError(f"{key}: {code} invalid {mapping_field}")
            else:
                if not isinstance(entries, list) or not entries:
                    raise CatalogError(f"{key}: {code} invalid variants")
                previous_maximum = -1
                if parameter.get("variants_decoder") not in (None, "version"):
                    raise CatalogError(f"{key}: {code} unknown variants decoder")
                allowed_fields = {"description", "description_ru", "range", "range_ru", "note", "note_ru",
                                  "minimum", "maximum", "scale", "unit", "encoding", "default", "default_note",
                                  "allowed_values", "maximum_from", "minimum_from", "signed", "digits", "digit_chars",
                                  "digit_limits", "digit_minimums"}
                for variant in entries:
                    if not isinstance(variant, dict):
                        raise CatalogError(f"{key}: {code} invalid variant entry")
                    lo, hi = variant.get("minimum"), variant.get("maximum", 65535)
                    if type(lo) is not int or type(hi) is not int or not previous_maximum < lo <= hi <= 65535:
                        raise CatalogError(f"{key}: {code} overlapping/invalid variants")
                    previous_maximum = hi
                    fields = variant.get("fields", {})
                    if not isinstance(fields, dict) or set(fields) - allowed_fields:
                        raise CatalogError(f"{key}: {code} invalid variant fields")
                    if not variant.get("unsupported"):
                        definition = dict(parameter, **fields)
                        for bound_field in dependencies.BOUND_FIELDS:
                            if definition.get(bound_field):
                                references.append((code, bound_field, definition[bound_field]))
                        if definition["encoding"] not in codecs.CODECS or definition["scale"] not in (1, 10, 100, 1000, 10000):
                            raise CatalogError(f"{key}: {code} invalid variant encoding/scale")
                        bits = parameter.get("data_bits", 16 * parameter.get("register_count", 1))
                        raw_lower = -(1 << (bits - 1)) if definition.get("signed") else 0
                        raw_upper = (1 << (bits - int(bool(definition.get("signed"))))) - 1
                        if definition["minimum"] * definition["scale"] < raw_lower or definition["maximum"] * definition["scale"] > raw_upper:
                            raise CatalogError(f"{key}: {code} variant exceeds register storage")
        guards = parameter.get("write_guards", [])
        if not isinstance(guards, list):
            raise CatalogError(f"{key}: {code} write_guards must be a list")
        for guard in guards:
            if not isinstance(guard, dict):
                raise CatalogError(f"{key}: {code} invalid write guard")
            provider = guard.get("code")
            if not isinstance(provider, str) or provider == code or not guard.get("allowed_values"):
                raise CatalogError(f"{key}: {code} invalid write guard")
            if not isinstance(guard["allowed_values"], list) or any(type(v) is not int or not 0 <= v <= 65535 for v in guard["allowed_values"]):
                raise CatalogError(f"{key}: {code} invalid guard values")
            references.append((code, "write_guards", provider))

        # Existing ENC maps use one register; other drives may use two.
        if not parameter.get("read_only"):
            raw_maximum = Decimal(str(parameter["maximum"])) * Decimal(str(parameter["scale"]))
            limit = (1 << (data_bits - int(bool(parameter.get("signed"))))) - 1
            raw_minimum = Decimal(str(parameter["minimum"])) * Decimal(str(parameter["scale"]))
            lower = -(1 << (data_bits - 1)) if parameter.get("signed") else 0
            if raw_maximum > limit or raw_minimum < lower:
                raise CatalogError(
                    f"{key}: {code} maximum {parameter['maximum']} does not fit "
                    f"its {data_bits}-bit storage"
                )

        # A bound taken from another parameter has to name a code this profile
        # actually has, or the write ordering would silently do nothing.
        for field_name in dependencies.BOUND_FIELDS:
            reference = parameter.get(field_name)
            if reference is None:
                continue
            if not isinstance(reference, str):
                raise CatalogError(f"{key}: {code} {field_name} must be a parameter code")
            if reference == code:
                raise CatalogError(f"{key}: {code} {field_name} points at itself")
            references.append((code, field_name, reference))
            for suffix in ("_factor", "_offset"):
                value = parameter.get(field_name + suffix, 1 if suffix == "_factor" else 0)
                if type(value) not in (int, float) or not Decimal(str(value)).is_finite():
                    raise CatalogError(f"{key}: {code} invalid bound transformation")

        same_as = parameter.get("same_as")
        if same_as is not None:
            if not isinstance(same_as, str):
                raise CatalogError(f"{key}: {code} same_as must be a parameter code")
            if same_as == code:
                raise CatalogError(f"{key}: {code} same_as points at itself")
            references.append((code, "same_as", same_as))

        digit_limits = parameter.get("digit_limits")
        if digit_limits is not None:
            if not isinstance(digit_limits, str) or not digit_limits:
                raise CatalogError(f"{key}: {code} digit_limits must be a non-empty string")
            if parameter.get("digits") and len(digit_limits) != parameter["digits"]:
                raise CatalogError(
                    f"{key}: {code} digit_limits {digit_limits!r} does not match "
                    f"{parameter['digits']} digits"
                )
        minimums = parameter.get("digit_minimums")
        if minimums is not None:
            if (not isinstance(minimums, str) or not digit_limits or len(minimums) != len(digit_limits)
                    or any(c not in "0123456789ABCDEF*" for c in minimums)):
                raise CatalogError(f"{key}: {code} invalid digit_minimums")
            if any(lo != "*" and hi != "*" and int(lo, 16) > int(hi, 16) for lo, hi in zip(minimums, digit_limits)):
                raise CatalogError(f"{key}: {code} digit minimum exceeds maximum")
        preserve_mask = parameter.get("preserve_mask")
        if preserve_mask is not None and (type(preserve_mask) is not int or not 0 < preserve_mask <= codecs.raw_maximum(parameter)):
            raise CatalogError(f"{key}: {code} invalid preserve_mask")
        if "verify_current" in parameter and type(parameter["verify_current"]) is not bool:
            raise CatalogError(f"{key}: {code} verify_current must be a boolean")

    # Checked once every code is known, so a bound may point forwards.
    for code, field_name, reference in references:
        if reference not in codes:
            raise CatalogError(
                f"{key}: {code} {field_name} points at unknown code {reference}"
            )

    by_code = {parameter["code"]: parameter for parameter in parameters}
    for code, field_name, reference in references:
        if field_name in ("unit_from", "variants_from", "write_guards"):
            source = by_code[reference]
            if source["encoding"] not in ("numeric", "version") or source["scale"] != 1 or codecs.context_codes(source):
                raise CatalogError(f"{key}: {code} context provider must be an unscaled, independent selector")
        if field_name == "unit_from":
            choices = set(by_code[reference].get("allowed_values", ()))
            if choices and choices != {int(v) for v in by_code[code]["unit_values"]}:
                raise CatalogError(f"{key}: {code} unit_values do not cover selector choices")
        if field_name == "scale_from":
            source = by_code[reference]
            if source.get("scale_from") or source["encoding"] != "numeric" or source["scale"] != 1:
                raise CatalogError(f"{key}: {code} scale_from must name an unscaled numeric selector")
            choices = set(source.get("allowed_values", ()))
            if choices and choices != {int(value) for value in by_code[code]["scale_values"]}:
                raise CatalogError(f"{key}: {code} scale_values do not cover selector choices")
        if field_name != "same_as":
            continue
        parameter = by_code[code]
        source = by_code[reference]
        for inherited in ("minimum", "maximum", "scale", "encoding"):
            if parameter[inherited] != source[inherited]:
                raise CatalogError(
                    f"{key}: {code} {inherited} does not match same_as {reference}"
                )


def _load_translations(
    key: str, directory: Path, declared: Mapping[str, str], codes: set[str]
) -> dict[str, dict[str, dict[str, str]]]:
    catalogues: dict[str, dict[str, dict[str, str]]] = {}
    for language, relative in declared.items():
        payload = _read_json(directory / relative)
        entries = payload.get("parameters")
        if not isinstance(entries, dict):
            raise CatalogError(f"{key}/{relative}: missing the parameter map")
        missing = codes - entries.keys()
        if missing:
            raise CatalogError(
                f"{key}/{relative}: no {language} translation for "
                f"{len(missing)} codes (first: {sorted(missing)[0]})"
            )
        catalogues[language] = {
            code: {
                name: DECIMAL_COMMA.sub(".", entry[name]) if name == "range" else entry[name]
                for name in TRANSLATABLE_FIELDS
                if isinstance(entry.get(name), str) and entry[name]
            }
            for code, entry in entries.items()
            if code in codes
        }
    return catalogues


def load_profile(directory: Path, shared: Mapping[str, InverterProfile] | None = None) -> InverterProfile:
    """Load one profile directory."""
    manifest = _read_json(directory / MANIFEST_NAME)
    manufacturer = manifest.get("manufacturer", "ENC")
    if not isinstance(manufacturer, str) or not manufacturer.strip():
        raise CatalogError(f"{directory.name}: manufacturer must be a non-empty string")
    addressing = manifest.get("addressing", "group_byte")
    if addressing not in ("group_byte", "danfoss_pnu", "parameter_id", "explicit"):
        raise CatalogError(f"{directory.name}: unknown addressing {addressing!r}")
    key = manifest.get("key") or directory.name
    labels = manifest.get("label") or {"en": manifest.get("model", key)}
    if isinstance(labels, str):
        labels = {"en": labels}

    borrowed = manifest.get("parameters_from")
    if borrowed:
        source = (shared or {}).get(borrowed)
        if source is None:
            raise CatalogError(f"{key}: parameters_from refers to unknown profile {borrowed!r}")
        parameters = source.parameters
        translations = source.translations
        group_ids = source.group_ids
        group_labels = source.group_labels
    else:
        parameters = _read_json(directory / manifest.get("parameters", "parameters.json"))
        if not isinstance(parameters, list) or not parameters:
            raise CatalogError(f"{key}: the parameter table must be a non-empty list")
        group_ids = manifest.get("groups") or {}
        _validate_parameters(key, parameters, group_ids, addressing)
        group_labels = manifest.get("group_labels") or {}
        if not isinstance(group_labels, dict):
            raise CatalogError(f"{key}: group_labels must be a language map")
        for language, labels_by_group in group_labels.items():
            if not isinstance(language, str) or not isinstance(labels_by_group, dict):
                raise CatalogError(f"{key}: invalid group_labels entry for {language!r}")
            unknown = labels_by_group.keys() - group_ids.keys()
            if unknown:
                raise CatalogError(
                    f"{key}: group_labels contains unknown group {sorted(unknown)[0]!r}"
                )
            if any(
                not isinstance(title, str) or not title.strip()
                for title in labels_by_group.values()
            ):
                raise CatalogError(f"{key}: group labels must be non-empty strings")
        codes = {parameter["code"] for parameter in parameters}
        translations = _load_translations(key, directory, manifest.get("translations", {}), codes)
        parameters = tuple(parameters)

    diagnostic_data = {}
    if manifest.get("diagnostics"):
        diagnostic_data = _read_json(directory / manifest["diagnostics"])
        try:
            diagnostics.validate(diagnostic_data, {p["code"]: p for p in parameters})
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise CatalogError(f"{key}: invalid diagnostics: {exc}") from exc

    protocols = manifest.get("protocols", {})
    if not isinstance(protocols, dict) or any(
        name not in ("modbus_rtu", "danfoss_fc") or not isinstance(options, dict)
        for name, options in protocols.items()
    ):
        raise CatalogError(f"{key}: invalid protocol definitions")
    if ("danfoss_fc" in protocols or manifest.get("link", {}).get("protocol") == "danfoss_fc") and addressing != "danfoss_pnu":
        raise CatalogError(f"{key}: FC requires Danfoss PNU addressing")
    for options in protocols.values():
        rates = options.get("baudrates")
        if rates is not None and (not isinstance(rates, list) or not rates or any(type(rate) is not int or not 300 <= rate <= 4_000_000 for rate in rates)):
            raise CatalogError(f"{key}: invalid baudrate list")

    profile = InverterProfile(
        key=key,
        model=manifest.get("model", key),
        series=manifest.get("series", ""),
        labels=labels,
        parameters=tuple(parameters),
        link=LinkSettings(**manifest.get("link", {})),
        manual_url=manifest.get("manual_url", ""),
        group_ids=group_ids,
        group_labels=group_labels,
        translations=translations,
        detect=manifest.get("detect"),
        order=manifest.get("order", 100),
        directory=directory,
        addressing=addressing,
        manufacturer=manufacturer.strip(),
        diagnostics=diagnostic_data,
        protocols=protocols,
    )
    from .connection import settings_for
    try:
        for protocol in profile.supported_protocols:
            settings_for(profile, {"protocol": protocol})
        settings_for(profile)
    except (ValueError, TypeError) as exc:
        raise CatalogError(f"{key}: invalid connection settings: {exc}") from exc
    return profile


def load_catalog(root: Path | None = None) -> Catalog:
    """Load every profile directory under ``root`` (default: ``profiles``)."""
    root = Path(root or PROFILES_DIRECTORY)
    directories = sorted(
        path.parent for path in root.glob(f"*/{MANIFEST_NAME}")
    )
    if not directories:
        raise CatalogError(f"{root}: no inverter profiles found")

    loaded: dict[str, InverterProfile] = {}
    deferred: list[Path] = []
    for directory in directories:
        manifest = _read_json(directory / MANIFEST_NAME)
        if manifest.get("parameters_from"):
            deferred.append(directory)
            continue
        profile = load_profile(directory)
        loaded[profile.key] = profile
    for directory in deferred:
        profile = load_profile(directory, loaded)
        loaded[profile.key] = profile

    for profile in loaded.values():
        detect = profile.detect or {}
        for target in _detect_targets(detect):
            if target not in loaded:
                raise CatalogError(f"{profile.key}: detection points at unknown profile {target!r}")
    return Catalog(list(loaded.values()))


def _detect_targets(detect: Mapping[str, Any]) -> list[str]:
    targets = [rule.get("profile") for rule in detect.get("rules", [])]
    if detect.get("fallback"):
        targets.append(detect["fallback"])
    return [target for target in targets if target]
