"""Integration checks for the window itself.

Skipped automatically where Tk cannot open a display.
"""

import tkinter as tk
import unittest

from enc_editor.catalog import load_catalog
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
        self.app = InverterParameterEditor(self.root, catalog=CATALOG)
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

    def test_profile_combobox_lists_every_profile(self):
        self.assertEqual(
            set(self.app.profile_combobox["values"]),
            set(CATALOG.labels(self.app.language)),
        )

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
