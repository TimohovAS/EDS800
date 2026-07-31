"""Editing state: filtering, dirty cells, write targets and settings files."""

import unittest

from enc_editor.catalog import load_catalog
from enc_editor.session import (
    ALL_GROUPS,
    SETTINGS_FORMAT_VERSION,
    Session,
    parse_settings_file,
)
from enc_editor.transport import contiguous_chunks

CATALOG = load_catalog()


class SessionTableTests(unittest.TestCase):
    def setUp(self):
        self.profile = CATALOG["eds800"]
        self.session = Session(self.profile)
        self.by_code = self.profile.by_code()

    def test_group_selection(self):
        self.assertEqual(
            len(self.session.group_parameters(ALL_GROUPS)), len(self.profile.parameters)
        )
        group = self.session.group_parameters("F0")
        self.assertTrue(group)
        self.assertTrue(all(p["group"] == "F0" for p in group))

    def test_filters(self):
        writable = self.session.visible_parameters(row_filter="writable")
        readonly = self.session.visible_parameters(row_filter="readonly")
        self.assertFalse(any(p.get("read_only") for p in writable))
        self.assertTrue(all(p.get("read_only") for p in readonly))
        self.assertEqual(len(writable) + len(readonly), len(self.profile.parameters))

    def test_search_matches_code_and_description(self):
        self.assertTrue(self.session.visible_parameters(query="f0.01"))
        self.assertTrue(self.session.visible_parameters(query="torque boost"))
        self.assertFalse(self.session.visible_parameters(query="zzzz"))

    def test_search_matches_translated_text(self):
        session = Session(CATALOG["en600_v5"])
        self.assertTrue(session.visible_parameters(query="частота"))
        self.assertTrue(session.visible_parameters(query="frequency"))

    def test_display_prefers_edits_over_read_values(self):
        parameter = self.by_code["F0.01"]
        self.session.apply_read({"F0.01": 5000})
        self.assertEqual(self.session.display(parameter), "50.00")
        self.session.edited["F0.01"] = "45.00"
        self.assertEqual(self.session.display(parameter), "45.00")
        self.assertEqual(self.session.baseline(parameter), "50.00")

    def test_failed_reads_are_shown_and_filterable(self):
        self.session.apply_read({"F0.01": "Error"})
        self.assertIn("F0.01", self.session.failed)
        self.assertEqual(self.session.baseline(self.by_code["F0.01"]), "Error")
        self.assertEqual(
            [p["code"] for p in self.session.visible_parameters(row_filter="errors")],
            ["F0.01"],
        )

    def test_track_edits_clears_values_restored_by_hand(self):
        parameters = [self.by_code["F0.01"], self.by_code["F0.14"]]
        self.session.apply_read({"F0.01": 5000, "F0.14": 40})
        self.session.track_edits(parameters, ["45.00", "4.0"])
        self.assertEqual(self.session.edited, {"F0.01": "45.00"})
        self.session.track_edits(parameters, ["50.00", "4.0"])
        self.assertEqual(self.session.edited, {})

    def test_switching_profiles_keeps_only_known_codes(self):
        session = Session(CATALOG["en600_v5"])
        session.apply_read({"F02.26": 100, "F01.01": 5000})
        session.use_profile(CATALOG["en600_v2"], preserve_values=True)
        self.assertIn("F01.01", session.loaded)
        self.assertNotIn("F02.26", session.loaded)  # V5-only parameter
        session.use_profile(CATALOG["eds800"])
        self.assertEqual(session.loaded, {})


class WriteTargetTests(unittest.TestCase):
    def setUp(self):
        self.profile = CATALOG["en600_v5"]
        self.session = Session(self.profile)
        self.by_code = self.profile.by_code()

    def test_read_only_and_unknown_values_are_skipped(self):
        self.session.apply_read({"F26.00": 3, "F01.01": 5000})
        targets, problems = self.session.collect_write_targets(self.profile.parameters)
        codes = {target.code for target in targets}
        self.assertIn("F01.01", codes)
        self.assertNotIn("F26.00", codes)
        self.assertEqual(problems, [])

    def test_edited_only_writes_just_the_dirty_cells(self):
        self.session.apply_read({"F01.01": 5000, "F01.04": 0})
        self.session.edited["F01.01"] = "45.00"
        targets, _ = self.session.collect_write_targets(
            self.profile.parameters, edited_only=True
        )
        self.assertEqual([target.code for target in targets], ["F01.01"])
        self.assertEqual(targets[0].raw_value, 4500)

    def test_action_parameters_are_never_replayed(self):
        self.session.apply_read({"F00.14": 0x0500, "F00.27": 0})
        targets, _ = self.session.collect_write_targets(self.profile.parameters)
        self.assertNotIn("F00.14", {target.code for target in targets})
        self.session.edited["F00.14"] = "500"
        targets, _ = self.session.collect_write_targets(self.profile.parameters)
        self.assertIn("F00.14", {target.code for target in targets})

    def test_invalid_edits_are_reported_not_written(self):
        self.session.edited["F01.01"] = "999"
        targets, problems = self.session.collect_write_targets(self.profile.parameters)
        self.assertEqual(targets, [])
        self.assertEqual(problems[0][0], "F01.01")
        self.assertEqual(problems[0][1].key, "valid.between")

    def test_failed_reads_are_not_written_back(self):
        self.session.apply_read({"F01.01": "Error"})
        targets, problems = self.session.collect_write_targets(self.profile.parameters)
        self.assertEqual((targets, problems), ([], []))


class SettingsFileTests(unittest.TestCase):
    def test_round_trip(self):
        session = Session(CATALOG["en600_v5"])
        payload = session.settings_payload({"F01.01": 5000}, device_id=7)
        loaded = parse_settings_file(payload, CATALOG)
        self.assertIs(loaded.profile, CATALOG["en600_v5"])
        self.assertEqual(loaded.values, {"F01.01": 5000})
        self.assertEqual(loaded.device_id, 7)

    def test_unknown_codes_are_counted_not_fatal(self):
        payload = self._payload({"F0.01": 5000, "F9.99": 1})
        loaded = parse_settings_file(payload, CATALOG)
        self.assertEqual(loaded.skipped, 1)
        self.assertEqual(loaded.values, {"F0.01": 5000})

    def test_bad_payloads_are_rejected(self):
        for payload in (
            {"F0.01": 5000},  # a bare code -> register mapping is not a settings file
            self._payload({}, profile="nope"),
            self._payload([]),
            self._payload({"F0.01": 70000}),
            {"format_version": 2, "profile": "eds800", "settings": {}},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_settings_file(payload, CATALOG)

    @staticmethod
    def _payload(settings, profile="eds800"):
        return {
            "format_version": SETTINGS_FORMAT_VERSION,
            "profile": profile,
            "settings": settings,
        }


class BatchTests(unittest.TestCase):
    def test_batches_are_contiguous_and_bounded(self):
        for profile in CATALOG:
            limit = profile.link.max_read_registers
            chunks = contiguous_chunks(profile.parameters, limit)
            with self.subTest(profile=profile.key):
                self.assertTrue(chunks)
                self.assertEqual(
                    sum(len(chunk) for chunk in chunks), len(profile.parameters)
                )
                for chunk in chunks:
                    self.assertLessEqual(len(chunk), limit)
                    addresses = [parameter["address"] for parameter in chunk]
                    self.assertEqual(
                        addresses,
                        list(range(addresses[0], addresses[0] + len(addresses))),
                    )


if __name__ == "__main__":
    unittest.main()
