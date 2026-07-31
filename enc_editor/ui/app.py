"""The editor window.

This module owns widgets and nothing else: parameter maps come from
:mod:`enc_editor.catalog`, value conversion from :mod:`enc_editor.codecs`,
serial traffic from :mod:`enc_editor.transport`, and the editing state from
:mod:`enc_editor.session`.
"""

from __future__ import annotations

import json
import logging
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import serial.tools.list_ports
import tksheet
from pymodbus.exceptions import ModbusException

from .. import VERSION, detection
from ..catalog import Catalog, CatalogError, load_catalog
from ..codecs import Problem
from ..i18n import LANGUAGES, Translator
from ..session import ALL_GROUPS, FILTERS, Session, parse_settings_file
from ..transport import LinkError, ModbusLink, TaskCancelled
from .theme import FONT, SMALL_FONT, THEMES, apply_theme, sheet_options

logger = logging.getLogger(__name__)

PREFERENCES_PATH = Path.home() / ".enc_inverter_editor.json"
COLUMN_KEYS = (
    "column.code",
    "column.parameter",
    "column.value",
    "column.unit",
    "column.default",
    "column.range",
)


class InverterParameterEditor:
    """Tk front end for one inverter at a time."""

    VERSION = VERSION
    COLUMN_WIDTHS = (80, 350, 100, 70, 125, 340)
    VALUE_COLUMN = 2
    DEFAULT_COLUMN = 4

    def __init__(self, root, catalog: Catalog | None = None):
        self.root = root
        self.preferences = self._load_preferences()
        self.t = Translator(self.preferences.get("language"))
        self.palette = THEMES.get(self.preferences.get("theme", "light"), THEMES["light"])
        self.style = ttk.Style(root)

        self.catalog = catalog or load_catalog()
        stored_profile = self.preferences.get("profile")
        profile = self.catalog.get(stored_profile)
        # A profile that disappeared (renamed, removed) must not silently turn
        # into a different inverter model.
        self._missing_profile = stored_profile if profile is None and stored_profile else None
        profile = profile or next(iter(self.catalog))
        self.session = Session(profile)

        # Tk variables
        self.selected_profile_label = tk.StringVar(value=profile.label(self.t.language))
        self.selected_port = tk.StringVar()
        self.selected_device_id = tk.IntVar(value=profile.link.device_id)
        self.selected_group = tk.StringVar(value=ALL_GROUPS)
        self.search_text = tk.StringVar()
        self.row_filter = tk.StringVar(value=self.t(f"filter.{FILTERS[0]}"))
        self.status_text = tk.StringVar(value=self.t("status.ready"))
        self.link_text = tk.StringVar(value=self.t("link.idle"))
        self.counts_text = tk.StringVar(value="")

        # State
        self.rows: list[dict] = []
        self.data: list[list] = []
        self._connection: dict = {}
        self._busy = False
        self._cancel = threading.Event()
        self._readonly_rows: list[int] = []
        self._task_title = ""
        self._search_job = None
        self._action_widgets: list[ttk.Widget] = []
        self._status = ("status.ready", "info", {})
        self._language_buttons: dict[str, ttk.Button] = {}
        self._filter_keys: dict[str, str] = {}
        self._profile_keys: dict[str, str] = {}
        self.text_buttons: dict[str, ttk.Button] = {}

        self._build_ui()
        self.apply_theme()
        self._apply_language()
        self.refresh_ports(announce=False)
        self._restore_connection_preferences()
        self._populate_groups()
        self.update_table()
        self._update_titles()
        if self._missing_profile:
            self._set_status(
                "status.profile_missing",
                "warning",
                profile=self._missing_profile,
                model=self.profile.model,
            )
            logger.warning(
                "Stored profile %s is unknown; using %s",
                self._missing_profile,
                self.profile.key,
            )

        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # Shorthand
    # ------------------------------------------------------------------
    @property
    def profile(self):
        return self.session.profile

    @property
    def language(self) -> str:
        return self.t.language

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.root.title(f"{self.t('app.name')} {self.VERSION}")
        self.root.geometry(self.preferences.get("geometry", "1340x820"))
        self.root.minsize(1180, 620)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        self._build_header()

        body = ttk.Frame(self.root, style="App.TFrame")
        body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(12, 8))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        self._build_sidebar(body)
        self._build_workspace(body)
        self._build_statusbar()
        self._bind_shortcuts()

    def _build_header(self):
        header = ttk.Frame(self.root, style="Brand.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        title_box = ttk.Frame(header, style="Brand.TFrame")
        title_box.grid(row=0, column=0, sticky="w", padx=18, pady=14)
        ttk.Label(title_box, text=self.t("app.name"), style="BrandTitle.TLabel").pack(anchor="w")
        self.header_subtitle = ttk.Label(title_box, text="", style="BrandSub.TLabel")
        self.header_subtitle.pack(anchor="w", pady=(2, 0))

        actions = ttk.Frame(header, style="Brand.TFrame")
        actions.grid(row=0, column=2, sticky="e", padx=18)

        languages = ttk.Frame(actions, style="Brand.TFrame")
        languages.pack(side="left", padx=(0, 14))
        for code, short, _name in LANGUAGES:
            button = ttk.Button(
                languages,
                text=short,
                width=4,
                style="Brand.TButton",
                command=lambda code=code: self.set_language(code),
            )
            button.pack(side="left", padx=(0, 2))
            self._language_buttons[code] = button

        self.manual_button = ttk.Button(
            actions, text="", style="Brand.TButton", command=self.open_manual
        )
        self.manual_button.pack(side="left", padx=(0, 8))
        self.theme_button = ttk.Button(
            actions, text="", style="Brand.TButton", command=self.toggle_theme
        )
        self.theme_button.pack(side="left")

    def _build_sidebar(self, parent):
        sidebar = ttk.Frame(parent, style="App.TFrame", width=360)
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(2, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        # --- connection ----------------------------------------------------
        card = ttk.Frame(sidebar, style="Card.TFrame", padding=(14, 12, 14, 14))
        card.grid(row=0, column=0, sticky="ew")
        card.grid_columnconfigure(0, weight=1)

        self.connection_label = ttk.Label(card, text="", style="Section.TLabel")
        self.connection_label.grid(row=0, column=0, columnspan=2, sticky="w")

        self.model_label = ttk.Label(card, text="", style="Field.TLabel")
        self.model_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 3))
        self.profile_combobox = ttk.Combobox(
            card, textvariable=self.selected_profile_label, state="readonly"
        )
        self.profile_combobox.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.profile_combobox.bind("<<ComboboxSelected>>", self.change_profile)

        self.port_label = ttk.Label(card, text="", style="Field.TLabel")
        self.port_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(12, 3))
        self.port_combobox = ttk.Combobox(card, textvariable=self.selected_port, state="readonly")
        self.port_combobox.grid(row=4, column=0, sticky="ew")
        refresh = ttk.Button(card, text="↻", style="Icon.TButton", width=3, command=self.refresh_ports)
        refresh.grid(row=4, column=1, sticky="e", padx=(6, 0))

        self.device_id_label = ttk.Label(card, text="", style="Field.TLabel")
        self.device_id_label.grid(row=5, column=0, sticky="w", pady=(12, 3))
        id_row = ttk.Frame(card, style="Card.TFrame")
        id_row.grid(row=6, column=0, columnspan=2, sticky="ew")
        self.device_id_spinbox = ttk.Spinbox(
            id_row, from_=1, to=247, width=6, textvariable=self.selected_device_id
        )
        self.device_id_spinbox.pack(side="left")
        self.link_settings_label = ttk.Label(id_row, text="", style="Mono.TLabel")
        self.link_settings_label.pack(side="left", padx=(10, 0))

        self.test_button = ttk.Button(card, text="", command=self.test_connection)
        self.test_button.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        self._action_widgets.append(self.test_button)

        # --- settings file --------------------------------------------------
        files = ttk.Frame(sidebar, style="Card.TFrame", padding=(14, 12, 14, 14))
        files.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        files.grid_columnconfigure(0, weight=1, uniform="file")
        files.grid_columnconfigure(1, weight=1, uniform="file")

        self.files_label = ttk.Label(files, text="", style="Section.TLabel")
        self.files_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        for column, (key, command) in enumerate(
            (("action.load", self.load_from_file), ("action.save", self.save_to_file))
        ):
            button = ttk.Button(files, text="", command=command)
            button.grid(row=1, column=column, sticky="ew", padx=(0, 6) if column == 0 else (6, 0))
            self._action_widgets.append(button)
            self.text_buttons[key] = button

        # --- groups ----------------------------------------------------------
        groups = ttk.Frame(sidebar, style="Card.TFrame", padding=(14, 12, 8, 12))
        groups.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        groups.grid_rowconfigure(1, weight=1)
        groups.grid_columnconfigure(0, weight=1)

        self.groups_label = ttk.Label(groups, text="", style="Section.TLabel")
        self.groups_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.group_tree = ttk.Treeview(
            groups, style="Groups.Treeview", show="tree", columns=("count",), selectmode="browse"
        )
        self.group_tree.column("#0", width=244, stretch=True)
        self.group_tree.column("count", width=46, anchor="e", stretch=False)
        self.group_tree.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(groups, orient="vertical", command=self.group_tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns", padx=(4, 0))
        self.group_tree.configure(yscrollcommand=scrollbar.set)
        self.group_tree.bind("<<TreeviewSelect>>", self._on_group_selected)

    def _build_workspace(self, parent):
        workspace = ttk.Frame(parent, style="App.TFrame")
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.grid_rowconfigure(1, weight=1)
        workspace.grid_columnconfigure(0, weight=1)

        toolbar = ttk.Frame(workspace, style="Toolbar.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        toolbar.grid_columnconfigure(2, weight=1)

        self.search_entry = ttk.Entry(
            toolbar, textvariable=self.search_text, style="Search.TEntry", width=26
        )
        self.search_entry.grid(row=0, column=0, sticky="w")
        self._add_placeholder(self.search_entry, "table.search")
        self.search_text.trace_add("write", self._on_search_changed)

        self.filter_combobox = ttk.Combobox(
            toolbar, textvariable=self.row_filter, state="readonly", width=13
        )
        self.filter_combobox.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.filter_combobox.bind("<<ComboboxSelected>>", lambda _event: self.update_table())

        buttons = ttk.Frame(toolbar, style="Toolbar.TFrame")
        buttons.grid(row=0, column=3, sticky="e")
        for key, command, style_name in (
            ("action.read_group", self.read_parameters, "Accent.TButton"),
            ("action.write_edited", self.save_changes, "TButton"),
            ("action.read_all", self.read_all_parameters, "TButton"),
            ("action.write_all", self.write_all_parameters, "TButton"),
        ):
            button = ttk.Button(buttons, text="", style=style_name, command=command)
            button.pack(side="left", padx=(6, 0))
            self._action_widgets.append(button)
            self.text_buttons[key] = button

        self.sheet = tksheet.Sheet(
            workspace,
            headers=[self.t(key) for key in COLUMN_KEYS],
            show_x_scrollbar=True,
            show_y_scrollbar=True,
            show_row_index=False,
            empty_horizontal=0,
            empty_vertical=0,
        )
        self.sheet.grid(row=1, column=0, sticky="nsew")
        self.sheet.enable_bindings(
            (
                "single_select",
                "row_select",
                "drag_select",
                "edit_cell",
                "column_width_resize",
                "double_click_column_resize",
                "arrowkeys",
                "copy",
                "rc_select",
            )
        )
        self.sheet.set_column_widths(list(self.COLUMN_WIDTHS))
        self.sheet.align_columns(columns=[0, 2, 3, 4], align="center")
        self.sheet.align_columns(columns=[1, 5], align="w")
        self.sheet.readonly_columns(columns=[0, 1, 3, 4, 5])
        self.sheet.bind("<<SheetModified>>", self._on_sheet_modified)
        self.sheet.bind("<<SheetSelect>>", self._on_sheet_select)

        self._build_details(workspace)

    def _build_details(self, parent):
        details = ttk.Frame(parent, style="Card.TFrame", padding=(14, 10, 14, 12))
        details.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        details.grid_columnconfigure(0, weight=1)

        head = ttk.Frame(details, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(1, weight=1)
        self.details_title = ttk.Label(head, text="", style="Card.TLabel", font=FONT)
        self.details_title.grid(row=0, column=0, sticky="w")
        self.details_meta = ttk.Label(head, text="", style="Muted.TLabel")
        self.details_meta.grid(row=0, column=1, sticky="e")

        self.details_text = tk.Text(
            details,
            height=5,
            wrap="word",
            relief="flat",
            highlightthickness=0,
            borderwidth=0,
            font=SMALL_FONT,
            padx=0,
            pady=6,
        )
        self.details_text.grid(row=1, column=0, sticky="ew")
        # Option lists run to several hundred characters, so the panel scrolls.
        self.details_scroll = ttk.Scrollbar(
            details, orient="vertical", command=self.details_text.yview
        )
        self.details_scroll.grid(row=1, column=1, sticky="ns", padx=(6, 0))
        self.details_text.configure(yscrollcommand=self._on_details_scroll)
        self.details_text.bind("<MouseWheel>", self._on_details_wheel)
        self.details_text.configure(state="disabled")

    def _on_details_scroll(self, first, last):
        """Hide the scrollbar while the whole text already fits."""
        self.details_scroll.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.details_scroll.grid_remove()
        else:
            self.details_scroll.grid()

    def _on_details_wheel(self, event):
        self.details_text.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _build_statusbar(self):
        bar = ttk.Frame(self.root, style="Status.TFrame", padding=(14, 8))
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_columnconfigure(2, weight=1)

        self.link_dot = tk.Label(bar, text="●", font=FONT)
        self.link_dot.grid(row=0, column=0, sticky="w")
        ttk.Label(bar, textvariable=self.link_text, style="Status.TLabel").grid(
            row=0, column=1, sticky="w", padx=(6, 0)
        )
        self.status_label = ttk.Label(bar, textvariable=self.status_text, style="StatusMuted.TLabel")
        self.status_label.grid(row=0, column=2, sticky="w", padx=18)

        self.progress = ttk.Progressbar(bar, mode="determinate", length=190)
        self.cancel_button = ttk.Button(bar, text="", style="Danger.TButton", command=self.cancel_task)
        ttk.Label(bar, textvariable=self.counts_text, style="StatusMuted.TLabel").grid(
            row=0, column=5, sticky="e"
        )

    def _bind_shortcuts(self):
        self.root.bind("<F5>", lambda _e: self.read_parameters())
        self.root.bind("<Control-r>", lambda _e: self.read_all_parameters())
        self.root.bind("<Control-s>", lambda _e: self.save_to_file())
        self.root.bind("<Control-o>", lambda _e: self.load_from_file())
        self.root.bind("<Control-f>", lambda _e: self._focus_search())
        self.root.bind("<Control-t>", lambda _e: self.toggle_theme())
        self.root.bind("<Escape>", lambda _e: self._on_escape())

    def _add_placeholder(self, entry: ttk.Entry, key: str):
        """Show grey helper text while the entry is empty and unfocused."""

        def show(_event=None):
            if not self.search_text.get():
                entry.configure(foreground=self.palette.muted)
                entry.insert(0, self.t(key))
                entry._placeholder_active = True

        def hide(_event=None):
            if getattr(entry, "_placeholder_active", False):
                entry.delete(0, "end")
                entry.configure(foreground=self.palette.text)
                entry._placeholder_active = False

        entry._placeholder_key = key
        entry._show_placeholder = show
        entry._hide_placeholder = hide
        entry.bind("<FocusIn>", hide)
        entry.bind("<FocusOut>", show)
        show()

    # ------------------------------------------------------------------
    # Theme and language
    # ------------------------------------------------------------------
    def apply_theme(self):
        palette = self.palette
        apply_theme(self.root, self.style, palette)
        self.sheet.change_theme(palette.sheet_theme, redraw=False)
        self.sheet.set_options(redraw=False, **sheet_options(palette))
        self.theme_button.configure(
            text=self.t("action.theme_dark" if palette.name == "light" else "action.theme_light")
        )
        self.link_dot.configure(background=palette.surface, foreground=palette.muted)
        self.details_text.configure(
            background=palette.surface, foreground=palette.muted, insertbackground=palette.text
        )
        self.details_text.tag_configure("body", foreground=palette.text)
        self.search_entry.configure(
            foreground=palette.muted
            if getattr(self.search_entry, "_placeholder_active", False)
            else palette.text
        )
        self._refresh_row_styles()
        self._update_link_indicator()

    def toggle_theme(self):
        self.palette = THEMES["dark" if self.palette.name == "light" else "light"]
        self.apply_theme()
        self._save_preferences()

    def set_language(self, language):
        """Switch the interface language without restarting the editor."""
        if language == self.t.language:
            return
        self.t.set_language(language)
        self._apply_language()
        self._save_preferences()
        logger.info("Interface language: %s", self.t.language)

    def _apply_language(self):
        """Re-label every widget after a language change."""
        t = self.t
        for code, button in self._language_buttons.items():
            button.configure(style="Accent.TButton" if code == t.language else "Brand.TButton")

        self.manual_button.configure(text=t("action.manual"))
        self.theme_button.configure(
            text=t("action.theme_dark" if self.palette.name == "light" else "action.theme_light")
        )
        self.connection_label.configure(text=t("sidebar.connection"))
        self.model_label.configure(text=t("sidebar.model"))
        self.port_label.configure(text=t("sidebar.port"))
        self.device_id_label.configure(text=t("sidebar.device_id"))
        self.groups_label.configure(text=t("sidebar.groups"))
        self.files_label.configure(text=t("sidebar.files"))
        self.test_button.configure(text=t("action.test_link"))
        self.cancel_button.configure(text=t("action.cancel"))
        for key, button in self.text_buttons.items():
            button.configure(text=t(key))

        if getattr(self.search_entry, "_placeholder_active", False):
            self.search_entry._hide_placeholder()
            self.search_entry._show_placeholder()

        current_filter = self._filter_key()
        self._filter_keys = {t(f"filter.{key}"): key for key in FILTERS}
        self.filter_combobox["values"] = list(self._filter_keys)
        self.row_filter.set(t(f"filter.{current_filter}"))

        self._profile_keys = self.catalog.labels(t.language)
        self.profile_combobox["values"] = list(self._profile_keys)
        self.selected_profile_label.set(self.profile.label(t.language))

        self.sheet.headers([t(key) for key in COLUMN_KEYS])
        self._populate_groups()
        self.update_table()
        self._update_titles()

        row = getattr(self.sheet.get_currently_selected(), "row", None)
        if row is not None and 0 <= row < len(self.rows):
            self._show_details(self.rows[row])
        else:
            self.details_title.configure(text=t("details.none"))
            self.details_meta.configure(text="")
            self.details_text.configure(state="normal")
            self.details_text.delete("1.0", "end")
            self.details_text.configure(state="disabled")

        message, level, params = self._status
        self._set_status(message, level, **params)

    # ------------------------------------------------------------------
    # Profile, ports and groups
    # ------------------------------------------------------------------
    def change_profile(self, event=None):
        """Switch parameter maps without carrying values between models."""
        if self._busy:
            self.selected_profile_label.set(self.profile.label(self.language))
            self._set_status("status.wait_operation", "warning")
            return
        key = self._profile_keys.get(self.selected_profile_label.get())
        if key is None:
            return
        self._activate_profile(self.catalog[key])

    def _activate_profile(self, profile, status=None, preserve_values=False, **status_params):
        """Apply one parameter map and drop values it does not know."""
        self.session.use_profile(profile, preserve_values=preserve_values)
        self.selected_profile_label.set(profile.label(self.language))
        if not preserve_values:
            self.selected_device_id.set(profile.link.device_id)
            self.selected_group.set(ALL_GROUPS)
        elif self.selected_group.get() not in profile.groups:
            self.selected_group.set(ALL_GROUPS)
        self._populate_groups()
        self.update_table()
        self._update_titles()
        if status:
            self._set_status(status, "info", **status_params)
        else:
            self._set_status("status.profile_loaded", model=profile.model)
        logger.info("Selected inverter profile: %s", profile.key)

    def refresh_ports(self, announce=True):
        """Refresh the list of available COM ports."""
        ports = [port.device for port in serial.tools.list_ports.comports()]
        current = self.selected_port.get()
        self.port_combobox["values"] = ports
        if ports:
            self.selected_port.set(current if current in ports else ports[0])
            self._set_status(lambda n=len(ports): self.t.plural("status.ports_available", n))
        else:
            self.selected_port.set("")
            self._set_status("status.no_ports", "warning")
            if announce:
                messagebox.showwarning(
                    self.t("dialog.serial_ports.title"), self.t("dialog.serial_ports.body")
                )
            logger.warning("No COM ports found")
        self._update_link_indicator()

    def _populate_groups(self):
        tree = self.group_tree
        tree.delete(*tree.get_children())
        tree.insert(
            "", "end", iid=ALL_GROUPS, text=self.t("group.all"),
            values=(len(self.profile.parameters),),
        )
        for group in self.profile.groups:
            count = sum(1 for p in self.profile.parameters if p["group"] == group)
            title = self.profile.group_label(group, self.language)
            tree.insert("", "end", iid=group, text=f"{group}  {title}", values=(count,))
        target = self.selected_group.get()
        if not tree.exists(target):
            target = ALL_GROUPS
            self.selected_group.set(target)
        tree.selection_set(target)
        tree.see(target)

    def _on_group_selected(self, _event=None):
        selection = self.group_tree.selection()
        if selection:
            self.selected_group.set(selection[0])
            self.update_table()

    def _group_parameters(self):
        return self.session.group_parameters(self.selected_group.get())

    def _group_label(self):
        group = self.selected_group.get()
        if group == ALL_GROUPS:
            return self.t("group.all")
        return f"{group} - {self.profile.group_label(group, self.language)}"

    def open_manual(self):
        if self.profile.manual_url:
            webbrowser.open(self.profile.manual_url)
            self._set_status("status.manual_opened")
        else:
            self._set_status("status.no_manual", "warning")

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------
    def update_table(self, event=None):
        """Rebuild the table from the group, search text and row filter."""
        self.rows = self.session.visible_parameters(
            self.selected_group.get(), self._search_query(), self._filter_key()
        )
        self.data = [
            [
                param["code"],
                self._text(param, "description"),
                self.session.display(param),
                self._unit(param),
                self._default_display(param),
                self._short_range(self._text(param, "range")),
            ]
            for param in self.rows
        ]
        self.sheet.set_sheet_data(self.data, reset_col_positions=False, redraw=False)
        self._refresh_row_styles()
        self._update_counts()

    def _text(self, parameter, field_name: str) -> str:
        return self.profile.text(parameter, field_name, self.language)

    def _unit(self, parameter) -> str:
        return self.t.unit(parameter.get("unit", ""))

    def _default_display(self, parameter) -> str:
        if parameter.get("default"):
            return parameter["default"]
        return self._text(parameter, "default_note")

    def _filter_key(self) -> str:
        return self._filter_keys.get(self.row_filter.get(), FILTERS[0])

    def _search_query(self) -> str:
        if getattr(self.search_entry, "_placeholder_active", False):
            return ""
        return self.search_text.get().strip().lower()

    def _on_search_changed(self, *_args):
        if getattr(self.search_entry, "_placeholder_active", False):
            return
        if self._search_job is not None:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(180, self.update_table)

    @staticmethod
    def _short_range(text: str, limit: int = 160) -> str:
        """Keep the table readable; the details panel shows the full text."""
        text = " ".join(str(text).split())
        return text if len(text) <= limit else f"{text[:limit - 1]}…"

    def _refresh_row_styles(self):
        sheet = self.sheet
        sheet.dehighlight_all(redraw=False)
        if self._readonly_rows:
            sheet.readonly_cells(
                cells=[(row, self.VALUE_COLUMN) for row in self._readonly_rows], readonly=False
            )

        readonly, edited, errors, nondefault = [], [], [], []
        for index, param in enumerate(self.rows):
            code = param["code"]
            if param.get("read_only"):
                readonly.append(index)
            if code in self.session.failed:
                errors.append(index)
            elif code in self.session.edited:
                edited.append(index)
            # Marking the factory cell, not the value cell, keeps the two
            # questions apart: what is in the drive, and what left the works.
            if self.session.matches_default(param) is False:
                nondefault.append(index)

        palette = self.palette
        if readonly:
            sheet.highlight_rows(
                rows=readonly, bg=palette.readonly_bg, fg=palette.readonly_fg, redraw=False
            )
            sheet.readonly_cells(cells=[(row, self.VALUE_COLUMN) for row in readonly], readonly=True)
        self._readonly_rows = readonly
        for indexes, column, background, foreground in (
            (edited, self.VALUE_COLUMN, palette.modified_bg, palette.modified_fg),
            (errors, self.VALUE_COLUMN, palette.error_bg, palette.error_fg),
            (nondefault, self.DEFAULT_COLUMN, palette.nondefault_bg, palette.nondefault_fg),
        ):
            if indexes:
                sheet.highlight_cells(
                    cells=[(row, column) for row in indexes],
                    bg=background,
                    fg=foreground,
                    redraw=False,
                )
        sheet.refresh()

    def _on_sheet_modified(self, _event=None):
        """Track manual edits so they can be highlighted and written back."""
        data = self.sheet.get_sheet_data()
        values = [
            row[self.VALUE_COLUMN] if len(row) > self.VALUE_COLUMN else ""
            for row in data[: len(self.rows)]
        ]
        self.session.track_edits(self.rows[: len(values)], values)
        self._refresh_row_styles()
        self._update_counts()

    def _on_sheet_select(self, _event=None):
        row = getattr(self.sheet.get_currently_selected(), "row", None)
        if row is None or not 0 <= row < len(self.rows):
            return
        self._show_details(self.rows[row])

    def _show_details(self, param):
        t = self.t
        writable = t("details.readonly" if param.get("read_only") else "details.writable")
        running = param.get("change_while_running")
        meta = [f"0x{param['address']:04X}", t("details.group", group=param["group"]), writable]
        if running is not None and not param.get("read_only"):
            meta.append(t("details.running_yes" if running else "details.running_no"))
        if param.get("manual_pdf_page"):
            meta.append(t("details.manual_page", page=param["manual_pdf_page"]))

        self.details_title.configure(
            text=f"{param['code']}  ·  {self._text(param, 'description')}"
        )
        self.details_meta.configure(text="  ·  ".join(meta))

        default = self._default_display(param) or "—"
        unit = f" {self._unit(param)}" if param["unit"] and param["default"] else ""
        body = f"{t('details.default', value=default)}{unit}\n{self._text(param, 'range')}"
        note = self._text(param, "note")
        if note:
            body += "\n\n" + t("details.translation_note", note=note)
        self.details_text.configure(state="normal")
        self.details_text.delete("1.0", "end")
        self.details_text.insert("1.0", body, "body")
        self.details_text.configure(state="disabled")

    def _update_counts(self):
        parts = [
            self.t(
                "status.counts_shown",
                shown=len(self.rows),
                total=len(self._group_parameters()),
            )
        ]
        if self.session.edited:
            parts.append(self.t("status.counts_edited", n=len(self.session.edited)))
        if self.session.failed:
            parts.append(self.t.plural("status.counts_errors", len(self.session.failed)))
        self.counts_text.set("  ·  ".join(parts))

    # ------------------------------------------------------------------
    # Connection and background tasks
    # ------------------------------------------------------------------
    def _prepare_connection(self) -> bool:
        """Validate the serial settings on the UI thread before a task starts."""
        port = self.selected_port.get()
        if not port:
            messagebox.showerror(
                self.t("dialog.select_port.title"), self.t("dialog.select_port.body")
            )
            return False
        try:
            device_id = int(self.selected_device_id.get())
        except (tk.TclError, ValueError):
            device_id = 0
        if not 1 <= device_id <= 247:
            messagebox.showerror(
                self.t("dialog.device_id.title"), self.t("dialog.device_id.body")
            )
            return False
        self._connection = {"port": port, "device_id": device_id}
        return True

    def _start_task(self, title, work, on_success):
        """Run ``work(link, progress)`` on a worker thread."""
        if self._busy:
            self._set_status("status.busy", "warning")
            return
        if not self._prepare_connection():
            return

        self._cancel.clear()
        self._busy = True
        self._set_busy(True, title)
        link = ModbusLink(
            self._connection["port"],
            self._connection["device_id"],
            self.profile.link,
            self._cancel,
        )

        def runner():
            try:
                link.open()
                result = work(link, self._report_progress)
            except TaskCancelled:
                self.root.after(0, self._task_cancelled, title)
            except Exception as exc:  # surfaced in the UI, never crashes the app
                logger.exception("%s failed", title)
                self.root.after(0, self._task_failed, title, exc)
            else:
                self.root.after(0, self._task_finished, result, on_success)
            finally:
                link.close()

        threading.Thread(target=runner, name="modbus-worker", daemon=True).start()

    def _report_progress(self, done, total):
        self.root.after(0, self._set_progress, done, total)

    def _set_progress(self, done, total):
        if not self._busy:
            return
        self.progress.configure(maximum=max(total, 1), value=done)
        self._set_status("status.progress", title=self._task_title, done=done, total=total)

    def _set_busy(self, busy, title=""):
        self._task_title = title
        state = "disabled" if busy else "normal"
        for widget in self._action_widgets:
            widget.configure(state=state)
        if busy:
            self.progress.configure(value=0, maximum=1)
            self.progress.grid(row=0, column=3, sticky="e", padx=(0, 10))
            self.cancel_button.grid(row=0, column=4, sticky="e", padx=(0, 14))
            self._set_status("status.working", title=title)
            self.root.configure(cursor="watch")
        else:
            self.progress.grid_remove()
            self.cancel_button.grid_remove()
            self.root.configure(cursor="")
        self._update_link_indicator(busy=busy)

    def cancel_task(self):
        if self._busy:
            self._cancel.set()
            self._set_status("status.cancelling", "warning")

    def _task_finished(self, result, on_success):
        self._busy = False
        self._set_busy(False)
        on_success(result)

    def _task_cancelled(self, title):
        self._busy = False
        self._set_busy(False)
        self._set_status("status.cancelled", "warning", title=title)

    def _task_failed(self, title, exc):
        self._busy = False
        self._set_busy(False)
        message = self.t("error.open_port", port=exc.port) if isinstance(exc, LinkError) else str(exc)
        self._set_status("status.failed", "danger", title=title, error=message)
        messagebox.showerror(title, message)

    # ------------------------------------------------------------------
    # Revision detection
    # ------------------------------------------------------------------
    def _run_after_profile_detection(self, continuation):
        """Run an action, resolving an auto-detect profile first."""
        if self._busy:
            self._set_status("status.busy", "warning")
            return
        if not detection.needs_detection(self.profile):
            continuation()
            return
        self._start_task(
            self.t("task.detect"),
            lambda link, _progress: detection.detect(self.catalog, self.profile, link),
            lambda result: self._detection_finished(result, continuation),
        )

    def _detection_finished(self, result, continuation):
        self._activate_profile(
            result.profile,
            "status.revision_detected",
            preserve_values=True,
            model=result.profile.model,
            value=result.displayed_value,
        )
        continuation()

    # ------------------------------------------------------------------
    # Read / write actions
    # ------------------------------------------------------------------
    def test_connection(self):
        """Read a single register to confirm the link and the Modbus ID."""

        def start():
            parameter = self.profile.parameters[0]

            def work(link, _progress):
                result = link.read_register(parameter["address"])
                if result.isError():
                    raise ModbusException(str(result))
                return parameter["code"], result.registers[0]

            self._start_task(self.t("task.test_link"), work, self._link_test_finished)

        self._run_after_profile_detection(start)

    def _link_test_finished(self, result):
        code, value = result
        self._set_status("status.link_ok", "success", code=code, value=value)
        self._update_link_indicator(ok=True)

    def read_parameters(self):
        """Read the parameters of the selected group."""

        def start():
            parameters = self._group_parameters()
            if not parameters:
                messagebox.showwarning(
                    self.t("dialog.nothing_to_read.title"),
                    self.t("dialog.nothing_to_read.body"),
                )
                return
            self._start_task(
                self.t("task.read_group", group=self._group_label()),
                lambda link, progress: link.read_values(parameters, progress),
                self._read_finished,
            )

        self._run_after_profile_detection(start)

    def read_all_parameters(self):
        """Read every parameter of the selected profile."""

        def start():
            parameters = list(self.profile.parameters)
            self._start_task(
                self.t("task.read_all", n=len(parameters)),
                lambda link, progress: link.read_values(parameters, progress),
                self._read_finished,
            )

        self._run_after_profile_detection(start)

    def _read_finished(self, values):
        successful = self.session.apply_read(values)
        self.update_table()
        self._update_link_indicator(ok=successful > 0)
        level = "success" if successful == len(values) else "warning"
        self._set_status("status.read_result", level, ok=successful, total=len(values))
        logger.info("Read %s/%s parameters for %s", successful, len(values), self.profile.model)

    def save_changes(self):
        """Write only the cells edited in the current view."""

        def start():
            group = self.selected_group.get()
            scope = (
                self.t("scope.all_groups")
                if group == ALL_GROUPS
                else self.t("scope.group", group=group)
            )
            self._write_parameters(self._group_parameters(), scope, edited_only=True)

        self._run_after_profile_detection(start)

    def write_all_parameters(self):
        """Write every known writable value back to the inverter."""
        self._run_after_profile_detection(
            lambda: self._write_parameters(
                list(self.profile.parameters), self.t("scope.all_parameters")
            )
        )

    def _problem_text(self, problem: Problem) -> str:
        # Codecs carry the unit as the manual prints it; the message shows it
        # in the interface language, like every other unit in the window.
        params = dict(problem.params)
        unit = str(params.get("unit", "")).strip()
        if unit:
            params["unit"] = f" {self.t.unit(unit)}"
        return self.t(problem.key, **params)

    def _write_parameters(self, parameters, scope, edited_only=False):
        t = self.t
        targets, problems = self.session.collect_write_targets(parameters, edited_only)
        if problems:
            listing = "\n".join(
                t("valid.problem", code=code, problem=self._problem_text(problem), value=self.session.edited.get(code, ""))
                for code, problem in problems[:12]
            )
            if len(problems) > 12:
                listing += t("dialog.more", n=len(problems) - 12)
            if not targets:
                messagebox.showerror(
                    t("dialog.invalid_values.title"),
                    t("dialog.invalid_values.none", problems=listing),
                )
                return
            if not messagebox.askyesno(
                t("dialog.invalid_values.title"),
                t.plural(
                    "dialog.invalid_values.skip",
                    len(problems),
                    problems=listing,
                    rest=len(targets),
                ),
            ):
                return
        if not targets:
            messagebox.showinfo(
                t("dialog.nothing_to_write.title"), t("dialog.nothing_to_write.body")
            )
            return

        edited = sum(1 for target in targets if target.code in self.session.edited)
        if not messagebox.askyesno(
            t("dialog.confirm_write.title"),
            t(
                "dialog.confirm_write.body",
                count=t.plural("dialog.confirm_write.count", len(targets)),
                scope=scope,
                model=self.profile.model,
                port=self.selected_port.get(),
                device_id=self.selected_device_id.get(),
                edited=t.plural("dialog.confirm_write.edited", edited),
            ),
        ):
            logger.info("Writing %s cancelled by user", scope)
            return

        payload = [target.as_tuple() for target in targets]
        self._start_task(
            t("task.write", scope=scope),
            lambda link, progress: link.write_values(payload, progress),
            self._write_finished,
        )

    def _write_finished(self, result):
        written, failed = result["written"], result["failed"]
        self.session.apply_write(written)
        self.update_table()
        self._update_link_indicator(ok=bool(written))
        if failed:
            details = "\n".join(f"{code}: {message}" for code, message in failed[:12])
            self._set_status(
                "status.write_partial", "danger", written=len(written), failed=len(failed)
            )
            messagebox.showerror(
                self.t("dialog.write_errors.title"),
                self.t.plural("dialog.write_errors.body", len(failed), details=details),
            )
        else:
            self._set_status(
                lambda n=len(written): self.t.plural("status.write_result", n), "success"
            )

    # ------------------------------------------------------------------
    # Settings files
    # ------------------------------------------------------------------
    def _file_types(self):
        return [
            (self.t("dialog.json_files"), "*.json"),
            (self.t("dialog.all_files"), "*.*"),
        ]

    def save_to_file(self):
        """Read every writable parameter and store it as JSON."""

        def start():
            file_path = filedialog.asksaveasfilename(
                defaultextension=".json",
                initialfile=f"{self.profile.key}_settings.json",
                filetypes=self._file_types(),
                title=self.t("dialog.save.title"),
            )
            if not file_path:
                logger.info("Saving cancelled by user")
                return
            writable = [p for p in self.profile.parameters if not p.get("read_only")]
            self._start_task(
                self.t("task.read_for_save"),
                lambda link, progress: link.read_values(writable, progress),
                lambda values: self._write_settings_file(file_path, values),
            )

        self._run_after_profile_detection(start)

    def _write_settings_file(self, file_path, settings):
        payload = self.session.settings_payload(settings, self.selected_device_id.get())
        try:
            with open(file_path, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=4)
        except OSError as exc:
            self._set_status("status.save_failed", "danger", error=exc)
            messagebox.showerror(self.t("dialog.save_failed.title"), str(exc))
            return
        self._read_finished(settings)
        self._set_status(
            "status.saved", "success", n=len(settings), file=Path(file_path).name
        )
        logger.info("Settings saved to file: %s", file_path)

    def load_from_file(self):
        """Load settings from a file into the table."""
        if self._busy:
            self._set_status("status.busy", "warning")
            return
        file_path = filedialog.askopenfilename(
            filetypes=self._file_types(), title=self.t("dialog.load.title")
        )
        if not file_path:
            logger.info("Loading cancelled by user")
            return

        try:
            with open(file_path, "r", encoding="utf-8") as stream:
                payload = json.load(stream)
            loaded = parse_settings_file(payload, self.catalog)
        except Exception as exc:
            message = self._settings_error_text(exc)
            self._set_status("status.load_failed", "danger", error=message)
            messagebox.showerror(self.t("dialog.load_failed.title"), message)
            logger.error("Error loading from file: %s", exc)
            return

        if loaded.profile.key != self.profile.key:
            self._activate_profile(loaded.profile)
        if loaded.device_id is not None:
            self.selected_device_id.set(loaded.device_id)
        self.session.loaded = dict(loaded.values)
        self.session.failed = set(loaded.failed)
        self.session.edited.clear()
        self.update_table()
        note = self.t.plural("status.loaded_note", loaded.skipped) if loaded.skipped else ""
        self._set_status(
            "status.loaded",
            "success",
            n=len(loaded.values),
            file=Path(file_path).name,
            note=note,
        )
        logger.info("Settings loaded from file: %s", file_path)

    def _settings_error_text(self, exc: Exception) -> str:
        """Turn a session-level error code into a localized message."""
        kind, _, detail = str(exc).partition(":")
        if kind == "unknown-profile":
            return self.t("error.unknown_profile", profile=detail)
        if kind == "not-a-settings-file":
            return self.t("error.not_a_settings_file")
        if kind == "unsupported-version":
            return self.t("error.unsupported_version", version=detail or "?")
        if kind == "out-of-range":
            return self.t("error.raw_out_of_range", code=detail)
        return str(exc)

    # ------------------------------------------------------------------
    # Status bar, preferences and window plumbing
    # ------------------------------------------------------------------
    def _set_status(self, message, level="info", **params):
        """Show a status message; ``message`` is a translation key or a callable."""
        self._status = (message, level, params)
        self.status_text.set(message() if callable(message) else self.t(message, **params))
        style = {
            "success": "Success.Status.TLabel",
            "warning": "Warning.Status.TLabel",
            "danger": "Danger.Status.TLabel",
        }.get(level, "StatusMuted.TLabel")
        self.status_label.configure(style=style)

    def _update_link_indicator(self, ok=None, busy=None):
        connected = bool(self.selected_port.get())
        port = self.selected_port.get() or self.t("link.no_port")
        frame = self.profile.link.frame
        self.link_settings_label.configure(text=frame)
        try:
            device_id = int(self.selected_device_id.get())
        except (tk.TclError, ValueError):
            device_id = "?"
        self.link_text.set(self.t("link.summary", port=port, link=frame, device_id=device_id))

        if busy or self._busy:
            colour = self.palette.warning
        elif ok is None:
            colour = self.palette.muted if connected else self.palette.danger
        else:
            colour = self.palette.success if ok else self.palette.danger
        self.link_dot.configure(foreground=colour, background=self.palette.surface)

    def _update_titles(self):
        self.root.title(f"{self.t('app.name')} — {self.profile.model} ({self.VERSION})")
        self.header_subtitle.configure(
            text=self.t(
                "header.subtitle",
                model=self.profile.model,
                parameters=self.t.plural("count.parameters", len(self.profile.parameters)),
                groups=self.t.plural("count.groups", len(self.profile.groups)),
                version=self.VERSION,
            )
        )
        self.manual_button.configure(state="normal" if self.profile.manual_url else "disabled")
        self._update_link_indicator()

    def _focus_search(self):
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, "end")

    def _on_escape(self):
        if self._busy:
            self.cancel_task()
        elif self._search_query():
            self.search_text.set("")
            self.update_table()

    def _load_preferences(self) -> dict:
        try:
            with PREFERENCES_PATH.open(encoding="utf-8") as stream:
                data = json.load(stream)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _restore_connection_preferences(self):
        port = self.preferences.get("port")
        if port and port in (self.port_combobox["values"] or ()):
            self.selected_port.set(port)
        device_id = self.preferences.get("device_id")
        if isinstance(device_id, int) and 1 <= device_id <= 247:
            self.selected_device_id.set(device_id)
        self._update_link_indicator()

    def _save_preferences(self):
        try:
            device_id = int(self.selected_device_id.get())
        except (tk.TclError, ValueError):
            device_id = self.profile.link.device_id
        payload = {
            "language": self.t.language,
            "theme": self.palette.name,
            "profile": self.profile.key,
            "port": self.selected_port.get(),
            "device_id": device_id,
            "geometry": self.root.winfo_geometry(),
        }
        try:
            with PREFERENCES_PATH.open("w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
        except OSError:
            logger.debug("Could not store preferences", exc_info=True)

    def _on_close(self):
        if self._busy and not messagebox.askyesno(
            self.t("dialog.closing.title"), self.t("dialog.closing.body")
        ):
            return
        self._cancel.set()
        self._save_preferences()
        self.root.destroy()


def main():
    """Start the editor; a broken profile directory is reported up front."""
    logging.basicConfig(level=logging.INFO)
    root = tk.Tk()
    try:
        InverterParameterEditor(root)
    except CatalogError as exc:
        root.withdraw()
        messagebox.showerror("Inverter profiles", str(exc))
        raise
    root.mainloop()
