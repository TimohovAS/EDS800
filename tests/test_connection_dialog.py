"""Inline connection tests use draft settings, mocked links and real Tk widgets."""
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from enc_editor.codecs import READ_ERROR
from enc_editor.detection import Detection
from enc_editor.transport import LinkError, TaskCancelled
from tests.test_app import CATALOG, TK_AVAILABLE


@unittest.skipUnless(TK_AVAILABLE, "Tk display is not available")
class ConnectionDialogTests(unittest.TestCase):
    def setUp(self):
        from enc_editor.ui.app import InverterParameterEditor
        self.root = tk.Tk()
        self.root.withdraw()
        for item in (
            patch.object(InverterParameterEditor, "_load_preferences", return_value={"language": "en", "offline": True}),
            patch.object(InverterParameterEditor, "_save_preferences"),
            patch("enc_editor.ui.app.serial.tools.list_ports.comports", return_value=[]),
        ):
            item.start()
            self.addCleanup(item.stop)
        self.app = InverterParameterEditor(self.root, catalog=CATALOG, show_initial_connection=False)
        self.app.selected_port.set("COM1")
        self.app.session.apply_read({"F0.01": 5000})
        self.app.session.edited["F0.01"] = "45.00"
        self.app.open_connection_settings()
        self.dialog = self.app.connection_dialog
        self.dialog.manufacturer.set("Danfoss")
        self.dialog.manufacturer_changed()
        self.dialog.port.set("COM7")
        self.dialog.device_id.set("7")

    def tearDown(self):
        self.app._busy = False
        self.app._set_busy(False)
        if self.app.connection_dialog:
            self.app.connection_dialog.close()
        self.root.update_idletasks()
        self.root.destroy()

    def start_test(self, *, value=42, open_error=None, close_error=None):
        link = Mock()
        link.read_parameter.return_value = value
        if open_error:
            link.open.side_effect = open_error
        if close_error:
            link.close.side_effect = close_error
        with patch("enc_editor.ui.app.create_link", return_value=link) as factory, \
                patch("enc_editor.ui.app.threading.Thread") as thread:
            self.assertTrue(self.dialog.test())
        return link, thread.call_args.kwargs["target"], factory

    def finish_worker(self, worker):
        with patch("enc_editor.ui.app.logger"), patch("enc_editor.ui.app.messagebox.showerror") as modal:
            worker()  # Execute the captured worker synchronously; callbacks still use Tk.after.
            self.root.update()
        modal.assert_not_called()

    def assert_draft_not_applied(self):
        self.assertEqual(self.app.profile.key, "eds800")
        self.assertEqual(self.app.selected_port.get(), "COM1")
        self.assertEqual(self.app.selected_device_id.get(), 1)
        self.assertTrue(self.app._offline)
        self.assertEqual(self.app.session.loaded, {"F0.01": 5000})
        self.assertEqual(self.app.session.edited, {"F0.01": "45.00"})
        self.assertEqual(self.app._link_overrides, {})

    def result(self):
        return self.dialog.result_label.cget("text")

    def test_success_keeps_dialog_open_and_shows_tested_draft_not_main_settings(self):
        link, worker, factory = self.start_test()
        self.assertEqual(factory.call_args.args[:2], ("COM7", 7))
        self.assertEqual(factory.call_args.args[2].protocol, "danfoss_fc")
        self.assertEqual(factory.call_args.args[2].frame, "9600 8E1")
        self.assertIs(self.app.connection_dialog, self.dialog)
        self.assert_draft_not_applied()
        self.finish_worker(worker)
        link.close.assert_called_once()
        self.assertIs(self.app.connection_dialog, self.dialog)
        self.assertTrue(self.dialog.window.winfo_exists())
        self.assertFalse(self.app._busy)
        self.assertFalse(self.dialog._testing)
        self.assertIn("COM7", self.result())
        self.assertIn("ID 7", self.result())
        self.assertIn("9600 8E1", self.result())
        self.assertIn("Link OK", self.result())
        self.assertIn("42", self.result())
        self.assertEqual(str(self.dialog.result_label.cget("foreground")), self.app.palette.success)
        self.assertEqual(self.app.status_text.get(), self.app.t("status.ready"))
        self.assert_draft_not_applied()

    def test_open_error_is_inline_and_the_port_closes_before_retry_is_enabled(self):
        link, worker, _factory = self.start_test(open_error=LinkError("COM7"))
        worker()
        link.close.assert_called_once()
        self.assertTrue(self.app._busy)  # Tk has not delivered the result yet.
        with patch("enc_editor.ui.app.messagebox.showerror") as modal:
            self.root.update()
        modal.assert_not_called()
        self.assertIs(self.app.connection_dialog, self.dialog)
        self.assertIn(self.app.t("error.open_port", port="COM7"), self.result())
        self.assertEqual(str(self.dialog.result_label.cget("foreground")), self.app.palette.danger)
        self.assertFalse(self.dialog.test_button.instate(("disabled",)))
        self.assert_draft_not_applied()

    def test_error_value_is_not_reported_as_success(self):
        _link, worker, _factory = self.start_test(value=READ_ERROR)
        self.finish_worker(worker)
        self.assertIn(self.app.t("connection.no_response"), self.result())
        self.assertNotIn("Link OK", self.result())
        self.assertFalse(self.app._busy)

    def test_test_locks_all_fields_prevents_reentry_and_restores_fc_frame_locks(self):
        _link, worker, factory = self.start_test()
        for widget in (self.dialog.manufacturer_entry, self.dialog.model_entry, self.dialog.port_entry,
                       self.dialog.device_id_entry, *self.dialog.entries.values(),
                       self.dialog.test_button, self.dialog.refresh_button, self.dialog.apply_button):
            self.assertTrue(widget.instate(("disabled",)))
        self.assertFalse(self.dialog.test())
        self.assertFalse(self.dialog.apply())
        factory.assert_called_once()
        self.finish_worker(worker)
        self.assertEqual(str(self.dialog.port_entry.cget("state")), "readonly")
        self.assertEqual(str(self.dialog.entries["timeout"].cget("state")), "normal")
        self.assertTrue(self.dialog.entries["parity"].instate(("disabled",)))
        self.assertTrue(self.dialog.entries["stopbits"].instate(("disabled",)))

    def test_cancel_waits_for_worker_and_keeps_dialog_open(self):
        link, worker, _factory = self.start_test()
        self.assertFalse(self.dialog.close())
        self.assertTrue(self.app._cancel.is_set())
        self.assertIs(self.app.connection_dialog, self.dialog)
        self.assertIn(self.app.t("status.cancelling"), self.result())
        link.read_parameter.side_effect = TaskCancelled()
        self.finish_worker(worker)
        self.assertIn("cancelled", self.result())
        self.assertFalse(self.app._busy)
        self.assertIs(self.app.connection_dialog, self.dialog)
        self.assert_draft_not_applied()

    def test_changed_draft_clears_old_result_and_can_be_tested_again(self):
        _link, worker, _factory = self.start_test(open_error=LinkError("COM7"))
        self.finish_worker(worker)
        self.dialog.port.set("COM8")
        self.assertEqual(self.result().strip(), self.app.t("connection.test_idle"))
        _link, worker, factory = self.start_test(value=17)
        self.assertEqual(factory.call_args.args[:2], ("COM8", 7))
        self.finish_worker(worker)
        self.assertIn("COM8", self.result())
        self.assertIn("Link OK", self.result())
        self.assert_draft_not_applied()

    def test_invalid_test_inputs_are_reported_inline_without_opening_any_port(self):
        for field, value, expected in (
            (self.dialog.port, "", "dialog.select_port.body"),
            (self.dialog.variables["timeout"], "nan", "connection.invalid_timeout"),
            (self.dialog.device_id, "127", "connection.device_id_body"),
        ):
            with self.subTest(value=value):
                self.dialog.port.set("COM7")
                self.dialog.device_id.set("7")
                self.dialog.variables["timeout"].set("1.0")
                field.set(value)
                with patch("enc_editor.ui.app.create_link") as factory, \
                        patch("enc_editor.ui.connection.messagebox.showerror") as modal:
                    self.assertFalse(self.dialog.test())
                factory.assert_not_called()
                modal.assert_not_called()
                self.assertIn(self.app.t(expected, maximum=126), self.result())
                self.assertFalse(self.dialog._testing)

    def test_auto_revision_updates_only_dialog_and_preserves_test_address_and_serial_settings(self):
        self.dialog.manufacturer.set("ENC")
        self.dialog.manufacturer_changed()
        self.dialog.model.set(CATALOG["en600_auto"].label(self.app.language))
        self.dialog.model_changed()
        self.dialog.device_id.set("7")
        self.dialog.variables["baudrate"].set("19200")
        _link, worker, _factory = self.start_test(value=0)
        with patch("enc_editor.ui.connection.detection.detect",
                   return_value=Detection(CATALOG["en600_v5"], "F02.26", 100)) as detect:
            self.finish_worker(worker)
        detect.assert_called_once()
        self.assertIs(self.app.connection_dialog, self.dialog)
        self.assertEqual(self.dialog.profile.key, "en600_v5")
        self.assertEqual(self.dialog.device_id.get(), "7")
        self.assertEqual(self.dialog.variables["baudrate"].get(), "19200")
        self.assertIn(CATALOG["en600_v5"].label(self.app.language), self.result())
        self.assert_draft_not_applied()

    def test_failure_releases_controls_even_if_link_close_fails(self):
        _link, worker, _factory = self.start_test(close_error=RuntimeError("close failed"))
        self.finish_worker(worker)
        self.assertIn("close failed", self.result())
        self.assertFalse(self.app._busy)
        self.assertFalse(self.dialog.test_button.instate(("disabled",)))

    def test_result_uses_free_space_under_address_without_resizing_dialog(self):
        self.root.deiconify()
        self.root.update()
        self.assertIs(self.dialog.result_area.master, self.dialog.device_id_entry.master)
        self.assertGreaterEqual(self.dialog.result_area.winfo_y(),
                                self.dialog.device_id_entry.winfo_y() + self.dialog.device_id_entry.winfo_height())
        self.assertEqual(int(self.dialog.result_label.cget("borderwidth") or 0), 0)
        height = self.dialog.window.winfo_height()
        self.dialog._show_result("A very long error message. " * 100, "danger")
        self.root.update()
        self.assertEqual(self.dialog.window.winfo_height(), height)
        self.assertLess(height, 490)
        self.assertIn("A very long error message.", self.dialog.result_tooltip.text())
