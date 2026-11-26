"""Background update checks, a cancellable download, and explicit installation."""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .. import VERSION, updates

logger = logging.getLogger(__name__)


class UpdatesDialog:
    def __init__(self, app):
        self.app = app
        self.release = None
        self.installer = None
        self._busy = False
        self._cancel = threading.Event()
        self._poll_job = None
        self._status = ("updates.current", {"version": VERSION})
        self.window = tk.Toplevel(app.root)
        self.window.withdraw()
        self.window.transient(app.root)
        self.window.geometry("620x340")
        self.window.minsize(560, 275)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", self.close)

        frame = ttk.Frame(self.window, style="Card.TFrame", padding=16)
        frame.pack(fill="both", expand=True)
        self.status = ttk.Label(frame, style="Card.TLabel", wraplength=520)
        self.status.pack(fill="x", pady=(0, 8))
        content = ttk.Frame(frame, style="Card.TFrame")
        content.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(content)
        scroll.pack(side="right", fill="y")
        self.notes = tk.Text(content, state="disabled", wrap="word", yscrollcommand=scroll.set,
                             padx=8, pady=6, relief="flat")
        self.notes.pack(fill="both", expand=True)
        scroll.configure(command=self.notes.yview)
        self.progress = ttk.Progressbar(frame, maximum=100)

        actions = ttk.Frame(frame, style="Card.TFrame")
        actions.pack(fill="x", pady=(10, 0))
        self.check_button = ttk.Button(actions, command=self.check)
        self.check_button.pack(side="left")
        self.download_button = ttk.Button(actions, command=self.download)
        self.download_button.pack(side="left", padx=6)
        self.install_button = ttk.Button(actions, command=self.install, style="Accent.TButton")
        self.install_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, command=self._cancel_download)
        self.cancel_button.pack(side="left", padx=6)
        self.close_button = ttk.Button(actions, command=self.close)
        self.close_button.pack(side="right")
        self.auto_check = tk.BooleanVar(self.window, value=app.auto_check_updates)
        self.auto_check_button = ttk.Checkbutton(
            frame, variable=self.auto_check, command=lambda: app.set_auto_check_updates(self.auto_check.get())
        )
        if app.update_scope is not None:
            self.auto_check_button.pack(anchor="w", pady=(6, 0))

        self.refresh_appearance()
        self.refresh_actions()

    def show(self):
        self.window.deiconify()
        self.window.lift()

    def refresh_appearance(self):
        palette = self.app.palette
        t = self.app.t
        self.window.title(t("updates.title"))
        self.window.configure(background=palette.bg)
        self.notes.configure(background=palette.surface, foreground=palette.text, insertbackground=palette.text)
        for button, key in (
            (self.check_button, "updates.check"), (self.download_button, "updates.download"),
            (self.install_button, "updates.install"), (self.cancel_button, "action.cancel"),
            (self.close_button, "updates.close"), (self.auto_check_button, "updates.auto_check"),
        ):
            button.configure(text=t(key))
        self._set_status(self._status[0], **self._status[1])

    def refresh_actions(self):
        can_install = self.installer is not None and self.app.update_scope is not None and not self.app._busy
        for button, enabled in (
            (self.check_button, not self._busy),
            (self.download_button, not self._busy and self.release is not None and self.installer is None),
            (self.install_button, not self._busy and can_install),
        ):
            button.configure(state="normal" if enabled else "disabled")
        downloading = self._busy and self.progress.winfo_manager() and not self._cancel.is_set()
        self.cancel_button.configure(state="normal" if downloading else "disabled")

    def _set_status(self, key, **params):
        self._status = (key, params)
        self.status.configure(text=self.app.t(key, **params))

    def _set_notes(self, text):
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", text)
        self.notes.configure(state="disabled")

    def _run(self, work, done, error_key):
        events = queue.SimpleQueue()
        self._busy = True
        self.refresh_actions()

        def worker():
            try:
                events.put(("done", work(lambda value: events.put(("progress", value)))))
            except updates.DownloadCancelled:
                events.put(("cancelled", None))
            except Exception as exc:
                logger.debug("Update task failed: %s", exc, exc_info=True)
                events.put(("error", str(exc)))

        def poll():
            self._poll_job = None
            while True:
                try:
                    event, value = events.get_nowait()
                except queue.Empty:
                    self._poll_job = self.window.after(80, poll)
                    return
                if event == "progress":
                    self.progress.configure(value=value)
                    continue
                self._busy = False
                self.progress.pack_forget()
                self.refresh_actions()
                if event == "done":
                    done(value)
                elif self.window.state() == "withdrawn":
                    self.close()
                elif event == "cancelled":
                    self._set_status("updates.cancelled")
                else:
                    self._set_status(error_key)
                    self._set_notes(value)
                return

        self._poll_job = self.window.after(80, poll)
        threading.Thread(target=worker, name="github-update", daemon=True).start()

    def check(self):
        if self._busy:
            return
        self.release = self.installer = None
        self._set_notes("")
        self._set_status("updates.checking")
        self._run(lambda _progress: updates.check_update(), self._checked, "updates.check_failed")

    def _checked(self, release):
        self.release = release
        self.refresh_actions()
        if release is None:
            if self.window.state() == "withdrawn":
                self.close()
            else:
                self._set_status("updates.current", version=VERSION)
            return
        size = f"{release.size / (1024 ** 2):.1f}"
        self._set_status("updates.available", version=release.version, size=size)
        self._set_notes(release.notes)
        self.show()

    def download(self):
        if self._busy or self.release is None or self.installer is not None:
            return
        release = self.release
        self._cancel = cancel = threading.Event()
        self._set_notes(release.notes)
        self._set_status("updates.downloading")
        self.progress.configure(value=0)
        self.progress.pack(fill="x", pady=(8, 0), before=self.check_button.master)
        self._run(lambda progress: updates.download_update(release, cancel=cancel, progress=progress),
                  self._downloaded, "updates.download_failed")

    def _cancel_download(self):
        self._cancel.set()
        self.cancel_button.configure(state="disabled")

    def _downloaded(self, path):
        self.installer = path
        self.refresh_actions()
        if self.app.update_scope is not None:
            self._set_status("updates.downloaded")
        else:
            self._set_status("updates.downloaded_manual")
            self._set_notes(str(path))

    def install(self):
        if self._busy or self.app._busy or self.installer is None or self.app.update_scope is None:
            return
        path, release = self.installer, self.release
        self.installer = None
        self._set_status("updates.verifying")
        self._run(lambda _progress: updates.verify_installer(path, release),
                  self._confirm_install, "updates.download_failed")

    def _confirm_install(self, path):
        self._downloaded(path)
        if self.app._busy:
            return
        t = self.app.t
        if not messagebox.askyesno(t("updates.title"), t("updates.confirm"), default="no", parent=self.window):
            return
        if self.app._busy:
            return
        try:
            updates.launch_installer(path, self.release, language=self.app.language)
        except (OSError, updates.UpdateError) as exc:
            self._set_status("updates.install_failed")
            self._set_notes(str(exc))
            return
        self.app._on_close()

    def close(self, _event=None):
        self._cancel.set()
        if self._poll_job is not None:
            self.window.after_cancel(self._poll_job)
        self.app.updates_dialog = None
        self.window.destroy()
