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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

from . import codecs, dependencies

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
}

TRANSLATABLE_FIELDS = ("description", "range", "default_note", "note")

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
        catalogue = self.translations.get(language)
        if catalogue:
            translated = catalogue.get(parameter["code"], {}).get(field_name)
            if translated:
                return translated
        return parameter.get(field_name, "")

    def searchable(self, parameter: Mapping[str, Any]) -> str:
        """Everything a search query may match, in every loaded language."""
        parts = [parameter["code"], parameter["description"], parameter["range"]]
        for catalogue in self.translations.values():
            translated = catalogue.get(parameter["code"], {})
            parts.extend(translated.get(name, "") for name in ("description", "range"))
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

    def labels(self, language: str) -> dict[str, str]:
        """Combobox contents: displayed label -> profile key."""
        return {profile.label(language): profile.key for profile in self}


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
    group, _, number = code.partition(".")
    if not number.isdigit():
        raise CatalogError(f"{code}: expected a code like F05.03")
    return group, int(number)


def _validate_parameters(
    key: str, parameters: list[dict[str, Any]], group_ids: Mapping[str, int]
) -> None:
    codes: set[str] = set()
    addresses: set[int] = set()
    references: list[tuple[str, str, str]] = []
    for parameter in parameters:
        code = parameter.get("code", "?")
        missing = REQUIRED_PARAMETER_FIELDS - parameter.keys()
        if missing:
            raise CatalogError(f"{key}: {code} is missing {sorted(missing)}")
        if code in codes:
            raise CatalogError(f"{key}: duplicate parameter code {code}")
        codes.add(code)
        if parameter["address"] in addresses:
            raise CatalogError(f"{key}: duplicate address for {code}")
        addresses.add(parameter["address"])

        group, number = _split_code(code)
        if group != parameter["group"]:
            raise CatalogError(f"{key}: {code} declares group {parameter['group']!r}")
        if group_ids:
            if group not in group_ids:
                raise CatalogError(f"{key}: {code} uses group {group} missing from the manifest")
            expected = (group_ids[group] << 8) | number
            if parameter["address"] != expected:
                raise CatalogError(
                    f"{key}: {code} address 0x{parameter['address']:04X} "
                    f"does not match 0x{expected:04X}"
                )

        encoding = parameter["encoding"]
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

        # A writable parameter is one 16-bit register; a wider documented
        # maximum means the row was transcribed as the wrong kind of field.
        if not parameter.get("read_only"):
            raw_maximum = parameter["maximum"] * parameter["scale"]
            if raw_maximum > 0xFFFF:
                raise CatalogError(
                    f"{key}: {code} maximum {parameter['maximum']} does not fit "
                    f"a 16-bit register"
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

        digit_limits = parameter.get("digit_limits")
        if digit_limits is not None:
            if not isinstance(digit_limits, str) or not digit_limits:
                raise CatalogError(f"{key}: {code} digit_limits must be a non-empty string")
            if parameter.get("digits") and len(digit_limits) != parameter["digits"]:
                raise CatalogError(
                    f"{key}: {code} digit_limits {digit_limits!r} does not match "
                    f"{parameter['digits']} digits"
                )

    # Checked once every code is known, so a bound may point forwards.
    for code, field_name, reference in references:
        if reference not in codes:
            raise CatalogError(
                f"{key}: {code} {field_name} points at unknown code {reference}"
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
        _validate_parameters(key, parameters, group_ids)
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

    return InverterProfile(
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
    )


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
