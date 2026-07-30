"""ENC inverter parameter editor.

A Modbus RTU front end for ENC frequency inverters: pick a model, read a
parameter group (or the whole map), edit values in the table and write them
back.  All serial traffic runs on a worker thread so the window stays
responsive and every long operation can be cancelled.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import serial.tools.list_ports
import tksheet
from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusException

from inverter_profiles import PROFILE_LABELS, PROFILES
from ui_theme import FONT, SMALL_FONT, THEMES, apply_theme, sheet_options

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PREFERENCES_PATH = Path.home() / ".enc_inverter_editor.json"
ALL_GROUPS = "All parameters"
FILTERS = ("All", "Writable", "Read-only", "Edited", "Errors")


class TaskCancelled(RuntimeError):
    """Raised inside the worker thread when the user cancels an operation."""


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


class InverterParameterEditor:
    VERSION = "2.2.2"

    COLUMNS = ("Code", "Parameter", "Value", "Unit", "Default", "Range / options")
    COLUMN_WIDTHS = (80, 300, 100, 60, 80, 380)
    VALUE_COLUMN = 2

    def __init__(self, root):
        self.root = root
        self.preferences = self._load_preferences()
        self.palette = THEMES.get(self.preferences.get("theme", "light"), THEMES["light"])
        self.style = ttk.Style(root)

        self.profile = PROFILES.get(self.preferences.get("profile"), PROFILES["eds800"])

        # Tk variables
        self.selected_profile_label = tk.StringVar(value=self.profile.label)
        self.selected_port = tk.StringVar()
        self.selected_device_id = tk.IntVar(value=self.profile.default_device_id)
        self.selected_group = tk.StringVar(value=ALL_GROUPS)
        self.search_text = tk.StringVar()
        self.row_filter = tk.StringVar(value=FILTERS[0])
        self.status_text = tk.StringVar(value="Ready")
        self.link_text = tk.StringVar(value="Idle")
        self.counts_text = tk.StringVar(value="")

        # State
        self.loaded_settings: dict[str, int] = {}
        self.edited_values: dict[str, str] = {}
        self.failed_codes: set[str] = set()
        self.rows: list[dict] = []
        self.data: list[list] = []
        self.client = None
        self._connection: dict = {}
        self._busy = False
        self._cancel = threading.Event()
        self._readonly_rows: list[int] = []
        self._task_title = ""
        self._search_job = None
        self._action_widgets: list[ttk.Widget] = []

        self._build_ui()
        self.apply_theme()
        self.refresh_ports(announce=False)
        self._restore_connection_preferences()
        self._populate_groups()
        self.update_table()
        self._update_titles()

        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.root.title(f"ENC Inverter Parameter Editor {self.VERSION}")
        self.root.geometry(self.preferences.get("geometry", "1340x820"))
        self.root.minsize(1080, 620)
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
        ttk.Label(title_box, text="ENC Inverter Parameter Editor", style="BrandTitle.TLabel").pack(anchor="w")
        self.header_subtitle = ttk.Label(title_box, text="", style="BrandSub.TLabel")
        self.header_subtitle.pack(anchor="w", pady=(2, 0))

        actions = ttk.Frame(header, style="Brand.TFrame")
        actions.grid(row=0, column=2, sticky="e", padx=18)
        self.manual_button = ttk.Button(
            actions, text="Manual", style="Brand.TButton", command=self.open_manual
        )
        self.manual_button.pack(side="left", padx=(0, 8))
        self.theme_button = ttk.Button(
            actions, text=self.palette.label, style="Brand.TButton", command=self.toggle_theme
        )
        self.theme_button.pack(side="left")

    def _build_sidebar(self, parent):
        sidebar = ttk.Frame(parent, style="App.TFrame", width=286)
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(1, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        # --- connection card -------------------------------------------------
        card = ttk.Frame(sidebar, style="Card.TFrame", padding=(14, 12, 14, 14))
        card.grid(row=0, column=0, sticky="ew")
        card.grid_columnconfigure(0, weight=1)

        ttk.Label(card, text="CONNECTION", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(card, text="Inverter model", style="Field.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(10, 3)
        )
        self.profile_combobox = ttk.Combobox(
            card,
            textvariable=self.selected_profile_label,
            state="readonly",
            values=list(PROFILE_LABELS),
        )
        self.profile_combobox.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.profile_combobox.bind("<<ComboboxSelected>>", self.change_profile)

        ttk.Label(card, text="Serial port", style="Field.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(12, 3)
        )
        self.port_combobox = ttk.Combobox(card, textvariable=self.selected_port, state="readonly")
        self.port_combobox.grid(row=4, column=0, sticky="ew")
        refresh = ttk.Button(card, text="↻", style="Icon.TButton", width=3, command=self.refresh_ports)
        refresh.grid(row=4, column=1, sticky="e", padx=(6, 0))

        ttk.Label(card, text="Modbus ID", style="Field.TLabel").grid(row=5, column=0, sticky="w", pady=(12, 3))
        id_row = ttk.Frame(card, style="Card.TFrame")
        id_row.grid(row=6, column=0, columnspan=2, sticky="ew")
        self.device_id_spinbox = ttk.Spinbox(
            id_row, from_=1, to=247, width=6, textvariable=self.selected_device_id
        )
        self.device_id_spinbox.pack(side="left")
        self.link_settings_label = ttk.Label(id_row, text="", style="Mono.TLabel")
        self.link_settings_label.pack(side="left", padx=(10, 0))

        self.test_button = ttk.Button(card, text="Test link", command=self.test_connection)
        self.test_button.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        self._action_widgets.append(self.test_button)

        # --- group list ------------------------------------------------------
        groups = ttk.Frame(sidebar, style="Card.TFrame", padding=(14, 12, 8, 12))
        groups.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        groups.grid_rowconfigure(1, weight=1)
        groups.grid_columnconfigure(0, weight=1)

        ttk.Label(groups, text="PARAMETER GROUPS", style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        self.group_tree = ttk.Treeview(
            groups, style="Groups.Treeview", show="tree", columns=("count",), selectmode="browse"
        )
        self.group_tree.column("#0", width=170, stretch=True)
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

        self.search_entry = ttk.Entry(toolbar, textvariable=self.search_text, style="Search.TEntry", width=28)
        self.search_entry.grid(row=0, column=0, sticky="w")
        self._add_placeholder(self.search_entry, "Search code or description")
        self.search_text.trace_add("write", self._on_search_changed)

        self.filter_combobox = ttk.Combobox(
            toolbar, textvariable=self.row_filter, state="readonly", values=FILTERS, width=11
        )
        self.filter_combobox.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.filter_combobox.bind("<<ComboboxSelected>>", lambda _event: self.update_table())

        buttons = ttk.Frame(toolbar, style="Toolbar.TFrame")
        buttons.grid(row=0, column=3, sticky="e")

        for text, command, style_name in (
            ("↓ Read group", self.read_parameters, "Accent.TButton"),
            ("↑ Write group", self.save_changes, "TButton"),
            ("↓ Read all", self.read_all_parameters, "TButton"),
            ("↑ Write all", self.write_all_parameters, "TButton"),
        ):
            button = ttk.Button(buttons, text=text, style=style_name, command=command)
            button.pack(side="left", padx=(6, 0))
            self._action_widgets.append(button)

        ttk.Separator(buttons, orient="vertical").pack(side="left", fill="y", padx=10, pady=2)

        for text, command in (("Load…", self.load_from_file), ("Save…", self.save_to_file)):
            button = ttk.Button(buttons, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            self._action_widgets.append(button)

        self.sheet = tksheet.Sheet(
            workspace,
            headers=list(self.COLUMNS),
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
        self.details_title = ttk.Label(head, text="No parameter selected", style="Card.TLabel", font=FONT)
        self.details_title.grid(row=0, column=0, sticky="w")
        self.details_meta = ttk.Label(head, text="", style="Muted.TLabel")
        self.details_meta.grid(row=0, column=1, sticky="e")

        self.details_text = tk.Text(
            details,
            height=4,
            wrap="word",
            relief="flat",
            highlightthickness=0,
            borderwidth=0,
            font=SMALL_FONT,
            padx=0,
            pady=6,
        )
        self.details_text.grid(row=1, column=0, sticky="ew")
        self.details_text.configure(state="disabled")

    def _build_statusbar(self):
        bar = ttk.Frame(self.root, style="Status.TFrame", padding=(14, 8))
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_columnconfigure(2, weight=1)

        self.link_dot = tk.Label(bar, text="●", font=FONT)
        self.link_dot.grid(row=0, column=0, sticky="w")
        ttk.Label(bar, textvariable=self.link_text, style="Status.TLabel").grid(row=0, column=1, sticky="w", padx=(6, 0))

        self.status_label = ttk.Label(bar, textvariable=self.status_text, style="StatusMuted.TLabel")
        self.status_label.grid(row=0, column=2, sticky="w", padx=18)

        self.progress = ttk.Progressbar(bar, mode="determinate", length=190)
        self.cancel_button = ttk.Button(bar, text="Cancel", style="Danger.TButton", command=self.cancel_task)
        ttk.Label(bar, textvariable=self.counts_text, style="StatusMuted.TLabel").grid(row=0, column=5, sticky="e")

    def _bind_shortcuts(self):
        self.root.bind("<F5>", lambda _e: self.read_parameters())
        self.root.bind("<Control-r>", lambda _e: self.read_all_parameters())
        self.root.bind("<Control-s>", lambda _e: self.save_to_file())
        self.root.bind("<Control-o>", lambda _e: self.load_from_file())
        self.root.bind("<Control-f>", lambda _e: self._focus_search())
        self.root.bind("<Control-t>", lambda _e: self.toggle_theme())
        self.root.bind("<Escape>", lambda _e: self._on_escape())

    def _add_placeholder(self, entry: ttk.Entry, text: str):
        """Show grey helper text while the entry is empty and unfocused."""

        def show(_event=None):
            if not self.search_text.get():
                entry.configure(foreground=self.palette.muted)
                entry.insert(0, text)
                entry._placeholder_active = True

        def hide(_event=None):
            if getattr(entry, "_placeholder_active", False):
                entry.delete(0, "end")
                entry.configure(foreground=self.palette.text)
                entry._placeholder_active = False

        entry._placeholder_text = text
        entry.bind("<FocusIn>", hide)
        entry.bind("<FocusOut>", show)
        show()

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def apply_theme(self):
        palette = self.palette
        apply_theme(self.root, self.style, palette)
        self.sheet.change_theme(palette.sheet_theme, redraw=False)
        self.sheet.set_options(redraw=False, **sheet_options(palette))
        self.theme_button.configure(text=palette.label)
        self.link_dot.configure(background=palette.surface, foreground=palette.muted)
        self.details_text.configure(
            background=palette.surface, foreground=palette.muted, insertbackground=palette.text
        )
        self.details_text.tag_configure("code", foreground=palette.accent, font=("Segoe UI", 9, "bold"))
        self.details_text.tag_configure("body", foreground=palette.text)
        if getattr(self.search_entry, "_placeholder_active", False):
            self.search_entry.configure(foreground=palette.muted)
        else:
            self.search_entry.configure(foreground=palette.text)
        self._refresh_row_styles()
        self._update_link_indicator()

    def toggle_theme(self):
        self.palette = THEMES["dark" if self.palette.name == "light" else "light"]
        self.apply_theme()
        self._save_preferences()

    # ------------------------------------------------------------------
    # Profile, ports and groups
    # ------------------------------------------------------------------
    def change_profile(self, event=None):
        """Switch parameter maps without carrying values between inverter models."""
        profile_key = PROFILE_LABELS[self.selected_profile_label.get()]
        self._activate_profile(PROFILES[profile_key])

    def _activate_profile(self, profile, status=None, preserve_values=False):
        """Apply one concrete parameter map and clear incompatible values."""
        loaded = dict(self.loaded_settings) if preserve_values else {}
        edited = dict(self.edited_values) if preserve_values else {}
        failed = set(self.failed_codes) if preserve_values else set()
        self.profile = profile
        self.selected_profile_label.set(profile.label)
        self.selected_device_id.set(self.profile.default_device_id)
        known = {parameter["code"] for parameter in profile.parameters}
        self.loaded_settings = {code: value for code, value in loaded.items() if code in known}
        self.edited_values = {code: value for code, value in edited.items() if code in known}
        self.failed_codes = failed & known
        self.selected_group.set(ALL_GROUPS)
        self._populate_groups()
        self.update_table()
        self._update_titles()
        self._set_status(status or f"Loaded parameter map for {self.profile.model}")
        logger.info("Selected inverter profile: %s", self.profile.label)

    def _ensure_auto_revision(self) -> bool:
        """Resolve the EN600 auto profile by probing V5-only parameter F02.26."""
        if self.profile.key != "en600_2s0007":
            return True
        if not self._prepare_connection():
            return False

        client = None
        try:
            client = self._open_client()
            try:
                link = client.read_holding_registers(
                    address=0x0000, count=1, device_id=self._device_id
                )
                probe = client.read_holding_registers(
                    address=0x021A, count=1, device_id=self._device_id
                )
            except TypeError:
                link = client.read_holding_registers(
                    address=0x0000, count=1, slave=self._device_id
                )
                probe = client.read_holding_registers(
                    address=0x021A, count=1, slave=self._device_id
                )
            if link.isError():
                raise ConnectionError(str(link))
            value = None if probe.isError() else probe.registers[0]
        except Exception as exc:
            messagebox.showerror("Revision detection", str(exc))
            return False
        finally:
            if client is not None:
                client.close()

        profile_key = (
            "en600_2s0007_v5"
            if value is not None and 95 <= value <= 115
            else "en600_2s0007_v2"
        )
        detected = PROFILES[profile_key]
        self._activate_profile(
            detected,
            f"Detected {detected.model} (F02.26 = {value if value is not None else 'N/A'})",
            preserve_values=True,
        )
        return True

    def refresh_ports(self, announce=True):
        """Refresh the list of available COM ports."""
        ports = [port.device for port in serial.tools.list_ports.comports()]
        current = self.selected_port.get()
        self.port_combobox["values"] = ports
        if ports:
            self.selected_port.set(current if current in ports else ports[0])
            self._set_status(f"{_plural(len(ports), 'serial port')} available")
        else:
            self.selected_port.set("")
            self._set_status("No serial ports found", "warning")
            if announce:
                messagebox.showwarning("Serial ports", "No COM ports found")
            logger.warning("No COM ports found")
        self._update_link_indicator()

    def _populate_groups(self):
        tree = self.group_tree
        tree.delete(*tree.get_children())
        tree.insert("", "end", iid=ALL_GROUPS, text=ALL_GROUPS, values=(len(self.profile.parameters),))
        for group in self.profile.groups:
            count = sum(1 for p in self.profile.parameters if p["group"] == group)
            tree.insert("", "end", iid=group, text=group, values=(count,))
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
        group = self.selected_group.get()
        if group == ALL_GROUPS:
            return list(self.profile.parameters)
        return [p for p in self.profile.parameters if p["group"] == group]

    def open_manual(self):
        if self.profile.manual_url:
            webbrowser.open(self.profile.manual_url)
            self._set_status("Opened the manual in your browser")
        else:
            self._set_status("No manual link for this model", "warning")

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------
    def update_table(self, event=None):
        """Rebuild the table from the current group, search text and filter."""
        query = self._search_query()
        mode = self.row_filter.get()
        rows = []
        for param in self._group_parameters():
            code = param["code"]
            if mode == "Writable" and param.get("read_only"):
                continue
            if mode == "Read-only" and not param.get("read_only"):
                continue
            if mode == "Edited" and code not in self.edited_values:
                continue
            if mode == "Errors" and code not in self.failed_codes:
                continue
            if query and query not in code.lower() and query not in param["description"].lower():
                continue
            rows.append(param)

        self.rows = rows
        self.data = [
            [
                param["code"],
                param["description"],
                self._display_value(param),
                param["unit"],
                param["default"],
                self._short_range(param["range"]),
            ]
            for param in rows
        ]
        self.sheet.set_sheet_data(self.data, reset_col_positions=False, redraw=False)
        self._refresh_row_styles()
        self._update_counts()

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

    def _display_value(self, param) -> str:
        return self.edited_values.get(param["code"], self._baseline_display(param))

    def _baseline_display(self, param) -> str:
        code = param["code"]
        if code in self.failed_codes:
            return "Error"
        if code not in self.loaded_settings:
            return ""
        return self._format_value(self.loaded_settings[code], param)

    def _refresh_row_styles(self):
        sheet = self.sheet
        sheet.dehighlight_all(redraw=False)
        if self._readonly_rows:
            sheet.readonly_cells(
                cells=[(row, self.VALUE_COLUMN) for row in self._readonly_rows], readonly=False
            )

        readonly, edited, errors = [], [], []
        for index, param in enumerate(self.rows):
            code = param["code"]
            if param.get("read_only"):
                readonly.append(index)
            if code in self.failed_codes:
                errors.append(index)
            elif code in self.edited_values:
                edited.append(index)

        palette = self.palette
        if readonly:
            sheet.highlight_rows(rows=readonly, bg=palette.readonly_bg, fg=palette.readonly_fg, redraw=False)
            sheet.readonly_cells(cells=[(row, self.VALUE_COLUMN) for row in readonly], readonly=True)
        self._readonly_rows = readonly
        if edited:
            sheet.highlight_cells(
                cells=[(row, self.VALUE_COLUMN) for row in edited],
                bg=palette.modified_bg,
                fg=palette.modified_fg,
                redraw=False,
            )
        if errors:
            sheet.highlight_cells(
                cells=[(row, self.VALUE_COLUMN) for row in errors],
                bg=palette.error_bg,
                fg=palette.error_fg,
                redraw=False,
            )
        sheet.refresh()

    def _on_sheet_modified(self, _event=None):
        """Track manual edits so they can be highlighted and written back."""
        data = self.sheet.get_sheet_data()
        for index, param in enumerate(self.rows):
            if index >= len(data):
                break
            value = str(data[index][self.VALUE_COLUMN]).strip()
            code = param["code"]
            if value == self._baseline_display(param):
                self.edited_values.pop(code, None)
            else:
                self.edited_values[code] = value
        self._refresh_row_styles()
        self._update_counts()

    def _on_sheet_select(self, _event=None):
        selected = self.sheet.get_currently_selected()
        row = getattr(selected, "row", None)
        if row is None or not 0 <= row < len(self.rows):
            return
        self._show_details(self.rows[row])

    def _show_details(self, param):
        writable = "Read-only" if param.get("read_only") else "Writable"
        running = param.get("change_while_running")
        meta = [f"0x{param['address']:04X}", f"group {param['group']}", writable]
        if running is not None and not param.get("read_only"):
            meta.append("changeable while running" if running else "stop before changing")
        if param.get("manual_pdf_page"):
            meta.append(f"manual p.{param['manual_pdf_page']}")

        self.details_title.configure(text=f"{param['code']}  ·  {param['description']}")
        self.details_meta.configure(text="  ·  ".join(meta))

        unit = f" {param['unit']}" if param["unit"] else ""
        body = f"Default {param['default']}{unit}\n{param['range']}"
        self.details_text.configure(state="normal")
        self.details_text.delete("1.0", "end")
        self.details_text.insert("1.0", body, "body")
        self.details_text.configure(state="disabled")

    def _update_counts(self):
        total = len(self._group_parameters())
        shown = len(self.rows)
        parts = [f"{shown} of {total} shown"]
        if self.edited_values:
            parts.append(f"{len(self.edited_values)} edited")
        if self.failed_codes:
            parts.append(_plural(len(self.failed_codes), "error"))
        self.counts_text.set("  ·  ".join(parts))

    # ------------------------------------------------------------------
    # Validation and encoding
    # ------------------------------------------------------------------
    def parse_range(self, range_str):
        """Parse the range of values from a string."""
        try:
            min_val, max_val = map(float, range_str.split("~"))
            return min_val, max_val
        except ValueError:
            return None, None

    def _value_error(self, param, value):
        """Return a human readable problem with ``value`` or ``None``."""
        if param.get("read_only"):
            return "read-only parameter"

        value = str(value).strip()
        if param.get("encoding") == "bcd":
            expected_len = param["digits"]
            valid_chars = param["digit_chars"]
            if len(value) != expected_len or any(char not in valid_chars for char in value):
                return f"must contain exactly {expected_len} digits from {valid_chars}"
            if "~" in param["range"] and param["range"].count("~") == 1:
                minimum, maximum = param["range"].split("~", maxsplit=1)
                if minimum.isdigit() and maximum.isdigit():
                    if not int(minimum) <= int(value) <= int(maximum):
                        return f"must be between {minimum} and {maximum}"
            return None

        if param.get("encoding") == "function_code":
            match = re.fullmatch(r"F?(\d{1,2})(?:\.(\d{1,2}))?", value, re.IGNORECASE)
            if not match:
                return "must be a function code such as 25.00"
            group = int(match.group(1))
            number = int(match.group(2) or 0)
            if group > param["maximum_group"]:
                return f"function group must be between 00 and {param['maximum_group']:02d}"
            if number > 99:
                return "function number must be between 00 and 99"
            return None

        if param.get("encoding") == "hex":
            normalized = value.upper().removesuffix("H")
            expected_len = param["digits"]
            valid_chars = param["digit_chars"]
            if (
                len(normalized) != expected_len
                or any(char not in valid_chars for char in normalized)
            ):
                return (
                    f"must contain exactly {expected_len} hexadecimal digits "
                    f"from {valid_chars}"
                )
            return None

        try:
            number = float(value)
        except ValueError:
            return "must be a number"

        min_val = param.get("minimum")
        max_val = param.get("maximum")
        if min_val is None or max_val is None:
            min_val, max_val = self.parse_range(param["range"])
        if min_val is not None and max_val is not None and not min_val <= number <= max_val:
            unit = f" {param['unit']}" if param["unit"] else ""
            return f"must be between {min_val:g} and {max_val:g}{unit}"
        return None

    def validate_value(self, param, value):
        """Validate the value against the parameter's range."""
        problem = self._value_error(param, value)
        if problem is None:
            return True
        messagebox.showerror("Invalid value", f"{param['code']}: {problem}")
        return False

    def _format_value(self, value, param):
        """Format the value with scaling and BCD handling."""
        try:
            if value == "":
                return ""
            if param.get("encoding") == "bcd":
                value = int(value) & 0xFFFF
                shift_offset = int(param.get("bcd_shift", 0)) * 4
                digits = [
                    (value >> shift) & 0x0F
                    for shift in range(
                        (param["digits"] - 1) * 4 + shift_offset,
                        shift_offset - 1,
                        -4,
                    )
                ]
                if all(str(digit) in param["digit_chars"] for digit in digits):
                    return "".join(map(str, digits))
                return "BCD Error"

            if param.get("encoding") == "hex":
                value = int(value) & 0xFFFF
                digits = param["digits"]
                suffix = "H" if param.get("hex_suffix") else ""
                return f"{value:0{digits}X}{suffix}"

            if param.get("encoding") == "function_code":
                value = int(value) & 0xFFFF
                nibbles = [(value >> shift) & 0x0F for shift in (12, 8, 4, 0)]
                if any(nibble > 9 for nibble in nibbles):
                    return "Code Error"
                return f"{nibbles[0]}{nibbles[1]}.{nibbles[2]}{nibbles[3]}"

            scale = param["scale"]
            if scale == 1:
                numeric_value = int(value)
                display_width = param.get("display_width")
                return (
                    f"{numeric_value:0{display_width}d}"
                    if display_width
                    else str(numeric_value)
                )
            decimal_places = len(str(scale)) - 1
            integer_digits = param.get("display_integer_digits")
            if integer_digits:
                width = int(integer_digits) + decimal_places + 1
                return f"{float(value) / scale:0{width}.{decimal_places}f}"
            return f"{float(value) / scale:.{decimal_places}f}"
        except (ValueError, TypeError):
            return str(value)

    def _encode_value(self, param, value):
        """Convert a displayed parameter value to one 16-bit register."""
        value = str(value).strip()
        try:
            if param.get("encoding") == "bcd":
                encoded = 0
                for char in value:
                    encoded = (encoded << 4) | int(char)
                return encoded << (int(param.get("bcd_shift", 0)) * 4)
            if param.get("encoding") == "hex":
                return int(value.upper().removesuffix("H"), 16)
            if param.get("encoding") == "function_code":
                match = re.fullmatch(
                    r"F?(\d{1,2})(?:\.(\d{1,2}))?",
                    value,
                    re.IGNORECASE,
                )
                if not match:
                    raise ValueError(f"Invalid function code: {value}")
                group = int(match.group(1))
                number = int(match.group(2) or 0)
                return (
                    ((group // 10) << 12)
                    | ((group % 10) << 8)
                    | ((number // 10) << 4)
                    | (number % 10)
                )
            return int(round(float(value) * param["scale"]))
        except (ValueError, TypeError):
            raise ValueError(f"Invalid value: {value}")

    # ------------------------------------------------------------------
    # Modbus plumbing
    # ------------------------------------------------------------------
    @property
    def _device_id(self) -> int:
        return int(self._connection.get("device_id", self.profile.default_device_id))

    def _read_register(self, address):
        """Read one register across supported pymodbus 3.x keyword variants."""
        try:
            return self.client.read_holding_registers(
                address=address, count=1, device_id=self._device_id
            )
        except TypeError:
            return self.client.read_holding_registers(
                address=address, count=1, slave=self._device_id
            )

    def _read_registers(self, address, count):
        """Read a contiguous register block across pymodbus 3.x variants."""
        try:
            return self.client.read_holding_registers(
                address=address, count=count, device_id=self._device_id
            )
        except TypeError:
            return self.client.read_holding_registers(
                address=address, count=count, slave=self._device_id
            )

    def _write_register(self, address, value):
        """Write one register across supported pymodbus 3.x keyword variants."""
        try:
            return self.client.write_register(
                address=address, value=value, device_id=self._device_id
            )
        except TypeError:
            return self.client.write_register(
                address=address, value=value, slave=self._device_id
            )

    @staticmethod
    def _contiguous_chunks(parameters, maximum_size=50):
        """Split parameters into address-contiguous Modbus read batches."""
        ordered = sorted(parameters, key=lambda parameter: parameter["address"])
        chunks = []
        current = []
        for parameter in ordered:
            if (
                current
                and (
                    parameter["address"] != current[-1]["address"] + 1
                    or len(current) >= maximum_size
                )
            ):
                chunks.append(current)
                current = []
            current.append(parameter)
        if current:
            chunks.append(current)
        return chunks

    def _read_parameter_values(self, parameters, progress=None):
        """Read parameters in batches, falling back to single reads on an error."""
        values = {}
        total = len(parameters)
        for chunk in self._contiguous_chunks(
            parameters,
            maximum_size=self.profile.max_read_registers,
        ):
            self._raise_if_cancelled()
            try:
                result = self._read_registers(chunk[0]["address"], len(chunk))
                if not result.isError() and len(result.registers) == len(chunk):
                    values.update(
                        {
                            parameter["code"]: value
                            for parameter, value in zip(chunk, result.registers)
                        }
                    )
                    if progress:
                        progress(len(values), total)
                    continue
            except ModbusException as exc:
                logger.warning("Batch read failed at 0x%04X: %s", chunk[0]["address"], exc)

            for parameter in chunk:
                self._raise_if_cancelled()
                try:
                    result = self._read_register(parameter["address"])
                    values[parameter["code"]] = (
                        result.registers[0] if not result.isError() else "Error"
                    )
                except ModbusException:
                    values[parameter["code"]] = "Error"
            if progress:
                progress(len(values), total)
        return values

    def _write_values(self, targets, progress=None):
        """Write ``(parameter, raw_value, display)`` triples to the inverter."""
        written, failed = {}, []
        total = len(targets)
        for index, (param, raw_value, display) in enumerate(targets, start=1):
            self._raise_if_cancelled()
            code = param["code"]
            try:
                result = self._write_register(param["address"], raw_value)
                if result.isError():
                    failed.append((code, str(result)))
                    logger.error("Failed to write %s", code)
                else:
                    written[code] = raw_value
                    logger.info("Written %s: %s (from %s)", code, raw_value, display)
            except (ValueError, ModbusException) as exc:
                failed.append((code, str(exc)))
                logger.error("Error writing %s: %s", code, exc)
            if progress:
                progress(index, total)
        return {"written": written, "failed": failed}

    def _prepare_connection(self) -> bool:
        """Validate the serial settings on the UI thread before a task starts."""
        port = self.selected_port.get()
        if not port:
            messagebox.showerror("Serial port", "Select a COM port first")
            return False
        try:
            device_id = int(self.selected_device_id.get())
        except (tk.TclError, ValueError):
            device_id = 0
        if not 1 <= device_id <= 247:
            messagebox.showerror("Modbus ID", "Modbus ID must be between 1 and 247")
            return False
        self._connection = {"port": port, "device_id": device_id}
        return True

    def _open_client(self):
        client = ModbusSerialClient(
            port=self._connection["port"],
            baudrate=self.profile.baudrate,
            parity=self.profile.parity,
            stopbits=self.profile.stopbits,
            bytesize=self.profile.bytesize,
            timeout=self.profile.timeout,
        )
        if not client.connect():
            raise ConnectionError(f"Could not open {self._connection['port']}")
        return client

    def connect(self):
        """Open a client on the calling thread (kept for scripted use)."""
        if not self._prepare_connection():
            return False
        try:
            self.client = self._open_client()
        except ConnectionError as exc:
            messagebox.showerror("Connection", str(exc))
            logger.error("%s", exc)
            return False
        return True

    def _raise_if_cancelled(self):
        if self._cancel.is_set():
            raise TaskCancelled

    # ------------------------------------------------------------------
    # Background tasks
    # ------------------------------------------------------------------
    def _start_task(self, title, work, on_success):
        if self._busy:
            self._set_status("Another operation is still running", "warning")
            return
        if not self._prepare_connection():
            return

        self._cancel.clear()
        self._busy = True
        self._set_busy(True, title)

        def runner():
            client = None
            try:
                client = self._open_client()
                self.client = client
                result = work(self._report_progress)
            except TaskCancelled:
                self.root.after(0, self._task_cancelled, title)
            except Exception as exc:  # surfaced in the UI, never crashes the app
                logger.exception("%s failed", title)
                self.root.after(0, self._task_failed, title, exc)
            else:
                self.root.after(0, self._task_finished, title, result, on_success)
            finally:
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        logger.debug("Closing the Modbus client failed", exc_info=True)

        threading.Thread(target=runner, name="modbus-worker", daemon=True).start()

    def _report_progress(self, done, total):
        self.root.after(0, self._set_progress, done, total)

    def _set_progress(self, done, total):
        if not self._busy:
            return
        self.progress.configure(maximum=max(total, 1), value=done)
        self._set_status(f"{self._task_title} — {done}/{total}")

    def _set_busy(self, busy, title=""):
        self._task_title = title
        state = "disabled" if busy else "normal"
        for widget in self._action_widgets:
            widget.configure(state=state)
        if busy:
            self.progress.configure(value=0, maximum=1)
            self.progress.grid(row=0, column=3, sticky="e", padx=(0, 10))
            self.cancel_button.grid(row=0, column=4, sticky="e", padx=(0, 14))
            self._set_status(f"{title}…")
            self.root.configure(cursor="watch")
        else:
            self.progress.grid_remove()
            self.cancel_button.grid_remove()
            self.root.configure(cursor="")
        self._update_link_indicator(busy=busy)

    def cancel_task(self):
        if self._busy:
            self._cancel.set()
            self._set_status("Cancelling…", "warning")

    def _task_finished(self, title, result, on_success):
        self._busy = False
        self._set_busy(False)
        self.client = None
        on_success(result)

    def _task_cancelled(self, title):
        self._busy = False
        self._set_busy(False)
        self.client = None
        self._set_status(f"{title} cancelled", "warning")

    def _task_failed(self, title, exc):
        self._busy = False
        self._set_busy(False)
        self.client = None
        self._set_status(f"{title} failed: {exc}", "danger")
        messagebox.showerror(title, str(exc))

    # ------------------------------------------------------------------
    # Read / write actions
    # ------------------------------------------------------------------
    def test_connection(self):
        """Read a single register to confirm the link and the Modbus ID."""
        if not self._ensure_auto_revision():
            return
        parameter = self.profile.parameters[0]

        def work(_progress):
            result = self._read_register(parameter["address"])
            if result.isError():
                raise ModbusException(str(result))
            return parameter["code"], result.registers[0]

        self._start_task("Testing link", work, self._link_test_finished)

    def _link_test_finished(self, result):
        code, value = result
        self._set_status(f"Link OK — {code} = {value}", "success")
        self._update_link_indicator(ok=True)

    def read_parameters(self):
        """Read the parameters of the selected group from the inverter."""
        if not self._ensure_auto_revision():
            return
        parameters = self._group_parameters()
        if not parameters:
            messagebox.showwarning("Nothing to read", "This group has no parameters")
            return
        title = f"Reading {self.selected_group.get()}"
        self._start_task(title, lambda progress: self._read_parameter_values(parameters, progress), self._read_finished)

    def read_all_parameters(self):
        """Read every parameter defined by the selected inverter profile."""
        if not self._ensure_auto_revision():
            return
        self._start_task(
            f"Reading all {len(self.profile.parameters)} parameters",
            lambda progress: self._read_parameter_values(self.profile.parameters, progress),
            self._read_finished,
        )

    def _read_finished(self, values):
        for code, value in values.items():
            if value == "Error":
                self.failed_codes.add(code)
                self.loaded_settings.pop(code, None)
            else:
                self.failed_codes.discard(code)
                self.loaded_settings[code] = value
            self.edited_values.pop(code, None)
        successful = sum(1 for value in values.values() if value != "Error")
        self.update_table()
        self._update_link_indicator(ok=successful > 0)
        level = "success" if successful == len(values) else "warning"
        self._set_status(f"Read {successful} of {len(values)} parameters", level)
        logger.info("Read %s/%s parameters for %s", successful, len(values), self.profile.model)

    def save_changes(self):
        """Write the current group back to the inverter."""
        if not self._ensure_auto_revision():
            return
        group = self.selected_group.get()
        self._write_parameters(
            self._group_parameters(),
            f"group {group}" if group != ALL_GROUPS else "all groups",
            edited_only=True,
        )

    def write_all_parameters(self):
        """Write every known writable value back to the inverter."""
        if not self._ensure_auto_revision():
            return
        self._write_parameters(list(self.profile.parameters), "all parameters")

    def _collect_write_targets(self, parameters, edited_only=False):
        """Pair writable parameters with the value shown in the table."""
        targets, problems = [], []
        for param in parameters:
            if param.get("read_only"):
                continue
            code = param["code"]
            if edited_only and code not in self.edited_values:
                continue
            if param.get("write_only_if_edited") and code not in self.edited_values:
                continue
            if code in self.edited_values:
                display = self.edited_values[code]
            elif code in self.loaded_settings:
                display = self._format_value(self.loaded_settings[code], param)
            else:
                continue
            display = str(display).strip()
            if not display or display in ("Error", "BCD Error", "Code Error"):
                continue
            problem = self._value_error(param, display)
            if problem:
                problems.append(f"{code}  —  {problem} (got '{display}')")
                continue
            try:
                targets.append((param, self._encode_value(param, display), display))
            except ValueError as exc:
                problems.append(f"{code}  —  {exc}")
        return targets, problems

    def _write_parameters(self, parameters, scope, edited_only=False):
        targets, problems = self._collect_write_targets(parameters, edited_only)
        if problems:
            shown = "\n".join(problems[:12])
            extra = f"\n…and {len(problems) - 12} more" if len(problems) > 12 else ""
            if not targets:
                messagebox.showerror("Invalid values", f"Nothing can be written:\n\n{shown}{extra}")
                return
            if not messagebox.askyesno(
                "Invalid values",
                f"{_plural(len(problems), 'value')} cannot be written:\n\n{shown}{extra}\n\n"
                f"Skip them and write the remaining {len(targets)}?",
            ):
                return
        if not targets:
            messagebox.showinfo(
                "Nothing to write",
                "No values to write yet. Read the inverter or load a settings file first.",
            )
            return

        edited = sum(1 for param, _, _ in targets if param["code"] in self.edited_values)
        if not messagebox.askyesno(
            "Confirm write",
            f"Write {_plural(len(targets), 'parameter')} of {scope} to {self.profile.model}\n"
            f"on {self.selected_port.get()} (Modbus ID {self.selected_device_id.get()})?\n\n"
            f"{_plural(edited, 'value')} edited in the table.",
        ):
            logger.info("Writing %s cancelled by user", scope)
            return

        self._start_task(
            f"Writing {scope}",
            lambda progress: self._write_values(targets, progress),
            self._write_finished,
        )

    def _write_finished(self, result):
        written, failed = result["written"], result["failed"]
        for code, raw_value in written.items():
            self.loaded_settings[code] = raw_value
            self.edited_values.pop(code, None)
            self.failed_codes.discard(code)
        self.update_table()
        self._update_link_indicator(ok=bool(written))
        if failed:
            details = "\n".join(f"{code}: {message}" for code, message in failed[:12])
            self._set_status(f"Wrote {len(written)}, {len(failed)} failed", "danger")
            messagebox.showerror("Write errors", f"{_plural(len(failed), 'parameter')} failed:\n\n{details}")
        else:
            self._set_status(f"Wrote {_plural(len(written), 'parameter')}", "success")

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------
    def save_to_file(self):
        """Read every writable parameter and store it as JSON."""
        if not self._ensure_auto_revision():
            return
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile=f"{self.profile.key}_settings.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Save settings to file",
        )
        if not file_path:
            logger.info("Saving cancelled by user")
            return

        writable = [p for p in self.profile.parameters if not p.get("read_only")]
        self._start_task(
            "Reading settings to save",
            lambda progress: self._read_parameter_values(writable, progress),
            lambda values: self._write_settings_file(file_path, values),
        )

    def _write_settings_file(self, file_path, settings):
        payload = {
            "format_version": 2,
            "profile": self.profile.key,
            "model": self.profile.model,
            "device_id": int(self.selected_device_id.get()),
            "settings": settings,
        }
        try:
            with open(file_path, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=4)
        except OSError as exc:
            self._set_status(f"Could not save file: {exc}", "danger")
            messagebox.showerror("Save failed", str(exc))
            return
        self._read_finished(settings)
        self._set_status(f"Saved {len(settings)} settings to {Path(file_path).name}", "success")
        logger.info("Settings saved to file: %s", file_path)

    def load_from_file(self):
        """Load settings from a file into the table."""
        file_path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Load settings from file",
        )
        if not file_path:
            logger.info("Loading cancelled by user")
            return

        try:
            with open(file_path, "r", encoding="utf-8") as stream:
                payload = json.load(stream)

            if isinstance(payload, dict) and "settings" in payload:
                profile_key = payload.get("profile")
                if profile_key not in PROFILES:
                    raise ValueError(f"Unknown inverter profile in file: {profile_key}")
                settings = payload["settings"]
                saved_device_id = payload.get("device_id")
            else:
                # Backward compatibility with the original EDS800 flat JSON format.
                profile_key = "eds800"
                settings = payload
                saved_device_id = None

            if profile_key != self.profile.key:
                self.selected_profile_label.set(PROFILES[profile_key].label)
                self.change_profile()
            if saved_device_id is not None and 1 <= int(saved_device_id) <= 247:
                self.selected_device_id.set(int(saved_device_id))
            if not isinstance(settings, dict):
                raise ValueError("Settings payload must be a JSON object")

            known_codes = {parameter["code"] for parameter in self.profile.parameters}
            loaded_settings = {}
            failed_codes = set()
            skipped = 0
            for code, value in settings.items():
                if code not in known_codes:
                    skipped += 1
                    continue
                if value == "Error":
                    failed_codes.add(code)
                    continue
                raw_value = int(value)
                if not 0 <= raw_value <= 65535:
                    raise ValueError(f"Raw value for {code} is outside 0..65535")
                loaded_settings[code] = raw_value

            self.loaded_settings = loaded_settings
            self.failed_codes = failed_codes
            self.edited_values.clear()
            self.update_table()
            note = f", {_plural(skipped, 'unknown code')} ignored" if skipped else ""
            self._set_status(
                f"Loaded {len(loaded_settings)} settings from {Path(file_path).name}{note}", "success"
            )
            logger.info("Settings loaded from file: %s", file_path)
        except Exception as exc:
            self._set_status(f"Could not load file: {exc}", "danger")
            messagebox.showerror("Load failed", str(exc))
            logger.error("Error loading from file: %s", exc)

    # ------------------------------------------------------------------
    # Status bar, preferences and window plumbing
    # ------------------------------------------------------------------
    def _set_status(self, message, level="info"):
        self.status_text.set(message)
        style = {
            "success": "Success.Status.TLabel",
            "warning": "Warning.Status.TLabel",
            "danger": "Danger.Status.TLabel",
        }.get(level, "StatusMuted.TLabel")
        self.status_label.configure(style=style)

    def _update_link_indicator(self, ok=None, busy=None):
        port = self.selected_port.get() or "no port"
        link = f"{self.profile.baudrate} {self.profile.bytesize}{self.profile.parity}{self.profile.stopbits}"
        self.link_settings_label.configure(text=link)
        try:
            device_id = int(self.selected_device_id.get())
        except (tk.TclError, ValueError):
            device_id = "?"
        self.link_text.set(f"{port}  ·  {link}  ·  ID {device_id}")

        if busy or self._busy:
            colour = self.palette.warning
        elif ok is None:
            colour = self.palette.muted if port != "no port" else self.palette.danger
        else:
            colour = self.palette.success if ok else self.palette.danger
        self.link_dot.configure(foreground=colour, background=self.palette.surface)

    def _update_titles(self):
        self.root.title(f"ENC Inverter Parameter Editor — {self.profile.model} ({self.VERSION})")
        self.header_subtitle.configure(
            text=f"{self.profile.model}  ·  {len(self.profile.parameters)} parameters  "
            f"·  {len(self.profile.groups)} groups  ·  v{self.VERSION}"
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
            device_id = self.profile.default_device_id
        payload = {
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
            "Operation running", "A Modbus operation is still running. Close anyway?"
        ):
            return
        self._cancel.set()
        self._save_preferences()
        self.root.destroy()


def main():
    root = tk.Tk()
    InverterParameterEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
