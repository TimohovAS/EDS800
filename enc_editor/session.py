"""Editing state of one inverter: what was read, what the user changed.

This is the layer the UI drives.  It holds no widgets and no serial code, so
the table rules (filtering, which cells are dirty, what may be written) can be
tested without a drive and without Tk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from . import codecs
from .catalog import Catalog, InverterProfile
from .codecs import ERROR_TEXTS, READ_ERROR, CodecError, Problem

ALL_GROUPS = "__all__"
FILTERS = ("all", "writable", "readonly", "edited", "errors")
SETTINGS_FORMAT_VERSION = 3


@dataclass(frozen=True)
class WriteTarget:
    """One register that is ready to be written."""

    parameter: Mapping[str, Any]
    raw_value: int
    displayed: str

    @property
    def code(self) -> str:
        return self.parameter["code"]

    def as_tuple(self) -> tuple[Mapping[str, Any], int, str]:
        return (self.parameter, self.raw_value, self.displayed)


@dataclass(frozen=True)
class LoadedSettings:
    """Result of reading a settings file."""

    profile: InverterProfile
    values: dict[str, int]
    failed: set[str]
    device_id: int | None = None
    skipped: int = 0


@dataclass
class Session:
    """Values read from the drive plus the edits made in the table."""

    profile: InverterProfile
    loaded: dict[str, int] = field(default_factory=dict)
    edited: dict[str, str] = field(default_factory=dict)
    failed: set[str] = field(default_factory=set)

    # -- profile ---------------------------------------------------------
    def use_profile(self, profile: InverterProfile, preserve_values: bool = False) -> None:
        """Switch parameter maps, dropping values the new map does not know."""
        self.profile = profile
        if not preserve_values:
            self.loaded.clear()
            self.edited.clear()
            self.failed.clear()
            return
        known = {parameter["code"] for parameter in profile.parameters}
        self.loaded = {code: value for code, value in self.loaded.items() if code in known}
        self.edited = {code: value for code, value in self.edited.items() if code in known}
        self.failed &= known

    # -- table content ----------------------------------------------------
    def group_parameters(self, group: str) -> list[dict[str, Any]]:
        if group == ALL_GROUPS:
            return list(self.profile.parameters)
        return [p for p in self.profile.parameters if p["group"] == group]

    def visible_parameters(
        self, group: str = ALL_GROUPS, query: str = "", row_filter: str = "all"
    ) -> list[dict[str, Any]]:
        """Parameters left after the group, filter and search selection."""
        query = query.strip().lower()
        rows = []
        for parameter in self.group_parameters(group):
            code = parameter["code"]
            if row_filter == "writable" and parameter.get("read_only"):
                continue
            if row_filter == "readonly" and not parameter.get("read_only"):
                continue
            if row_filter == "edited" and code not in self.edited:
                continue
            if row_filter == "errors" and code not in self.failed:
                continue
            if query and query not in self.profile.searchable(parameter):
                continue
            rows.append(parameter)
        return rows

    def baseline(self, parameter: Mapping[str, Any]) -> str:
        """What the cell shows without user edits."""
        code = parameter["code"]
        if code in self.failed:
            return READ_ERROR
        if code not in self.loaded:
            return ""
        return codecs.format_value(self.loaded[code], parameter)

    def display(self, parameter: Mapping[str, Any]) -> str:
        return self.edited.get(parameter["code"], self.baseline(parameter))

    def track_edits(self, parameters: Sequence[Mapping[str, Any]], values: Sequence[str]) -> None:
        """Compare the table against the baseline and remember the differences."""
        for parameter, value in zip(parameters, values):
            code = parameter["code"]
            text = str(value).strip()
            if text == self.baseline(parameter):
                self.edited.pop(code, None)
            else:
                self.edited[code] = text

    # -- results ----------------------------------------------------------
    def apply_read(self, values: Mapping[str, Any]) -> int:
        """Store a batch of read values; returns how many succeeded."""
        for code, value in values.items():
            if value == READ_ERROR:
                self.failed.add(code)
                self.loaded.pop(code, None)
            else:
                self.failed.discard(code)
                self.loaded[code] = value
            self.edited.pop(code, None)
        return sum(1 for value in values.values() if value != READ_ERROR)

    def apply_write(self, written: Mapping[str, int]) -> None:
        for code, raw_value in written.items():
            self.loaded[code] = raw_value
            self.edited.pop(code, None)
            self.failed.discard(code)

    # -- writing ----------------------------------------------------------
    def collect_write_targets(
        self, parameters: Iterable[Mapping[str, Any]], edited_only: bool = False
    ) -> tuple[list[WriteTarget], list[tuple[str, Problem]]]:
        """Pair writable parameters with the value currently shown."""
        targets: list[WriteTarget] = []
        problems: list[tuple[str, Problem]] = []
        for parameter in parameters:
            if parameter.get("read_only"):
                continue
            code = parameter["code"]
            if edited_only and code not in self.edited:
                continue
            # Action parameters (reset, upload/download) must never be replayed
            # from a value that was merely read back.
            if parameter.get("write_only_if_edited") and code not in self.edited:
                continue
            if code in self.edited:
                displayed = self.edited[code]
            elif code in self.loaded:
                displayed = codecs.format_value(self.loaded[code], parameter)
            else:
                continue
            displayed = str(displayed).strip()
            if not displayed or displayed in ERROR_TEXTS:
                continue
            problem = codecs.validate_value(parameter, displayed)
            if problem is not None:
                problems.append((code, problem))
                continue
            try:
                targets.append(WriteTarget(parameter, codecs.encode_value(parameter, displayed), displayed))
            except CodecError as exc:
                problems.append((code, exc.problem))
        return targets, problems

    def validate(self, parameter: Mapping[str, Any], text: str) -> Problem | None:
        return codecs.validate_value(parameter, text)

    # -- settings files ---------------------------------------------------
    def settings_payload(self, values: Mapping[str, Any], device_id: int) -> dict[str, Any]:
        return {
            "format_version": SETTINGS_FORMAT_VERSION,
            "profile": self.profile.key,
            "model": self.profile.model,
            "device_id": int(device_id),
            "settings": dict(values),
        }


def parse_settings_file(payload: Any, catalog: Catalog) -> LoadedSettings:
    """Validate a settings file and map it onto a known profile."""
    if not isinstance(payload, dict) or "settings" not in payload:
        raise ValueError("not-a-settings-file")

    version = payload.get("format_version")
    if version != SETTINGS_FORMAT_VERSION:
        raise ValueError(f"unsupported-version:{version}")

    settings = payload["settings"]
    device_id = payload.get("device_id")
    try:
        profile = catalog.resolve(payload.get("profile"))
    except KeyError:
        raise ValueError(f"unknown-profile:{payload.get('profile')}") from None
    if not isinstance(settings, dict):
        raise ValueError("not-a-settings-file")

    known = {parameter["code"] for parameter in profile.parameters}
    values: dict[str, int] = {}
    failed: set[str] = set()
    skipped = 0
    for code, value in settings.items():
        if code not in known:
            skipped += 1
            continue
        if value == READ_ERROR:
            failed.add(code)
            continue
        raw_value = int(value)
        if not 0 <= raw_value <= 0xFFFF:
            raise ValueError(f"out-of-range:{code}")
        values[code] = raw_value

    if device_id is not None:
        device_id = int(device_id)
        if not 1 <= device_id <= 247:
            device_id = None
    return LoadedSettings(profile, values, failed, device_id, skipped)
