"""Transactional device/PC connection dialog. Cancel leaves the editor untouched."""
import tkinter as tk
from tkinter import font as tkfont, messagebox, ttk

from .. import connection, detection
from ..codecs import READ_ERROR
from .theme import SMALL_FONT
from .tooltip import Tooltip


class ConnectionDialog:
    def __init__(self, app):
        self.app = app
        self.profile = app.profile
        self._testing = False
        self._busy_states = []
        self._test_summary = ""
        self.window = tk.Toplevel(app.root)
        self.window.title(app.t("connection.title"))
        self.window.transient(app.root)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.configure(background=app.palette.bg)
        self.manufacturer = tk.StringVar(self.window, value=self.profile.manufacturer)
        self.model = tk.StringVar(self.window, value=self.profile.label(app.language))
        self.port = tk.StringVar(self.window, value=app.selected_port.get())
        self.device_id = tk.StringVar(self.window, value=app.root.getvar(app.selected_device_id._name))
        self._profile_choices = {}
        self._last_profiles = dict(app._manufacturer_profiles)
        self.variables = {key: tk.StringVar(self.window) for key in
                          ("protocol", "baudrate", "parity", "stopbits", "timeout")}
        self.entries = {}

        frame = ttk.Frame(self.window, style="Card.TFrame", padding=18)
        frame.pack(fill="both", expand=True)
        device = ttk.Frame(frame, style="Card.TFrame")
        device.grid(row=0, column=0, sticky="nsew", padx=(0, 24))
        serial = ttk.Frame(frame, style="Card.TFrame")
        serial.grid(row=0, column=1, sticky="nsew")
        device.columnconfigure(0, weight=1)
        serial.columnconfigure(1, weight=1)

        for row, (key, variable) in enumerate((
            ("manufacturer", self.manufacturer), ("model", self.model),
            ("port", self.port), ("device_id", self.device_id),
        )):
            ttk.Label(device, text=app.t(f"sidebar.{key}"), style="Field.TLabel").grid(
                row=row * 2, column=0, sticky="w", pady=(0 if row == 0 else 7, 3))
            if key == "device_id":
                widget = ttk.Spinbox(device, from_=1, to=247, width=8, textvariable=variable)
            else:
                widget = ttk.Combobox(device, textvariable=variable, state="readonly", width=40)
            widget.grid(row=row * 2 + 1, column=0, sticky="ew" if key != "device_id" else "w")
            setattr(self, f"{key}_entry", widget)
        self.manufacturer_entry["values"] = app.catalog.manufacturers
        self.manufacturer_entry.bind("<<ComboboxSelected>>", self.manufacturer_changed)
        self.model_entry.bind("<<ComboboxSelected>>", self.model_changed)
        self.refresh_button = ttk.Button(device, text="↻", width=3, style="Icon.TButton", command=self.refresh_ports)
        self.refresh_button.grid(row=5, column=1, padx=(5, 0))
        for row, key in enumerate(self.variables):
            ttk.Label(serial, text=app.t(f"connection.{key}"), style="Field.TLabel").grid(
                row=row * 2, column=0, columnspan=2, sticky="w", pady=(0 if row == 0 else 7, 3))
            if key == "timeout":
                widget = ttk.Entry(serial, textvariable=self.variables[key], width=24)
            else:
                widget = ttk.Combobox(serial, textvariable=self.variables[key], state="readonly", width=24)
            widget.grid(row=row * 2 + 1, column=0, columnspan=2, sticky="ew")
            self.entries[key] = widget
        self.entries["parity"]["values"] = ("N", "E", "O")
        self.entries["stopbits"]["values"] = (1, 2)
        self.entries["protocol"].bind("<<ComboboxSelected>>", self.protocol_changed)
        ttk.Label(frame, text=app.t("connection.note"), style="Muted.TLabel", wraplength=690).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(10, 8))
        # Use the empty space below the address, alongside the serial settings.
        # A fixed-height, borderless area keeps results from resizing the dialog.
        line_height = tkfont.Font(root=self.window, font=SMALL_FONT).metrics("linespace")
        self.result_area = ttk.Frame(device, style="Card.TFrame", height=4 * line_height, width=1)
        self.result_area.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.result_area.pack_propagate(False)
        self.result_label = ttk.Label(self.result_area, text="", style="Card.TLabel", font=SMALL_FONT,
                                      wraplength=340, anchor="nw", justify="left", width=1)
        self.result_label.pack(fill="both", expand=True)
        self.result_label.bind("<Configure>", lambda event: self.result_label.configure(wraplength=max(1, event.width)))
        self.result_tooltip = Tooltip(self.result_label, lambda: self.result_label.cget("text"))
        self._show_result(app.t("connection.test_idle"))
        actions = ttk.Frame(frame, style="Card.TFrame")
        actions.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.defaults_button = ttk.Button(actions, text=app.t("connection.defaults"), command=self.defaults)
        self.defaults_button.pack(side="left")
        self.test_button = ttk.Button(actions, text=app.t("action.test_link"), command=self.test)
        self.test_button.pack(side="left", padx=8)
        self.offline_button = ttk.Button(actions, text=app.t("connection.offline"), command=lambda: self.apply(offline=True))
        self.offline_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text=app.t("action.cancel"), command=self.close)
        self.cancel_button.pack(side="right")
        self.apply_button = ttk.Button(actions, text=app.t("connection.apply"), style="Accent.TButton", command=self.apply)
        self.apply_button.pack(side="right", padx=8)
        self._refresh_choices()
        self.refresh_ports()
        self.populate(app.connection_settings)
        for variable in (self.manufacturer, self.model, self.port, self.device_id, *self.variables.values()):
            variable.trace_add("write", self._draft_changed)
        self.window.bind("<Escape>", lambda _event: self.close())
        self.window.update_idletasks()
        width, height = self.window.winfo_reqwidth(), self.window.winfo_reqheight()
        x = max(0, min(app.root.winfo_rootx() + (app.root.winfo_width() - width) // 2,
                       self.window.winfo_screenwidth() - width))
        y = max(0, min(app.root.winfo_rooty() + (app.root.winfo_height() - height) // 2,
                       self.window.winfo_screenheight() - height - 60))
        self.window.geometry(f"+{x}+{y}")
        self.window.grab_set()

    def _refresh_choices(self):
        self._profile_choices = self.app.catalog.labels(self.app.language, self.manufacturer.get())
        self.model_entry["values"] = list(self._profile_choices)
        self.model.set(self.profile.label(self.app.language))
        self.protocols = {self.app.t(f"connection.protocol.{key}"): key
                          for key in self.profile.supported_protocols}
        self.entries["protocol"]["values"] = list(self.protocols)

    def manufacturer_changed(self, _event=None):
        choices = self.app.catalog.labels(self.app.language, self.manufacturer.get())
        key = self._last_profiles.get(self.manufacturer.get())
        if key not in choices.values():
            key = next(iter(choices.values()))
        self._select_profile(self.app.catalog[key])

    def model_changed(self, _event=None):
        key = self._profile_choices.get(self.model.get())
        if key:
            self._select_profile(self.app.catalog[key])

    def _select_profile(self, profile):
        self.profile = profile
        self._last_profiles[profile.manufacturer] = profile.key
        self._refresh_choices()
        self.device_id.set(str(profile.link.device_id))
        self.populate(connection.settings_for(profile, self.app._link_overrides.get(profile.key)))

    def refresh_ports(self):
        self.app.refresh_ports(announce=False)
        # Keep a saved port even when its USB adapter is temporarily unplugged.
        self.port_entry["values"] = list(dict.fromkeys(self.app._ports + ([self.port.get()] if self.port.get() else [])))

    def populate(self, settings):
        self.variables["protocol"].set(self.app.t(f"connection.protocol.{settings.protocol}"))
        for key in ("baudrate", "parity", "stopbits", "timeout"):
            self.variables[key].set(str(getattr(settings, key)))
        rates = self.profile.protocols.get(settings.protocol, {}).get("baudrates", connection.COMMON_BAUDRATES)
        self.entries["baudrate"]["values"] = sorted(set(rates) | {settings.baudrate})
        state = "disabled" if settings.protocol == "danfoss_fc" else "readonly"
        self.entries["parity"].configure(state=state)
        self.entries["stopbits"].configure(state=state)
        self.device_id_entry.configure(to=settings.maximum_device_id)

    def protocol_changed(self, _event=None):
        self.populate(self.profile.link_for_protocol(self.protocols[self.variables["protocol"].get()]))

    def defaults(self):
        self.populate(self.profile.link)

    def test(self):
        if self.app._busy or self._testing:
            return False
        if not self.port.get():
            self._show_result(self.app.t("dialog.select_port.body"), "danger")
            return False
        validated = self._validated_settings(inline=True)
        if validated is None:
            return False
        device_id, settings = validated
        profile, port, catalog = self.profile, self.port.get(), self.app.catalog
        self._test_settings = settings
        self._test_summary = self.app.t(
            "link.summary", port=port,
            link=f"{self.app.t(f'connection.protocol.{settings.protocol}')} · {settings.frame}",
            device_id=device_id,
        )
        self._testing = True
        self._show_result(self._test_summary + "\n" + self.app.t("task.test_link") + "…")

        def work(link, _progress):
            resolved = detection.detect(catalog, profile, link).profile if detection.needs_detection(profile) else profile
            parameter = resolved.parameters[0]
            value = link.read_parameter(parameter)
            if value == READ_ERROR:
                raise ConnectionError(self.app.t("connection.no_response"))
            return resolved, parameter["code"], value

        started = self.app._start_task(
            self.app.t("task.test_link"), work, self._test_finished,
            connection_override=(port, device_id, settings),
            on_error=self._test_failed, on_cancel=self._test_cancelled,
        )
        if not started:
            self._testing = False
            self._show_result(self.app.t("status.busy"), "warning")
        return started

    def _show_result(self, message, level="info"):
        color = {"success": self.app.palette.success, "danger": self.app.palette.danger,
                 "warning": self.app.palette.warning}.get(level, self.app.palette.text)
        self.result_tooltip.hide()
        self.result_label.configure(text=message, foreground=color)

    def _draft_changed(self, *_args):
        if not self._testing:
            self._show_result(self.app.t("connection.test_idle"))

    def _test_finished(self, result):
        profile, code, value = result
        detected = profile.key != self.profile.key
        if detected:
            self.profile = profile
            self._last_profiles[profile.manufacturer] = profile.key
            self._refresh_choices()
            self.populate(self._test_settings)
        self._testing = False
        message = self._test_summary + "\n" + self.app.t("status.link_ok", code=code, value=value)
        if detected:
            message += "\n" + profile.label(self.app.language)
        self._show_result(message, "success")
        self.app._set_status("status.ready")

    def _test_failed(self, message):
        self._testing = False
        self._show_result(self.app.t("connection.test_failed", error=message) + "\n" + self._test_summary, "danger")

    def _test_cancelled(self):
        self._testing = False
        self._show_result(self.app.t("status.cancelled", title=self.app.t("task.test_link")), "warning")

    def set_busy(self, busy):
        if busy and not self._busy_states:
            controls = [self.manufacturer_entry, self.model_entry, self.port_entry, self.device_id_entry,
                        *self.entries.values(), self.refresh_button, self.defaults_button,
                        self.test_button, self.offline_button, self.apply_button]
            self._busy_states = [(widget, str(widget.cget("state"))) for widget in controls]
            for widget, _state in self._busy_states:
                widget.configure(state="disabled")
        elif not busy:
            for widget, state in self._busy_states:
                widget.configure(state=state)
            self._busy_states = []
        self.cancel_button.configure(text=self.app.t("connection.cancel_test" if busy else "action.cancel"))

    def _validation_error(self, message, inline):
        if inline:
            self._show_result(message, "danger")
        else:
            messagebox.showerror(self.app.t("connection.title"), message, parent=self.window)

    def _validated_settings(self, *, inline=False):
        try:
            try:
                baudrate = int(self.variables["baudrate"].get())
                stopbits = int(self.variables["stopbits"].get())
                timeout = float(self.variables["timeout"].get().replace(",", "."))
            except ValueError as exc:
                raise connection.SettingsError("connection.invalid_number") from exc
            overrides = dict(protocol=self.protocols.get(self.variables["protocol"].get(), ""),
                             baudrate=baudrate, parity=self.variables["parity"].get(),
                             stopbits=stopbits, bytesize=8, timeout=timeout)
            settings = connection.settings_for(self.profile, overrides)
        except connection.SettingsError as exc:
            self._validation_error(self.app.t(exc.key), inline)
            return None
        try:
            device_id = int(self.device_id.get())
            if not 1 <= device_id <= settings.maximum_device_id:
                raise ValueError
        except ValueError:
            self._validation_error(self.app.t("connection.device_id_body", maximum=settings.maximum_device_id), inline)
            return None
        return device_id, settings

    def apply(self, *, offline=False):
        if self.app._busy:
            return False
        validated = self._validated_settings()
        if validated is None:
            return False
        device_id, settings = validated
        app = self.app
        changed = (self.profile.key != app.profile.key or self.port.get() != app.selected_port.get()
                   or self.device_id.get() != str(app.root.getvar(app.selected_device_id._name))
                   or settings != app.connection_settings)
        if changed and app.session.edited and not messagebox.askyesno(
            app.t("connection.title"), app.t("connection.discard_edits"), default="no", parent=self.window):
            return False
        self.close()
        app.apply_connection_configuration(self.profile, self.port.get(), device_id, settings, offline=offline)
        return True

    def close(self):
        if self.app._busy:
            self.app.cancel_task()
            if self._testing:
                self._show_result(self.app.t("status.cancelling"), "warning")
            return False
        self.window.grab_release()
        self.window.destroy()
        self.app.connection_dialog = None
