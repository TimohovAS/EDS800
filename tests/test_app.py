"""Integration checks for the window itself.

Skipped automatically where Tk cannot open a display.
"""

import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from enc_editor.catalog import load_catalog
from enc_editor import connection
from enc_editor.detection import Detection
from enc_editor.session import ALL_GROUPS

CATALOG = load_catalog()

try:
    _probe = tk.Tk()
    _probe.destroy()
    TK_AVAILABLE = True
except Exception:  # pragma: no cover - headless machine
    TK_AVAILABLE = False


@unittest.skipUnless(TK_AVAILABLE, "Tk display is not available")
class EditorWindowTests(unittest.TestCase):
    def setUp(self):
        from enc_editor.ui.app import InverterParameterEditor

        self.root = tk.Tk()
        self.root.withdraw()
        # Do not let a developer's stored preferences steer the test.
        InverterParameterEditor._load_preferences = lambda self: {}
        InverterParameterEditor._save_preferences = lambda self: None
        self.app = InverterParameterEditor(self.root, catalog=CATALOG, show_initial_connection=False)
        self.app.set_language("en")

    def tearDown(self):
        # Let tksheet's pending redraws run, otherwise destroy() logs noise.
        try:
            self.root.update_idletasks()
        except tk.TclError:  # pragma: no cover - window already gone
            pass
        self.root.destroy()

    def test_window_starts_on_the_first_profile(self):
        self.assertEqual(self.app.profile.key, "eds800")
        self.assertEqual(len(self.app.rows), len(self.app.profile.parameters))

    def test_header_and_window_title_follow_the_active_model(self):
        self.assertEqual(self.app.header_title.cget("text"), "EDS800")
        self.assertEqual(self.root.title(), f"Inverter Parameter Editor — EDS800 ({self.app.VERSION})")
        model = CATALOG["vacon_nxl"]
        self.app._activate_profile(model)
        self.app.set_language("ru")
        self.assertEqual(self.app.header_title.cget("text"), model.model)
        self.assertEqual(self.root.title(), f"Inverter Parameter Editor — {model.model} ({self.app.VERSION})")

    def test_eds800_help_and_faults_follow_the_interface_language(self):
        self.app.set_language("ru")
        by_code = self.app.profile.by_code()
        self.app._show_details(by_code["F0.00"])
        self.assertIn("Источник задания частоты", self.app.details_title.cget("text"))
        self.assertIn("11 — Длительность импульсов", self.app.details_text.get("1.0", "end"))
        self.assertEqual(self.app.data[0][1], "Источник задания частоты")
        matches = self.app.session.visible_parameters(ALL_GROUPS, "потенциометр на панели")
        self.assertIn(by_code["F0.00"], matches)

        self.app.session.apply_read({"Fd.00": 17})
        self.app.update_table()
        fault_row = next(i for i, param in enumerate(self.app.rows) if param["code"] == "Fd.00")
        self.assertEqual(self.app.data[fault_row][self.app.VALUE_COLUMN], "17")
        self.assertIn("E017 · Потеря обратной связи ПИД", self.app.data[fault_row][-1])
        self.assertEqual(str(self.app.diagnostics_button.cget("state")), "normal")
        self.app.open_diagnostics(auto_read=False)
        self.assertFalse(self.app.diagnostics_window.reset.winfo_manager())
        self.app.diagnostics_window.apply({"Fd.00": 17})
        self.assertIn(
            "E017 · Потеря обратной связи ПИД",
            self.app.diagnostics_window.text.get("1.0", "end"),
        )
        self.app.set_language("en")
        self.app._show_details(by_code["F0.00"])
        self.assertIn("11 — Pulse width (PWM)", self.app.details_text.get("1.0", "end"))

    def test_profile_combobox_lists_only_selected_manufacturer(self):
        self.app.open_connection_settings()
        self.assertEqual(
            set(self.app.connection_dialog.model_entry["values"]),
            set(CATALOG.labels(self.app.language, "ENC")),
        )
        self.app.connection_dialog.close()

    def test_manufacturer_switch_filters_models_and_clears_values(self):
        self.app.session.apply_read({"F0.01": 5000})
        self.app.selected_manufacturer.set("Danfoss")
        self.app.change_manufacturer()
        self.assertEqual(self.app.profile.key, "danfoss_fc51")
        self.assertEqual(self.app.session.loaded, {})
        self.assertIn("FC · 9600 8E1", self.app.link_text.get())
        self.assertEqual(set(self.app._profile_keys), set(CATALOG.labels("en", "Danfoss")))
        self.app.set_language("ru")
        self.assertEqual(self.app.connection_button.cget("text"), "Настройки подключения")
        self.assertEqual(self.app.selected_manufacturer.get(), "Danfoss")
        self.app._activate_profile(CATALOG["en600_v5"])
        self.assertEqual(self.app.selected_manufacturer.get(), "ENC")

    def test_manufacturer_switch_is_blocked_while_busy(self):
        self.app._busy = True
        self.app.selected_manufacturer.set("Danfoss")
        self.app.change_manufacturer()
        self.assertEqual(self.app.profile.key, "eds800")
        self.assertEqual(self.app.selected_manufacturer.get(), "ENC")

    def test_manufacturer_follows_profile_loaded_from_settings(self):
        self.app._activate_profile(CATALOG["danfoss_fc51"])
        self.assertEqual(self.app.selected_manufacturer.get(), "Danfoss")
        self.assertEqual(self.app.selected_profile_label.get(), CATALOG["danfoss_fc51"].label("en"))

    def test_nxl_manufacturer_groups_and_parameter_id_details(self):
        self.app.selected_manufacturer.set("VACON")
        self.app.change_manufacturer()
        self.assertEqual(self.app.profile.key, "vacon_nxl")
        self.assertEqual(len(self.app.rows), 170)
        self.app.set_language("ru")
        self.assertIn("Основные", self.app.group_tree.item("P2.1", "text"))
        self.assertIn("RTU · 9600 8N1", self.app.link_text.get())
        self.app._show_details(self.app.profile.by_code()["P2.1.1"])
        self.assertIn("ID 101", self.app.details_meta.cget("text"))
        self.app.selected_port.set("fake")
        self.app.selected_device_id.set(255)
        self.assertTrue(self.app._prepare_connection())

    def test_xinje_manufacturer_profile_and_faults(self):
        self.app.selected_manufacturer.set("XINJE")
        self.app.change_manufacturer()
        self.assertEqual(self.app.profile.key, "xinje_vh5")
        self.assertEqual(len(self.app.rows), 548)
        self.assertIn("19200 8E1", self.app.link_text.get())
        self.app.set_language("ru")
        self.assertIn("Основные", self.app.group_tree.item("P0", "text"))
        self.app.open_diagnostics(auto_read=False)
        self.app._diagnostics_finished({"MB.16": 44})
        self.assertIn("Тайм-аут", self.app.diagnostics_window.text.get("1.0", "end"))
        self.assertFalse(self.app.trip_reset_supported)
        self.assertFalse(self.app.diagnostics_window.reset.winfo_manager())
        self.app.diagnostics_window.close()

    def test_xinje_time_rows_unlock_after_selector_is_read(self):
        self.app._activate_profile(CATALOG["xinje_vh5"])
        self.app.set_language("ru")
        parameter = self.app.profile.by_code()["P0-18"]
        row = next(i for i, p in enumerate(self.app.rows) if p["code"] == "P0-18")
        self.assertIn(row, self.app._readonly_rows)
        self.app._show_details(parameter)
        self.assertIn("Сначала прочитайте PC-09", self.app.details_text.get("1.0", "end"))
        self.app._read_finished({"PC-09": 1, "P0-18": 100, "P0-19": 200})
        self.assertNotIn(row, self.app._readonly_rows)
        self.assertEqual(self.app.data[row][2:4], ["10.0", "с"])
        self.app._show_details(parameter)
        self.assertIn(self.app.t("details.writable"), self.app.details_meta.cget("text"))
        self.assertNotIn("Сначала прочитайте PC-09", self.app.details_text.get("1.0", "end"))
        self.app.sheet.set_cell_data(row, self.app.VALUE_COLUMN, "3.5")
        self.app._on_sheet_modified()
        self.assertEqual(self.app.session.edited, {"P0-18": "3.5"})

    def test_xinje_read_group_automatically_reads_pc09(self):
        self.app._activate_profile(CATALOG["xinje_vh5"])
        self.app.selected_group.set("P0")
        self.app._run_after_profile_detection = lambda start: start()
        self.app._start_task = Mock()
        self.app.read_parameters()
        work = self.app._start_task.call_args.args[1]
        link, progress = Mock(), Mock()
        work(link, progress)
        codes = [p["code"] for p in link.read_values.call_args.args[0]]
        self.assertIn("P0-18", codes)
        self.assertIn("P0-19", codes)
        self.assertEqual(codes.count("PC-09"), 1)

    def test_offline_export_preserves_seconds_when_pc09_is_edited(self):
        self.app._activate_profile(CATALOG["xinje_vh5"])
        self.app.session.apply_read({"PC-09": 1, "P0-18": 100, "P0-19": 200})
        self.app.session.edited.update({"PC-09": "2", "P0-18": "3.25"})
        self.app._write_settings_file = Mock()
        with patch("enc_editor.ui.app.filedialog.asksaveasfilename", return_value="not-written.json"):
            self.app._save_cached_to_file()
        values = self.app._write_settings_file.call_args.args[1]
        self.assertEqual(values, {"PC-09": 2, "P0-18": 325, "P0-19": 2000})
        self.assertEqual(self.app.session.loaded["PC-09"], 1)

    def test_time_context_failure_is_explained_in_russian_and_keeps_edits(self):
        from enc_editor.codecs import Problem
        self.app._activate_profile(CATALOG["xinje_vh5"])
        self.app.set_language("ru")
        self.app.session.apply_read({"PC-09": 1, "P0-18": 100})
        self.app.session.edited["P0-18"] = "12"
        with patch("enc_editor.ui.app.messagebox.showerror") as error:
            self.app._write_finished({"written": {}, "context": {"PC-09": 2},
                                     "failed": [("P0-18", Problem("valid.scale_changed", {"code": "PC-09"}))]})
        self.assertIn("Считайте параметры заново", error.call_args.args[1])
        self.assertEqual(self.app.session.edited["P0-18"], "12")
        self.assertNotIn("P0-18", self.app.session.loaded)

    def test_vh5_header_explicitly_reports_partial_support(self):
        self.app._activate_profile(CATALOG["xinje_vh5"])
        self.app.set_language("ru")
        self.assertIn("62 настроек пока не поддерживаются", self.app.header_subtitle.cget("text"))

    def test_vh5_firmware_changes_name_units_and_range_together(self):
        self.app._activate_profile(CATALOG["xinje_vh5"])
        self.app.set_language("ru")
        self.app._read_finished({"P8-15": 3000, "P8-16": 0x3744, "PF-05": 1})
        row = next(i for i, p in enumerate(self.app.rows) if p["code"] == "PF-05")
        self.assertIn("Источник", self.app.data[row][1])
        self.assertEqual(self.app.data[row][2:4], ["1", ""])
        self.assertIn("1: AI", self.app.data[row][5])
        self.app._read_finished({"P8-16": 3700, "PF-05": 1})
        self.assertIn("разгона", self.app.data[row][1])
        self.assertEqual(self.app.data[row][2:4], ["0.01", "с"])
        self.assertIn("650.00", self.app.data[row][5])

    def test_full_backup_reads_versions_and_unsupported_raw_registers(self):
        self.app._activate_profile(CATALOG["xinje_vh5"])
        self.app._run_after_profile_detection = lambda start: start()
        self.app._start_task = Mock()
        with patch("enc_editor.ui.app.filedialog.asksaveasfilename", return_value="not-written.json"):
            self.app.save_to_file()
        work = self.app._start_task.call_args.args[1]
        link = Mock()
        work(link, Mock())
        codes = {p["code"] for p in link.read_values.call_args.args[0]}
        self.assertEqual(len(codes), 548)
        self.assertTrue({"P8-15", "P8-16", "P2-54", "P9-02", "PE-00"} <= codes)

    def test_confirmed_vh5_fields_show_panel_encoding_in_table(self):
        self.app._activate_profile(CATALOG["xinje_vh5"])
        self.app._read_finished({"P8-16": 3744, "P2-54": 801, "P2-55": 0, "P7-39": 11, "P8-22": 11})
        for code, shown in (("P2-54", "H.321"), ("P2-55", "H.000"), ("P7-39", "11"), ("P8-22", "11")):
            row = next(i for i, p in enumerate(self.app.rows) if p["code"] == code)
            self.assertEqual(self.app.data[row][2], shown)
            self.app._show_details(self.app.rows[row])
            self.assertIn(self.app.t("details.writable"), self.app.details_meta.cget("text"))

    def test_offline_backup_preserves_read_only_evidence(self):
        self.app._activate_profile(CATALOG["xinje_vh5"])
        self.app.session.apply_read({"P8-16": 0x3744, "P2-54": 0x321, "P0-10": 5000})
        self.app._write_settings_file = Mock()
        with patch("enc_editor.ui.app.filedialog.asksaveasfilename", return_value="not-written.json"):
            self.app._save_cached_to_file()
        values = self.app._write_settings_file.call_args.args[1]
        self.assertEqual(values["P8-16"], 0x3744)
        self.assertEqual(values["P2-54"], 0x321)

    def test_nxl_diagnostics_uses_own_intro_and_does_not_offer_fc51_reset(self):
        self.app._activate_profile(CATALOG["vacon_nxl"])
        self.app.open_diagnostics(auto_read=False)
        window = self.app.diagnostics_window
        self.app._diagnostics_finished({"FB.2101": 8, "FB.2111": 14})
        text = window.text.get("1.0", "end")
        self.assertIn("Drive overtemperature", text)
        self.assertNotIn("16-90", text)
        self.assertFalse(window.reset.winfo_manager())
        self.assertFalse(self.app.trip_reset_supported)
        with patch("enc_editor.ui.app.create_link") as factory:
            self.app.reset_diagnostics()
        factory.assert_not_called()
        window.close()

    def test_decoded_column_and_details_preserve_numeric_value(self):
        self.app._activate_profile(CATALOG["danfoss_fc51"])
        self.app.set_language("ru")
        self.app.session.apply_read({"16-90": 32})
        self.app.update_table()
        row = next(i for i, p in enumerate(self.app.rows) if p["code"] == "16-90")
        self.assertEqual(self.app.data[row][2], "32")
        self.assertIn("Сверхток", self.app.data[row][6])
        self.app._show_details(self.app.rows[row])
        self.assertIn("Сверхток", self.app.details_text.get("1.0", "end"))
        self.assertEqual(self.app.session.edited, {})

    def test_diagnostics_button_and_window_snapshot(self):
        self.app._activate_profile(CATALOG["en600_v5"])
        self.assertEqual(str(self.app.diagnostics_button.cget("state")), "disabled")
        self.app._activate_profile(CATALOG["danfoss_fc51"])
        self.assertEqual(str(self.app.diagnostics_button.cget("state")), "normal")
        self.app.open_diagnostics(auto_read=False)
        window = self.app.diagnostics_window
        self.assertIn("Not read", window.text.get("1.0", "end"))
        self.app._diagnostics_finished({"16-90": 32, "15-30[0]": 13})
        text = window.text.get("1.0", "end")
        self.assertIn("Overcurrent", text)
        self.assertIn("15-30[9]", text)
        self.app._busy = True
        self.app._set_busy(True)
        self.assertEqual(str(window.reset.cget("state")), "disabled")
        self.app._busy = False
        self.app._set_busy(False)
        self.app._activate_profile(CATALOG["eds800"])
        self.assertIsNone(self.app.diagnostics_window)

    def test_reset_requires_confirmation_and_never_runs_for_other_profiles(self):
        self.app._start_task = Mock()
        with patch("enc_editor.ui.app.messagebox.askyesno", return_value=False) as confirm:
            self.app.reset_diagnostics()
            confirm.assert_not_called()
            self.app._activate_profile(CATALOG["danfoss_fc51"])
            self.app.apply_connection_settings(self.app.profile.link_for_protocol("modbus_rtu"))
            self.app.selected_port.set("COM7")
            self.app.reset_diagnostics()
            confirm.assert_called_once()
        self.app._start_task.assert_not_called()

    def test_connection_dialog_cancel_does_not_change_values_or_open_port(self):
        self.app._activate_profile(CATALOG["danfoss_fc51"])
        self.app.session.apply_read({"1-23": 50})
        with patch("enc_editor.fc_protocol.serial.Serial") as serial_port:
            self.app.open_connection_settings()
            dialog = self.app.connection_dialog
            dialog.variables["protocol"].set("Modbus RTU")
            dialog.protocol_changed()
            self.assertEqual(dialog.variables["baudrate"].get(), "19200")
            self.assertEqual(str(dialog.entries["parity"].cget("state")), "readonly")
            dialog.close()
        serial_port.assert_not_called()
        self.assertEqual(self.app.connection_settings.protocol, "danfoss_fc")
        self.assertEqual(self.app.session.loaded, {"1-23": 50})

    def test_connection_dialog_apply_is_pc_only_and_remembers_per_profile(self):
        self.app._activate_profile(CATALOG["danfoss_fc51"])
        self.app.session.apply_read({"1-23": 50})
        with patch("enc_editor.fc_protocol.serial.Serial") as serial_port:
            self.app.open_connection_settings()
            dialog = self.app.connection_dialog
            dialog.variables["protocol"].set("Modbus RTU")
            dialog.protocol_changed()
            dialog.variables["baudrate"].set("38400")
            dialog.variables["parity"].set("N")
            dialog.variables["stopbits"].set("2")
            dialog.variables["timeout"].set("2,5")
            dialog.apply()
        serial_port.assert_not_called()
        self.assertIsNone(self.app.connection_dialog)
        self.assertEqual(self.app.connection_settings.frame, "38400 8N2")
        self.assertEqual(self.app.connection_settings.timeout, 2.5)
        self.assertEqual(self.app.session.loaded, {})
        self.app._activate_profile(CATALOG["eds800"])
        self.assertEqual(self.app.connection_settings.frame, "9600 8N1")
        self.app._activate_profile(CATALOG["danfoss_fc51"])
        self.assertEqual(self.app.connection_settings.frame, "38400 8N2")

    def test_dialog_rejects_invalid_timeout_and_native_fc_locks_frame(self):
        self.app._activate_profile(CATALOG["danfoss_fc51"])
        self.app.open_connection_settings()
        dialog = self.app.connection_dialog
        self.assertEqual(str(dialog.entries["parity"].cget("state")), "disabled")
        self.assertEqual(str(dialog.entries["stopbits"].cget("state")), "disabled")
        dialog.variables["timeout"].set("nan")
        with patch("enc_editor.ui.connection.messagebox.showerror") as error:
            dialog.apply()
        self.assertTrue(error.called)
        self.assertIsNotNone(self.app.connection_dialog)
        self.assertEqual(self.app.connection_settings.timeout, 1)
        dialog.defaults()
        self.assertEqual(dialog.variables["timeout"].get(), "1.0")
        dialog.close()

    def test_applying_unchanged_settings_does_not_drop_user_edits(self):
        self.app.session.apply_read({"F0.01": 5000})
        self.app.session.edited["F0.01"] = "45.00"
        self.app.apply_connection_settings(self.app.connection_settings)
        self.assertEqual(self.app.session.loaded, {"F0.01": 5000})
        self.assertEqual(self.app.session.edited, {"F0.01": "45.00"})

    def test_fc_address_limit_and_reset_interlock_open_no_port(self):
        self.app._activate_profile(CATALOG["danfoss_fc51"])
        self.app.selected_port.set("not-a-real-port")
        self.app.selected_device_id.set(127)
        with patch("enc_editor.ui.app.messagebox.showerror") as error:
            self.assertFalse(self.app._prepare_connection())
        self.assertIn("126", error.call_args.args[1])
        self.assertFalse(self.app.trip_reset_supported)
        with patch("enc_editor.ui.app.messagebox.showwarning") as warning, patch("enc_editor.ui.app.create_link") as factory:
            self.app.reset_diagnostics()
        warning.assert_called_once()
        factory.assert_not_called()

    def test_worker_uses_effective_serial_overrides(self):
        settings = connection.settings_for(self.app.profile, {"baudrate": 19200, "timeout": 2})
        self.app.apply_connection_settings(settings)
        self.app.selected_port.set("not-a-real-port")
        self.app.selected_device_id.set(7)
        with patch("enc_editor.ui.app.create_link") as factory, patch("enc_editor.ui.app.threading.Thread"):
            self.app._start_task("test", lambda *_: None, lambda *_: None)
        self.assertEqual(factory.call_args.args[:2], ("not-a-real-port", 7))
        self.assertEqual(factory.call_args.args[2].baudrate, 19200)
        self.assertEqual(factory.call_args.args[2].timeout, 2)
        self.app._busy = False
        self.app._set_busy(False)

    def test_revision_detection_preserves_serial_overrides(self):
        self.app._activate_profile(CATALOG["en600_auto"])
        self.app.apply_connection_settings(connection.settings_for(self.app.profile, {"baudrate": 19200, "parity": "E"}))
        self.app.selected_device_id.set(7)
        self.app._detection_finished(Detection(CATALOG["en600_v5"], "F02.26", 100), lambda: None)
        self.assertEqual(self.app.connection_settings.frame, "19200 8E1")
        self.assertEqual(self.app.selected_device_id.get(), 7)

    def test_settings_dialog_is_blocked_while_busy(self):
        self.app._busy = True
        self.app.open_connection_settings()
        self.assertIsNone(self.app.connection_dialog)
        self.app._busy = False

    def test_invalid_id_does_not_crash_diagnostics_window(self):
        self.app._activate_profile(CATALOG["danfoss_fc51"])
        self.app.selected_port.set("COM7")
        self.app.selected_device_id.set("invalid")
        self.app.open_diagnostics(auto_read=False)
        with patch("enc_editor.ui.app.messagebox.showerror") as error:
            self.app.read_diagnostics()
        self.assertEqual(error.call_args.kwargs["parent"], self.app.diagnostics_window.window)
        self.assertFalse(self.app._busy)

    def test_reset_result_is_based_on_readback_not_command_ack(self):
        self.app._activate_profile(CATALOG["danfoss_fc51"])
        cases = (({"16-90": 0, "16-03": 0}, "diag.reset_clear"),
                 ({"16-90": 32, "16-03": 8}, "diag.reset_remaining"),
                 ({"16-90": "Error", "16-03": 0}, "diag.reset_unverified"))
        with patch("enc_editor.ui.app.messagebox.showinfo") as show:
            for values, key in cases:
                self.app._reset_finished(values)
                self.assertEqual(show.call_args.args[1], self.app.t(key))

    def test_group_tree_shows_localized_manual_titles(self):
        self.app._activate_profile(CATALOG["en600_v5"])
        english = self.app.group_tree.item("F20", "text")
        self.assertIn("F20", english)
        self.assertIn(CATALOG["en600_v5"].group_label("F20", "en"), english)

        self.app.set_language("ru")
        russian = self.app.group_tree.item("F20", "text")
        self.assertIn(CATALOG["en600_v5"].group_label("F20", "ru"), russian)
        self.assertNotEqual(russian, english)

    def test_detection_preserves_modbus_id_and_group(self):
        self.app._activate_profile(CATALOG["en600_auto"])
        self.app.selected_device_id.set(7)
        self.app.group_tree.selection_set("F05")
        self.root.update()

        self.app._detection_finished(Detection(CATALOG["en600_v5"], "F02.26", 100), lambda: None)

        self.assertEqual(self.app.profile.key, "en600_v5")
        self.assertEqual(self.app.selected_device_id.get(), 7)
        self.assertEqual(self.app.selected_group.get(), "F05")

    def test_switching_models_resets_id_and_values(self):
        self.app.session.apply_read({"F0.01": 5000})
        self.app._activate_profile(CATALOG["en600_v5"])
        self.assertEqual(self.app.session.loaded, {})
        self.assertEqual(self.app.selected_group.get(), ALL_GROUPS)

    def test_edits_are_tracked_from_the_sheet(self):
        self.app.session.apply_read({"F0.01": 5000})
        self.app.update_table()
        row = next(i for i, p in enumerate(self.app.rows) if p["code"] == "F0.01")
        self.app.sheet.set_cell_data(row, self.app.VALUE_COLUMN, "45.00")
        self.app._on_sheet_modified()
        self.assertEqual(self.app.session.edited, {"F0.01": "45.00"})
        self.assertIn("1 edited", self.app.counts_text.get())

    def test_factory_cell_is_highlighted_only_where_the_value_moved(self):
        self.app.session.apply_read({"F0.01": 4500, "F0.02": 0})
        self.app.update_table()
        rows = {p["code"]: i for i, p in enumerate(self.app.rows)}
        highlighted = self.app.sheet.get_highlighted_cells()

        changed = highlighted[(rows["F0.01"], self.app.DEFAULT_COLUMN)]
        self.assertEqual(changed.bg, self.app.palette.nondefault_bg)
        # Still at its factory value, and never read at all.
        self.assertNotIn((rows["F0.02"], self.app.DEFAULT_COLUMN), highlighted)
        self.assertNotIn((rows["F0.14"], self.app.DEFAULT_COLUMN), highlighted)

        # Typing the factory value back clears the mark without a write.
        self.app.sheet.set_cell_data(rows["F0.01"], self.app.VALUE_COLUMN, "50.00")
        self.app._on_sheet_modified()
        self.assertNotIn(
            (rows["F0.01"], self.app.DEFAULT_COLUMN), self.app.sheet.get_highlighted_cells()
        )

    def test_language_switch_relabels_everything(self):
        self.app._activate_profile(CATALOG["en600_v5"])
        english_button = self.app.text_buttons["action.read_group"].cget("text")
        english_row = self.app.data[0][1]

        self.app.set_language("ru")
        self.assertNotEqual(self.app.text_buttons["action.read_group"].cget("text"), english_button)
        self.assertNotEqual(self.app.data[0][1], english_row)
        self.assertEqual(self.app._unit({"unit": "Hz"}), "Гц")

        self.app.set_language("sr")
        # Serbian has no parameter catalogue, so manual text stays English.
        self.assertEqual(self.app.data[0][1], english_row)

    def test_filters_and_search_survive_a_language_switch(self):
        self.app.row_filter.set(self.app.t("filter.readonly"))
        self.app.update_table()
        readonly_rows = len(self.app.rows)
        self.app.set_language("ru")
        self.assertEqual(self.app._filter_key(), "readonly")
        self.assertEqual(len(self.app.rows), readonly_rows)

    def test_theme_toggle_keeps_the_table(self):
        rows = len(self.app.rows)
        self.app.toggle_theme()
        self.assertEqual(self.app.palette.name, "dark")
        self.assertEqual(len(self.app.rows), rows)

    def test_busy_guard_blocks_new_work(self):
        self.app._busy = True
        started = []
        self.app._run_after_profile_detection(lambda: started.append(True))
        self.assertEqual(started, [])
        self.assertEqual(self.app.status_text.get(), self.app.t("status.busy"))
        self.app._busy = False

    def test_unknown_stored_profile_is_reported_not_swapped_silently(self):
        from enc_editor.ui.app import InverterParameterEditor

        InverterParameterEditor._load_preferences = lambda self: {"profile": "gone_model"}
        root = tk.Tk()
        root.withdraw()
        try:
            app = InverterParameterEditor(root, catalog=CATALOG, show_initial_connection=False)
            app.set_language("en")
            self.assertEqual(app._missing_profile, "gone_model")
            self.assertIn("gone_model", app.status_text.get())
            self.assertIn(app.profile.model, app.status_text.get())
        finally:
            InverterParameterEditor._load_preferences = lambda self: {}
            root.update_idletasks()
            root.destroy()

    def test_details_panel_can_scroll_long_option_lists(self):
        self.app._activate_profile(CATALOG["en600_v5"])
        longest = max(self.app.profile.parameters, key=lambda p: len(p["range"]))
        self.app._show_details(longest)
        self.assertGreater(len(longest["range"]), 500)
        self.assertTrue(self.app.details_text.cget("yscrollcommand"))
        # The scrollbar appears exactly when the text does not fit.
        self.app._on_details_scroll("0.0", "0.4")
        self.assertTrue(self.app.details_scroll.winfo_manager())
        self.app._on_details_scroll("0.0", "1.0")
        self.assertFalse(self.app.details_scroll.winfo_manager())

    def test_settings_error_messages_are_localized(self):
        message = self.app._settings_error_text(ValueError("unknown-profile:nope"))
        self.assertIn("nope", message)
        self.assertEqual(
            self.app._settings_error_text(ValueError("not-a-settings-file")),
            self.app.t("error.not_a_settings_file"),
        )
        self.assertIn(
            "2", self.app._settings_error_text(ValueError("unsupported-version:2"))
        )


if __name__ == "__main__":
    unittest.main()
