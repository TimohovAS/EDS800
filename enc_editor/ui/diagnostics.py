"""A keypad-independent snapshot of current diagnostics and fault history."""
from datetime import datetime
import tkinter as tk
from tkinter import ttk

from .. import diagnostics
from .theme import FONT


class DiagnosticsWindow:
    def __init__(self, app):
        self.app = app
        self.values = {}
        self.updated = None
        self.window = tk.Toplevel(app.root)
        self.window.transient(app.root)
        self.window.title(app.t("diag.title"))
        self.window.geometry("940x650")
        self.window.minsize(680, 430)
        self.window.configure(background=app.palette.bg)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(self.window, style="App.TFrame", padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        self.heading = ttk.Label(frame, text="", style="Card.TLabel", wraplength=850)
        self.heading.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        intro = app.profile.diagnostics.get("intro", {})
        intro_text = intro.get(app.language) or intro.get("en") or app.t("diag.history_note")
        history_note = ttk.Label(frame, text=intro_text, style="Muted.TLabel",
                                 wraplength=850)
        if not app.trip_reset_supported and app.profile.diagnostics.get("reset"):
            history_note.configure(text=app.t("diag.history_note") + "\n\n" + app.t("diag.reset_fc_unavailable"))
        history_note.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        frame.bind("<Configure>", lambda event: [
            label.configure(wraplength=max(200, event.width - 12))
            for label in (self.heading, history_note)
        ])
        self.text = tk.Text(frame, wrap="word", font=FONT, relief="flat", padx=12, pady=10,
                            background=app.palette.surface, foreground=app.palette.text)
        self.text.grid(row=2, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.text.yview)
        scroll.grid(row=2, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scroll.set)
        self.text.tag_configure("heading", font=(FONT[0], FONT[1], "bold"))
        actions = ttk.Frame(frame, style="App.TFrame")
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.refresh = ttk.Button(actions, text=app.t("diag.refresh"), command=app.read_diagnostics)
        self.refresh.pack(side="left")
        self.reset = ttk.Button(actions, text=app.t("diag.reset"), style="Danger.TButton",
                                command=app.reset_diagnostics)
        if app.profile.diagnostics.get("reset"):
            self.reset.pack(side="left", padx=10)
        self.cancel = ttk.Button(actions, text=app.t("action.cancel"), command=app.cancel_task)
        self.cancel.pack(side="left")
        self.done = ttk.Button(actions, text=app.t("diag.close"), command=self.close)
        self.done.pack(side="right")
        self.render()
        self.set_busy(False)
        self.window.grab_set()

    def close(self):
        if self.app._busy:
            return
        self.window.grab_release()
        self.window.destroy()
        self.app.diagnostics_window = None

    def set_busy(self, busy):
        for button in (self.refresh, self.done):
            button.configure(state="disabled" if busy else "normal")
        self.reset.configure(state="normal" if not busy and self.app.trip_reset_supported else "disabled")
        self.cancel.configure(state="normal" if busy else "disabled")

    def clear(self):
        self.values = {}
        self.updated = None
        self.render()

    def apply(self, values):
        self.values = values
        self.updated = datetime.now().strftime("%H:%M:%S")
        self.render()

    def render(self):
        app = self.app
        snapshot = app.t("diag.snapshot", time=self.updated) if self.updated else app.t("diag.not_read")
        self.heading.configure(text=f"{app.profile.model} · {app.selected_port.get()} · "
                               f"ID {app.root.getvar(app.selected_device_id._name)}\n{snapshot}")
        by_code = app.profile.by_code()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for code in app.profile.diagnostics["fields"]:
            parameter = by_code[code]
            raw = self.values.get(code)
            self.text.insert("end", f"{code} — {app._text(parameter, 'description')}\n", "heading")
            if type(raw) is int:
                width = parameter.get("data_bits", 16) // 4
                self.text.insert("end", f"{raw}  (0x{raw:0{width}X})\n")
            decoded = diagnostics.decode(app.profile.diagnostics, code, raw, app.t)
            self.text.insert("end", decoded.replace("; ", "\n") + "\n\n")
        self.text.configure(state="disabled")
