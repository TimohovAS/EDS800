"""Compact workspace and transactional connection setup; no hardware required."""
import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from enc_editor import updates
from enc_editor.session import parse_settings_file
from tests.test_app import CATALOG, TK_AVAILABLE
from tests.test_updates import INSTALLER, RELEASE


@unittest.skipUnless(TK_AVAILABLE, "Tk display is not available")
class CompactWorkspaceTests(unittest.TestCase):
    def setUp(self):
        from enc_editor.ui.app import InverterParameterEditor
        self.root = tk.Tk()
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.patches = [
            patch.object(InverterParameterEditor, "_load_preferences", return_value={"language": "ru"}),
            patch.object(InverterParameterEditor, "_save_preferences"),
            patch("enc_editor.ui.app.serial.tools.list_ports.comports", return_value=[]),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.app = InverterParameterEditor(self.root, catalog=CATALOG, show_initial_connection=False)

    def tearDown(self):
        if self.app.connection_dialog:
            self.app.connection_dialog.close()
        self.root.update_idletasks()
        self.root.destroy()
        self.assertEqual(self.errors, [])

    def test_cancel_leaves_model_address_port_and_edits_untouched(self):
        self.app.selected_port.set("COM7")
        self.app.selected_device_id.set(7)
        self.app.session.apply_read({"F0.01": 5000})
        self.app.session.edited["F0.01"] = "45.00"
        with patch("enc_editor.ui.app.create_link") as factory:
            self.app.open_connection_settings()
            dialog = self.app.connection_dialog
            dialog.manufacturer.set("VACON")
            dialog.manufacturer_changed()
            self.assertEqual(dialog.profile.key, "vacon_nxl")
            self.assertEqual(set(dialog.model_entry["values"]), set(CATALOG.labels("ru", "VACON")))
            dialog.port.set("COM9")
            dialog.device_id.set("255")
            dialog.close()
        factory.assert_not_called()
        self.assertEqual(self.app.profile.key, "eds800")
        self.assertEqual(self.app.selected_port.get(), "COM7")
        self.assertEqual(self.app.selected_device_id.get(), 7)
        self.assertEqual(self.app.session.loaded, {"F0.01": 5000})
        self.assertEqual(self.app.session.edited, {"F0.01": "45.00"})

    def test_file_icons_replace_menu_and_run_the_existing_actions(self):
        self.assertFalse(self.root.cget("menu"))
        self.assertEqual(set(self.app.file_buttons), {"open", "save"})
        self.assertTrue(self.root.bind("<Control-o>"))
        self.assertTrue(self.root.bind("<Control-s>"))
        for button in self.app.file_buttons.values():
            self.assertEqual(str(button.cget("style")), "BrandIcon.TButton")
            self.assertTrue(button.cget("image"))
            self.assertIn(button, self.app._action_widgets)
        with patch("enc_editor.ui.app.filedialog.askopenfilename", return_value="") as picker:
            self.app.file_buttons["open"].invoke()
        picker.assert_called_once()
        self.app._offline = True
        with patch.object(self.app, "_save_cached_to_file") as save, \
                patch("enc_editor.ui.app.create_link") as factory:
            self.app.file_buttons["save"].invoke()
        save.assert_called_once()
        factory.assert_not_called()

    def test_connection_icon_replaces_the_connection_row_and_opens_settings(self):
        self.app.selected_port.set("COM7")
        self.app.selected_device_id.set(7)
        self.app._update_link_indicator()
        button = self.app.connection_button
        self.assertEqual(
            button.master.pack_slaves(),
            [button, self.app.file_buttons["open"], self.app.file_buttons["save"]],
        )
        self.assertEqual(str(button.cget("compound")), "image")
        self.assertTrue(button.cget("image"))
        self.assertIs(self.app.workspace_panes.master.master, self.root.grid_slaves(row=1)[0])
        self.assertIs(self.app.test_button.master, self.root.grid_slaves(row=2)[0])
        self.assertIs(self.app.diagnostics_button.master, self.app.test_button.master)

        for language in ("en", "ru", "sr"):
            self.app.set_language(language)
            tooltip = self.app.connection_tooltip.text()
            self.assertIn(self.app.t("connection.title"), tooltip)
            self.assertIn("COM7", tooltip)
            self.assertIn("9600 8N1", tooltip)
            self.assertIn("ID 7", tooltip)

        with patch("enc_editor.ui.app.create_link") as factory:
            button.invoke()
        factory.assert_not_called()
        self.assertEqual(self.app.connection_dialog.port.get(), "COM7")
        self.assertEqual(self.app.connection_dialog.device_id.get(), "7")

    def test_file_and_connection_icons_are_disabled_while_busy(self):
        self.app._busy = True
        self.app._set_busy(True, "test")
        icons = (*self.app.file_buttons.values(), self.app.connection_button)
        for button in icons:
            self.assertTrue(button.instate(("disabled",)))
        with patch("enc_editor.ui.app.filedialog.askopenfilename") as picker:
            self.app.file_buttons["open"].invoke()
        picker.assert_not_called()
        self.app.connection_button.invoke()
        self.assertIsNone(self.app.connection_dialog)
        self.app._busy = False
        self.app._set_busy(False)
        for button in icons:
            self.assertFalse(button.instate(("disabled",)))

    def test_file_hints_follow_language_and_offline_mode(self):
        for language in ("en", "ru", "sr"):
            self.app.set_language(language)
            self.assertEqual(self.app.file_tooltips["open"].text(), self.app.t("file.open_hint"))
            self.app._offline = False
            self.assertEqual(self.app.file_tooltips["save"].text(), self.app.t("file.backup_hint"))
            self.app._offline = True
            self.assertEqual(self.app.file_tooltips["save"].text(), self.app.t("file.save_hint"))
        self.assertEqual(self.app.file_buttons["open"].cget("text"), self.app.t("action.load"))

    def test_manual_and_theme_icons_keep_their_actions_and_localized_hints(self):
        manual = self.app.manual_button
        theme = self.app.theme_button
        for button in (manual, theme):
            self.assertEqual(str(button.cget("compound")), "image")
            self.assertTrue(button.cget("image"))

        with patch("enc_editor.ui.app.webbrowser.open") as browser:
            manual.invoke()
        browser.assert_called_once_with(self.app.profile.manual_url)

        for language in ("en", "ru", "sr"):
            self.app.set_language(language)
            self.assertEqual(self.app.manual_tooltip.text(), self.app.t("action.manual"))
            self.assertEqual(self.app.theme_tooltip.text(), self.app.t("action.theme_dark"))

        theme.invoke()
        self.assertEqual(self.app.palette.name, "dark")
        self.assertEqual(self.app.theme_tooltip.text(), self.app.t("action.theme_light"))
        self.assertEqual(str(theme.cget("image")[0]), str(self.app._header_images["theme_light"][0]))
        theme.invoke()
        self.assertEqual(self.app.palette.name, "light")
        self.assertEqual(str(theme.cget("image")[0]), str(self.app._header_images["theme_dark"][0]))

    def test_header_icons_and_tooltip_fit_minimum_window_and_both_themes(self):
        self.app._activate_profile(CATALOG["vacon_nxl"])
        self.root.geometry("1000x620")
        self.root.deiconify()
        self.root.update()
        for _theme in range(2):
            for button in (*self.app.file_buttons.values(), self.app.connection_button,
                           self.app.manual_button, self.app.updates_button, self.app.theme_button):
                self.assertTrue(button.winfo_viewable())
                self.assertGreater(button.winfo_rootx(), self.app.header_subtitle.winfo_rootx()
                                   + self.app.header_subtitle.winfo_width())
                self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                     self.root.winfo_rootx() + self.root.winfo_width())
            tooltip = self.app.connection_tooltip
            tooltip.show()
            self.root.update_idletasks()
            self.assertIsNotNone(tooltip.window)
            self.app.toggle_theme()
            self.assertIsNone(tooltip.window)
            self.root.update()
        tooltip.schedule()
        self.assertIsNotNone(tooltip._job)
        tooltip.hide()
        self.assertIsNone(tooltip._job)

    def test_update_requires_download_and_confirmation_and_respects_device_tasks(self):
        self.root.deiconify()
        self.app.update_scope = "/CURRENTUSER"
        with patch.object(updates, "check_update", return_value=RELEASE):
            self.app.updates_button.invoke()
            dialog = self.app.updates_dialog
            self._wait_for_update(dialog)
        self.assertEqual(dialog.window.title(), self.app.t("updates.title"))
        self.assertTrue(dialog.download_button.instate(("!disabled",)))
        self.assertTrue(dialog.install_button.instate(("disabled",)))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / RELEASE.filename
            path.write_bytes(INSTALLER)
            with patch.object(updates, "download_update", return_value=path):
                dialog.download_button.invoke()
                self._wait_for_update(dialog)
            self.app._busy = True
            self.app._set_busy(True, "test")
            self.assertTrue(dialog.install_button.instate(("disabled",)))
            self.app._busy = False
            self.app._set_busy(False)
            with patch("enc_editor.ui.updates.messagebox.askyesno", return_value=False) as confirm, \
                    patch.object(updates, "launch_installer") as launch:
                dialog.install_button.invoke()
                self._wait_for_update(dialog)
                confirm.assert_called_once()
                launch.assert_not_called()
            with patch("enc_editor.ui.updates.messagebox.askyesno", return_value=True), \
                    patch.object(updates, "launch_installer") as launch, patch.object(self.app, "_on_close") as close:
                dialog.install_button.invoke()
                self._wait_for_update(dialog)
                launch.assert_called_once_with(path, RELEASE, language="ru")
                close.assert_called_once()
        dialog.close()

    def _wait_for_update(self, dialog):
        completed = tk.BooleanVar(self.root)

        def poll():
            if dialog._busy:
                self.root.after(10, poll)
            else:
                completed.set(True)

        deadline = self.root.after(3000, lambda: completed.set(False))
        poll()
        if not completed.get():
            self.root.wait_variable(completed)
        self.root.after_cancel(deadline)
        self.assertTrue(completed.get(), "Update dialog did not finish")

    def test_apply_draft_changes_all_connection_fields_without_opening_port(self):
        with patch("enc_editor.ui.app.create_link") as factory:
            self.app.open_connection_settings()
            dialog = self.app.connection_dialog
            dialog.manufacturer.set("VACON")
            dialog.manufacturer_changed()
            dialog.port.set("COM9")
            dialog.device_id.set("255")
            dialog.variables["baudrate"].set("19200")
            self.assertTrue(dialog.apply())
        factory.assert_not_called()
        self.assertIsNone(self.app.connection_dialog)
        self.assertEqual(self.app.profile.key, "vacon_nxl")
        self.assertEqual(self.app.selected_port.get(), "COM9")
        self.assertEqual(self.app.selected_device_id.get(), 255)
        self.assertEqual(self.app.connection_settings.baudrate, 19200)

    def test_changed_target_requires_permission_to_discard_edits(self):
        self.app.session.edited["F0.01"] = "45.00"
        self.app.open_connection_settings()
        dialog = self.app.connection_dialog
        dialog.device_id.set("7")
        with patch("enc_editor.ui.connection.messagebox.askyesno", return_value=False) as confirm:
            self.assertFalse(dialog.apply())
        self.assertEqual(confirm.call_args.kwargs["default"], "no")
        self.assertEqual(self.app.selected_device_id.get(), 1)
        self.assertEqual(self.app.session.edited["F0.01"], "45.00")
        self.assertIs(self.app.connection_dialog, dialog)

    def test_same_profile_new_port_or_address_clears_cached_values(self):
        self.app.session.apply_read({"F0.01": 5000})
        self.app.apply_connection_configuration(self.app.profile, "COM9", 7, self.app.connection_settings)
        self.assertEqual(self.app.session.loaded, {})
        self.app.session.apply_read({"F0.01": 4500})
        self.app.apply_connection_configuration(self.app.profile, "COM9", 8, self.app.connection_settings)
        self.assertEqual(self.app.session.loaded, {})

    def test_offline_transition_preserves_edits_and_blocks_device_actions(self):
        self.app.session.apply_read({"F0.01": 5000})
        self.app.session.edited["F0.01"] = "45.00"
        self.app.open_connection_settings()
        self.assertTrue(self.app.connection_dialog.apply(offline=True))
        self.assertEqual(self.app.session.edited["F0.01"], "45.00")
        with patch("enc_editor.ui.app.create_link") as factory, patch.object(self.app, "open_connection_settings"):
            for action in (self.app.read_parameters, self.app.read_all_parameters,
                           self.app.save_changes, self.app.write_all_parameters, self.app.test_connection):
                action()
        factory.assert_not_called()
        self.assertIn("Без устройства", self.app.connection_tooltip.text())

    def test_offline_save_exports_edits_without_reading_or_marking_them_written(self):
        self.app._offline = True
        self.app.session.apply_read({"F0.01": 5000})
        self.app.session.edited["F0.01"] = "45.00"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "settings.json"
            with patch("enc_editor.ui.app.filedialog.asksaveasfilename", return_value=str(target)), \
                    patch("enc_editor.ui.app.create_link") as factory:
                self.app.save_to_file()
            factory.assert_not_called()
            loaded = parse_settings_file(json.loads(target.read_text(encoding="utf-8")), CATALOG)
            self.assertEqual(loaded.values["F0.01"], 4500)
        self.assertEqual(self.app.session.loaded["F0.01"], 5000)
        self.assertEqual(self.app.session.edited["F0.01"], "45.00")

    def test_offline_save_refuses_invalid_edits(self):
        self.app._offline = True
        self.app.session.edited["F0.01"] = "invalid"
        with patch("enc_editor.ui.app.filedialog.asksaveasfilename") as picker, \
                patch("enc_editor.ui.app.messagebox.showerror") as error:
            self.app.save_to_file()
        picker.assert_not_called()
        error.assert_called_once()

    def test_unplugged_saved_port_is_not_replaced_by_an_unrelated_port(self):
        self.app.preferences["port"] = "COM7"
        self.app._restore_connection_preferences()
        with patch("enc_editor.ui.app.serial.tools.list_ports.comports", return_value=[Mock(device="COM3")]):
            self.app.refresh_ports(announce=False)
        self.assertEqual(self.app.selected_port.get(), "COM7")
        self.app.open_connection_settings()
        self.assertIn("COM7", self.app.connection_dialog.port_entry["values"])

    def test_laptop_layout_shows_all_nxl_groups_and_wraps_toolbar(self):
        self.app._activate_profile(CATALOG["vacon_nxl"])
        self.root.geometry("1100x660")
        self.root.deiconify()
        self.root.update()
        self.assertEqual(len(self.app.group_tree.get_children()), 14)
        self.assertTrue(self.app.group_tree.bbox("FB"))
        self.assertGreater(self.app.group_tree.winfo_height(), 390)
        self.assertGreater(self.app.sheet.winfo_height(), 180)
        self.assertEqual(self.app.toolbar_buttons.grid_info()["row"], 1)
        for button in self.app.text_buttons.values():
            self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                 self.root.winfo_rootx() + self.root.winfo_width())
        self.assertGreater(self.app.details_panel.winfo_height(), 140)
        self.app.open_connection_settings()
        self.root.update()
        self.assertLess(self.app.connection_dialog.window.winfo_height(), 520)
        self.assertLess(self.app.connection_dialog.window.winfo_width(), 1000)

    def test_details_can_expand_resize_collapse_and_restore_height(self):
        self.root.geometry("1100x660")
        self.root.deiconify()
        self.root.update()
        self.assertGreater(self.app.details_panel.winfo_height(), 140)
        self.app.workspace_panes.sashpos(0, self.app.workspace_panes.winfo_height() - 225)
        self.root.update()
        self.app._remember_details_size()
        height = self.app._details_height
        self.app.toggle_details()
        self.root.update()
        self.assertLess(self.app.details_panel.winfo_height(), 60)
        self.app.toggle_details()
        self.root.update()
        self.assertLess(abs(self.app.details_panel.winfo_height() - height), 8)
        restored_height = self.app.details_panel.winfo_height()
        for _cycle in range(5):
            self.app.toggle_details()
            self.root.update()
            self.app.toggle_details()
            self.root.update()
            self.assertEqual(self.app.details_panel.winfo_height(), restored_height)

    def test_details_default_is_open_and_toggle_is_labeled_in_each_language(self):
        self.assertFalse(self.app._details_collapsed)
        self.assertTrue(self.app.details_text.winfo_manager())
        for language in ("en", "ru", "sr"):
            self.app.set_language(language)
            self.assertEqual(self.app.details_toggle.cget("text"), "▼ " + self.app.t("details.hide"))
            self.app.details_toggle.invoke()
            self.assertEqual(self.app.details_toggle.cget("text"), "▲ " + self.app.t("details.show"))
            self.assertTrue(self.app._details_collapsed)
            self.assertTrue(self.app._details_visibility_explicit)
            self.app.details_toggle.invoke()
            self.assertFalse(self.app._details_collapsed)

    def test_upgrade_opens_old_collapsed_default_but_respects_new_explicit_choice(self):
        from enc_editor.ui.app import InverterParameterEditor
        for preferences, expected in (
            ({"details_collapsed": True}, False),
            ({"details_collapsed": True, "details_visibility_explicit": True}, True),
            ({"details_collapsed": False, "details_visibility_explicit": True}, False),
        ):
            with self.subTest(preferences=preferences):
                root = tk.Tk()
                root.withdraw()
                try:
                    with patch.object(InverterParameterEditor, "_load_preferences", return_value=preferences):
                        app = InverterParameterEditor(root, catalog=CATALOG, show_initial_connection=False)
                    self.assertEqual(app._details_collapsed, expected)
                    self.assertEqual(bool(app.details_text.winfo_manager()), not expected)
                finally:
                    root.update_idletasks()
                    root.destroy()

    def test_nxl_description_stays_visible_after_window_resize(self):
        self.app._activate_profile(CATALOG["vacon_nxl"])
        parameter = self.app.profile.by_code()["P2.1.14"]
        self.app._show_details(parameter)
        self.root.deiconify()
        for geometry in ("1100x660", "1250x800", "1000x620", "1100x660"):
            self.root.geometry(geometry)
            self.root.update()
            self.assertFalse(self.app._details_collapsed)
            self.assertTrue(self.app.details_text.winfo_viewable())
            self.assertGreater(self.app.details_panel.winfo_height(), 140)
            self.assertIn(self.app.profile.range_text(parameter, self.app.language),
                          self.app.details_text.get("1.0", "end"))

    def test_first_launch_opens_setup_without_contacting_drive(self):
        from enc_editor.ui.app import InverterParameterEditor
        root = tk.Tk()
        root.withdraw()
        try:
            with patch("enc_editor.ui.app.create_link") as factory:
                app = InverterParameterEditor(root, catalog=CATALOG)
                root.update_idletasks()
                self.assertIsNotNone(app.connection_dialog)
                app.connection_dialog.close()
            factory.assert_not_called()
        finally:
            root.update_idletasks()
            root.destroy()
