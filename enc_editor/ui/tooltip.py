"""Delayed, keyboard-accessible help for icon-only controls."""
import tkinter as tk
from tkinter import ttk


class Tooltip:
    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.window = None
        self._job = None
        for event in ("<Enter>", "<FocusIn>"):
            widget.bind(event, self.schedule, add="+")
        for event in ("<Leave>", "<FocusOut>", "<ButtonPress>", "<KeyPress>", "<Destroy>"):
            widget.bind(event, self.hide, add="+")

    def schedule(self, _event=None):
        self.hide()
        self._job = self.widget.after(self.delay, self.show)

    def show(self):
        self.hide()
        if not self.widget.winfo_viewable() or self.widget.instate(("disabled",)):
            return
        window = self.window = tk.Toplevel(self.widget)
        window.overrideredirect(True)
        ttk.Label(window, text=self.text(), style="Card.TLabel", padding=(10, 7),
                  relief="solid", borderwidth=1, wraplength=350).pack()
        window.update_idletasks()
        x = min(self.widget.winfo_rootx(), window.winfo_screenwidth() - window.winfo_reqwidth() - 8)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        if y + window.winfo_reqheight() > window.winfo_screenheight() - 40:
            y = self.widget.winfo_rooty() - window.winfo_reqheight() - 8
        window.geometry(f"+{max(0, x)}+{max(0, y)}")

    def hide(self, _event=None):
        if self._job is not None:
            self.widget.after_cancel(self._job)
            self._job = None
        if self.window is not None:
            self.window.destroy()
            self.window = None
