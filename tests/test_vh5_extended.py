"""Reviewed VH5 extensions: physical units, revisions and guarded writes.

All serial interactions are mocks. Nothing in this suite opens a COM port.
"""
from copy import deepcopy
import unittest
from unittest.mock import Mock

from enc_editor import codecs
from enc_editor.catalog import CatalogError, _validate_parameters, load_catalog
from enc_editor.session import Session, parse_settings_file
from enc_editor.transport import create_link

CATALOG = load_catalog()
PROFILE = CATALOG["xinje_vh5"]
P = PROFILE.by_code()


def reply(value):
    result = Mock(registers=[value])
    result.isError.return_value = False
    return result


class ReviewedVH5Tests(unittest.TestCase):
    def setUp(self):
        self.session = Session(PROFILE)

    def targets(self, edits, loaded=None, codes=None):
        self.session.apply_read(loaded or {})
        self.session.edited.update(edits)
        return self.session.collect_write_targets([P[c] for c in codes] if codes else PROFILE.parameters, edited_only=True)

    def test_functional_version_is_not_performance_version(self):
        self.session.apply_read({"P8-15": 3000, "P8-16": 0x3744, "PF-05": 1})
        effective = self.session.effective_parameter(P["PF-05"])
        self.assertEqual(effective["unit"], "")
        self.assertIn("источник", PROFILE.text(effective, "description", "ru").lower())
        self.assertIsNone(self.session.validate(P["PF-05"], "1"))
        self.assertIsNotNone(self.session.validate(P["PF-05"], "2"))
        self.assertEqual(self.session.display(P["P8-15"]), "u30.00")
        self.assertEqual(self.session.display(P["P8-16"]), "u37.44")

    def test_version_decoding_never_guesses_between_two_valid_encodings(self):
        self.assertEqual(codecs.version_number(3744), 3744)
        self.assertEqual(codecs.version_number(0x3744), 3744)
        with self.assertRaises(ValueError):
            codecs.version_number(0x1234)
        self.session.apply_read({"P8-16": 0x1234})
        self.assertEqual(self.session.validate(P["PF-05"], "1").key, "valid.scale_unknown")

    def test_performance_version_alone_cannot_unlock_pf(self):
        self.session.apply_read({"P8-15": 3744, "PF-05": 1})
        self.assertEqual(self.session.context_problem(P["PF-05"]).params["code"], "P8-16")

    def test_functional_version_change_clears_edits_with_different_meaning(self):
        self.session.apply_read({"P8-16": 3744, "PF-05": 0})
        self.session.edited["PF-05"] = "1"
        self.session.apply_write({}, {"P8-16": 3700})
        self.assertNotIn("PF-05", self.session.edited)
        self.assertNotIn("PF-05", self.session.loaded)

    def test_pf_old_new_layouts_and_ai_revision_boundary(self):
        self.session.apply_read({"P8-16": 3700, "PF-03": 125, "PF-05": 1})
        self.assertEqual(self.session.display(P["PF-03"]), "1.25")
        self.assertEqual(self.session.display(P["PF-05"]), "0.01")
        self.assertEqual(self.session.context_problem(P["PF-07"]).key, "valid.context_unsupported")
        self.session.apply_read({"P8-16": 3720, "PF-03": 2, "PF-05": 2})
        self.assertEqual(self.session.display(P["PF-03"]), "2")
        self.assertIsNone(self.session.validate(P["PF-03"], "2"))
        self.session.apply_read({"P8-16": 3744, "PF-03": 1})
        self.assertIsNone(self.session.validate(P["PF-03"], "1"))
        self.assertIsNotNone(self.session.validate(P["PF-03"], "2"))

    def test_context_read_includes_functional_version_and_frequency_ceiling(self):
        codes = {p["code"] for p in self.session.read_parameters_with_context(self.session.group_parameters("PF"))}
        self.assertTrue({"P8-16", "P0-13"} <= codes)
        self.assertNotIn("P8-15", codes)

    def test_all_four_ramp_groups_follow_pc09_but_jog_does_not(self):
        for mode, scale in ((0, 1), (1, 10), (2, 100)):
            for code in ("PC-03", "PC-04", "PC-05", "PC-06", "PC-07", "PC-08"):
                with self.subTest(mode=mode, code=code):
                    targets, problems = self.targets({code: "12"}, {"PC-09": mode})
                    self.assertFalse(problems)
                    self.assertEqual(targets[0].raw_value, 12 * scale)
                    self.session.edited.clear()
            self.assertEqual(codecs.format_value(120, P["PC-01"]), "12.0")
            self.assertIsNone(self.session.validate(P["PC-01"], "12.3"))

    def test_plc_times_have_explicit_s_or_h_and_fixed_tenths(self):
        for unit, label in ((0, "s"), (1, "h")):
            self.session.apply_read({"PB-50": unit, "PB-17": 123})
            self.assertEqual(self.session.display(P["PB-17"]), "12.3")
            self.assertEqual(self.session.effective_parameter(P["PB-17"])["unit"], label)
            self.assertIsNotNone(self.session.validate(P["PB-17"], "12.34"))

    def test_plc_unit_and_time_cannot_be_written_as_ambiguous_batch(self):
        targets, problems = self.targets({"PB-50": "1", "PB-17": "2"}, {"PB-50": 0})
        self.assertEqual([t.code for t in targets], ["PB-50"])
        self.assertEqual(problems[0][1].key, "valid.unit_change")

    def test_unit_change_clears_pending_times_in_old_units(self):
        self.session.apply_read({"PB-50": 0, "PB-17": 20})
        self.session.edited["PB-17"] = "3"
        self.session.apply_write({"PB-50": 1})
        self.assertNotIn("PB-17", self.session.loaded)
        self.assertNotIn("PB-17", self.session.edited)

    def test_signed_ai_voltage_curve_and_precision(self):
        targets, problems = self.targets({"P2-38": "-5.25"}, {"P2-40": 1000})
        self.assertFalse(problems)
        self.assertEqual(targets[0].raw_value, 65011)
        self.assertEqual(codecs.format_value(65011, P["P2-38"]), "-5.25")
        self.assertIsNotNone(self.session.validate(P["P2-38"], "-5.251"))

    def test_confirmed_third_ai_curve_negative_minimum_is_revision_specific(self):
        self.session.apply_read({"P8-16": 3744, "P2-26": 64536, "P2-28": 1000})
        self.assertEqual(self.session.display(P["P2-26"]), "-10.00")
        self.assertIsNone(self.session.validate(P["P2-26"], "-10.00"))
        self.session.edited["P2-26"] = "-5.00"
        targets, problems = self.session.collect_write_targets([P["P2-26"]], edited_only=True)
        self.assertFalse(problems)
        self.assertEqual(targets[0].raw_value, 65036)
        self.session.apply_read({"P8-16": 3730, "P2-26": 0})
        self.assertIsNotNone(self.session.validate(P["P2-26"], "-5.00"))
        self.session.apply_read({"P8-16": 3745, "P2-26": 0})
        self.assertIsNotNone(self.session.validate(P["P2-26"], "-5.00"))

    def test_confirmed_voltage_thresholds_have_one_decimal_place(self):
        for code, raw, shown in (("PC-44", 8100, "810.0"), ("PC-45", 3500, "350.0")):
            self.assertEqual(codecs.format_value(raw, P[code]), shown)
            self.assertEqual(codecs.encode_value(P[code], shown), raw)
            self.assertIsNone(self.session.validate(P[code], shown))

    def test_ai_curve_bounds_are_validated_and_write_order_moves_max_first(self):
        targets, problems = self.targets({"P2-18": "8", "P2-20": "9"}, {"P2-18": 0, "P2-20": 500})
        self.assertFalse(problems)
        self.assertEqual([t.code for t in targets], ["P2-20", "P2-18"])
        self.session.edited.clear()
        targets, problems = self.targets({"P2-18": "6"}, {"P2-20": 500})
        self.assertFalse(targets)
        self.assertTrue(problems)

    def test_s_curve_sum_and_decreasing_peer_write_order(self):
        targets, problems = self.targets({"P4-20": "20", "P4-21": "80"}, {"P4-20": 800, "P4-21": 200})
        self.assertFalse(problems)
        self.assertEqual([t.code for t in targets], ["P4-20", "P4-21"])
        self.session.edited.clear()
        targets, problems = self.targets({"P4-20": "80", "P4-21": "40"}, {"P4-20": 300, "P4-21": 300})
        self.assertFalse(targets)
        self.assertEqual(len(problems), 2)
        self.assertIn("100 - P4-21", PROFILE.range_text(P["P4-20"], "ru"))

    def test_display_bitmasks_are_hex_not_bcd(self):
        for code in ("P8-07", "P8-08", "P8-09"):
            self.assertIsNone(self.session.validate(P[code], "A5F0"))
            self.assertEqual(codecs.encode_value(P[code], "A5F0"), 0xA5F0)
            self.assertEqual(codecs.format_value(0xA5F0, P[code]), "A5F0")

    def test_380v_model_limits_and_documented_power_precision(self):
        for code, valid, invalid in (("PC-44", "810", "400"), ("PC-45", "350", "538"),
                                     ("PC-67", "16.0", "16.1"), ("P8-20", "123.45", "123.456")):
            with self.subTest(code=code):
                self.assertIsNone(self.session.validate(P[code], valid))
                self.assertIsNotNone(self.session.validate(P[code], invalid))

    def test_snapshot_overvoltage_threshold_has_tenths_of_volt(self):
        self.assertEqual(codecs.format_value(7600, P["P7-56"]), "760.0")
        self.assertEqual(codecs.encode_value(P["P7-56"], "760.0"), 7600)
        self.assertIsNone(self.session.validate(P["P7-56"], "760.0"))

    def test_hex_address_mapping_requires_supported_firmware_and_disabled_mapping(self):
        self.session.apply_read({"P8-16": 3744, "A9-00": 0})
        self.assertIsNone(self.session.validate(P["A9-01"], "2000"))
        self.session.apply_read({"A9-00": 1})
        self.assertIsNotNone(self.session.validate(P["A9-01"], "2000"))
        self.session.apply_read({"A9-00": 0, "P8-16": 3700})
        self.assertIsNotNone(self.session.validate(P["A9-01"], "2000"))
        self.assertTrue(P["A9-00"]["read_only"])

    def test_mapping_entries_are_never_replayed_from_backups(self):
        self.session.apply_read({"P8-16": 3744, "A9-00": 0, "A9-01": 0x2000})
        targets, problems = self.session.collect_write_targets(PROFILE.parameters)
        self.assertFalse(problems)
        self.assertNotIn("A9-01", [t.code for t in targets])

    def test_unresolved_parameters_actions_and_disputed_addresses_stay_blocked(self):
        for code in ("P0-05", "P0-20", "P2-16", "P3-11", "P9-02", "PE-00", "P1-35", "A2-35", "P8-02",
                     "P3-01", "P3-15", "P3-16", "AD-12", "AD-15", "PC-43", "P5-05", "A1-11"):
            self.assertTrue(P[code]["read_only"], code)

    def test_backups_preserve_read_only_raw_evidence_but_never_write_it(self):
        values = {"P8-15": 3000, "P8-16": 0x3744, "P2-54": 0x321, "P0-10": 5000}
        loaded = parse_settings_file(self.session.settings_payload(values, 1), CATALOG)
        self.session.apply_read(loaded.values)
        self.assertEqual(self.session.loaded["P2-54"], 0x321)
        targets, problems = self.session.collect_write_targets(PROFILE.parameters)
        self.assertFalse(problems)
        self.assertEqual([t.code for t in targets], ["P0-10"])

    def test_catalog_rejects_bad_variant_ranges_and_references(self):
        for field, value in (("variants_from", "missing"), ("variants", [{"minimum": 20, "maximum": 1}]),
                             ("variants", [{"minimum": 1, "fields": {"maximum": 70000}}]),
                             ("variants", [{"minimum": 1, "fields": {"address": 0}}])):
            parameters = deepcopy(list(PROFILE.parameters))
            next(p for p in parameters if p["code"] == "PF-03")[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(CatalogError):
                _validate_parameters(PROFILE.key, parameters, PROFILE.group_ids, "explicit")


class ContextTransportTests(unittest.TestCase):
    def setUp(self):
        self.session = Session(PROFILE)
        self.link = create_link("mock", 1, PROFILE.link)
        self.link.client = Mock()
        self.link.client.write_register.return_value = reply(0)

    def payload(self, values, edited):
        self.session.apply_read(values)
        self.session.edited.update(edited)
        targets, problems = self.session.collect_write_targets(PROFILE.parameters, edited_only=True)
        self.assertFalse(problems)
        return [t.as_tuple() for t in targets]

    def test_functional_version_is_rechecked_before_pf_write(self):
        payload = self.payload({"P8-15": 3000, "P8-16": 0x3744}, {"PF-05": "1"})
        self.link.client.read_holding_registers.return_value = reply(0x3744)
        result = self.link.write_values(payload)
        self.assertEqual(result["written"], {"PF-05": 1})
        self.link.client.read_holding_registers.assert_called_once_with(address=0x0810, count=1, device_id=1)
        self.link.client.write_register.assert_called_once_with(address=0x0F05, value=1, device_id=1)

    def test_different_firmware_blocks_whole_batch(self):
        payload = self.payload({"P8-16": 0x3744}, {"PF-05": "1", "P0-10": "10"})
        self.link.client.read_holding_registers.return_value = reply(0x3719)
        result = self.link.write_values(payload)
        self.assertFalse(result["written"])
        self.assertEqual(len(result["failed"]), 2)
        self.link.client.write_register.assert_not_called()

    def test_mapping_guard_checks_both_firmware_and_enable_state(self):
        payload = self.payload({"P8-16": 3744, "A9-00": 0}, {"A9-01": "2000"})
        self.link.client.read_holding_registers.side_effect = lambda **kw: reply(3744 if kw["address"] == 0x0810 else 1)
        result = self.link.write_values(payload)
        self.assertFalse(result["written"])
        self.link.client.write_register.assert_not_called()

    def test_changed_plc_time_unit_blocks_write(self):
        payload = self.payload({"PB-50": 0}, {"PB-17": "12.3"})
        self.link.client.read_holding_registers.return_value = reply(1)
        result = self.link.write_values(payload)
        self.assertFalse(result["written"])
        self.link.client.write_register.assert_not_called()


if __name__ == "__main__":
    unittest.main()
