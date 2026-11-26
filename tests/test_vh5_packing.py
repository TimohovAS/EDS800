"""Per-field packing and preservation safeguards; all I/O is mocked."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from enc_editor import codecs
from enc_editor.catalog import CatalogError, _validate_parameters, load_catalog
from enc_editor.transport import create_link
from enc_editor.session import Session, parse_settings_file

PROFILE = load_catalog()["xinje_vh5"]


def curve_selector():
    # A test definition, independent of whether the profile is unlocked yet.
    parameter = {"code": "P2-54", "address": 0x236, "unit": ""}
    parameter.update(encoding="bcd", read_only=False, digits=3, digit_chars="0123456789",
                     digit_limits="*55", digit_minimums="011", preserve_mask=0xFF00,
                     reject_high_bits=True, minimum=0, maximum=999, scale=1)
    return parameter


def reply(raw):
    result = Mock(registers=[raw])
    result.isError.return_value = False
    return result


class DigitPackingTests(unittest.TestCase):
    def test_confirmed_snapshot_values_display_like_the_panel(self):
        payload = json.loads((Path(__file__).parent / "fixtures/vh5_3744_readback.json").read_text(encoding="utf-8"))
        catalog = load_catalog()
        loaded = parse_settings_file(payload, catalog)
        session = Session(loaded.profile, loaded=loaded.values)
        for code, panel in payload["panel_confirmed"].items():
            shown = session.display(loaded.profile.by_code()[code])
            with self.subTest(code=code):
                if panel.startswith(("u", "H.")):
                    self.assertEqual(shown, panel)
                else:
                    self.assertEqual(float(shown), float(panel))

    def test_raw_801_is_hex_0321_not_decimal_321(self):
        p = curve_selector()
        self.assertEqual(codecs.format_value(801, p), "321")
        self.assertEqual(codecs.encode_value(p, "321"), 801)
        self.assertEqual(codecs.encode_value(p, "325"), 805)

    def test_invalid_curve_zero_is_not_accepted(self):
        p = curve_selector()
        for text in ("301", "310", "300"):
            self.assertEqual(codecs.validate_value(p, text).key, "valid.digit_minimums")
        for text in ("326", "361"):
            self.assertEqual(codecs.validate_value(p, text).key, "valid.digit_limits")
        for text in ("311", "321", "355", "955"):
            self.assertIsNone(codecs.validate_value(p, text))

    def test_unknown_fourth_nibble_is_not_silently_discarded(self):
        self.assertEqual(codecs.format_value(0x1321, curve_selector()), codecs.BCD_ERROR)

    def test_decimal_11_is_not_valid_bcd(self):
        p = dict(curve_selector(), digits=2)
        self.assertEqual(codecs.format_value(11, p), codecs.BCD_ERROR)
        p.update(encoding="numeric", display_width=2, digit_limits="11")
        p.pop("digit_minimums")
        self.assertEqual(codecs.format_value(11, p), "11")
        self.assertEqual(codecs.encode_value(p, "11"), 11)

    def test_catalog_validates_preservation_mask_and_digit_minima(self):
        for field, value in (("preserve_mask", -1), ("preserve_mask", 65536),
                             ("digit_minimums", "00"), ("digit_minimums", "0ZZZ"),
                             ("digit_minimums", "FFFF")):
            parameters = deepcopy(list(PROFILE.parameters))
            p = next(p for p in parameters if p["code"] == "P8-07")
            p["digit_limits"] = "7777"
            p[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(CatalogError):
                _validate_parameters(PROFILE.key, parameters, PROFILE.group_ids, "explicit")


class ReservedDigitTransportTests(unittest.TestCase):
    def setUp(self):
        self.link = create_link("mock", 1, PROFILE.link)
        self.link.client = Mock()
        self.link.client.write_register.return_value = reply(0)

    def test_known_low_digits_can_change_without_changing_reserved_high_digits(self):
        self.link.client.read_holding_registers.return_value = reply(0x321)
        result = self.link.write_values([(curve_selector(), 0x325, "325")])
        self.assertEqual(result["written"], {"P2-54": 0x325})
        self.link.client.read_holding_registers.assert_called_once_with(address=0x236, count=1, device_id=1)
        self.link.client.write_register.assert_called_once_with(address=0x236, value=0x325, device_id=1)

    def test_reserved_digit_mismatch_blocks_entire_batch_before_any_write(self):
        self.link.client.read_holding_registers.return_value = reply(0x321)
        result = self.link.write_values([
            (PROFILE.by_code()["P0-10"], 5000, "50.00"), (curve_selector(), 0x125, "125")])
        self.assertFalse(result["written"])
        self.assertEqual(len(result["failed"]), 2)
        self.assertEqual(result["failed"][0][1].key, "valid.preserved_bits")
        self.link.client.write_register.assert_not_called()
        self.link.client.write_coil.assert_not_called()

    def test_failed_live_read_never_clears_reserved_bits(self):
        result = Mock()
        result.isError.return_value = True
        self.link.client.read_holding_registers.return_value = result
        response = self.link.write_values([(curve_selector(), 0x325, "325")])
        self.assertFalse(response["written"])
        self.link.client.write_register.assert_not_called()


class ConfirmedProfilePackingTests(unittest.TestCase):
    def setUp(self):
        self.parameters = PROFILE.by_code()
        self.session = Session(PROFILE, loaded={"P8-16": 3744, "P2-54": 801,
                                                "P2-55": 0, "P7-39": 11, "P8-22": 11})
        self.link = create_link("mock", 1, PROFILE.link)
        self.link.client = Mock()
        self.link.client.write_register.return_value = reply(0)
        self.live = {0x0810: 3744, 0x0236: 801, 0x0237: 0, 0x0727: 11, 0x0816: 11}
        self.link.client.read_holding_registers.side_effect = lambda **kw: reply(self.live[kw["address"]])

    def payload(self, edits):
        self.session.edited.update(edits)
        targets, problems = self.session.collect_write_targets(PROFILE.parameters, edited_only=True)
        self.assertFalse(problems)
        return [target.as_tuple() for target in targets]

    def test_confirmed_hex_and_decimal_fields_have_different_wire_values(self):
        for code, expected in (("P2-54", "H.321"), ("P7-39", "11"), ("P8-22", "11")):
            self.assertEqual(self.session.display(self.parameters[code]), expected)
        result = self.link.write_values(self.payload({"P2-54": "H.325", "P7-39": "10", "P8-22": "21"}))
        self.assertEqual(result["written"], {"P2-54": 0x325, "P7-39": 10, "P8-22": 21})
        self.assertFalse(result["failed"])
        self.assertEqual({call.kwargs["address"]: call.kwargs["value"]
                          for call in self.link.client.write_register.call_args_list},
                         {0x0236: 0x325, 0x0727: 10, 0x0816: 21})

    def test_hex_entry_accepts_exact_panel_spelling_or_manual_suffix(self):
        p = self.session.effective_parameter(self.parameters["P2-54"])
        for text in ("H.321", "H. 321", "321H", "321"):
            with self.subTest(text=text):
                self.assertIsNone(codecs.validate_value(p, text))
                self.assertEqual(codecs.encode_value(p, text), 801)

    def test_reserved_curve_digit_cannot_change_even_in_an_otherwise_valid_batch(self):
        result = self.link.write_values(self.payload({"P2-54": "H.125", "P7-39": "10"}))
        self.assertFalse(result["written"])
        self.assertEqual(result["failed"][0][1].key, "valid.preserved_bits")
        self.link.client.write_register.assert_not_called()
        self.link.client.write_coil.assert_not_called()

    def test_historical_curve_tens_digit_is_preserved_on_3744(self):
        result = self.link.write_values(self.payload({"P2-54": "H.315"}))
        self.assertFalse(result["written"])
        self.assertEqual(result["failed"][0][1].key, "valid.preserved_bits")
        self.link.client.write_register.assert_not_called()

    def test_below_minimum_selector_only_changes_documented_bit_zero(self):
        for current, requested in ((0, "H.001"), (0xA10, "H.A11")):
            self.live[0x0237] = current
            result = self.link.write_values(self.payload({"P2-55": requested}))
            self.assertEqual(result["written"], {"P2-55": current | 1})
        result = self.link.write_values(self.payload({"P2-55": "H.A01"}))
        self.assertFalse(result["written"])
        self.assertEqual(result["failed"][0][1].key, "valid.preserved_bits")
        self.assertIsNotNone(self.session.validate(self.parameters["P2-55"], "H.002"))

    def test_unknown_live_decimal_code_blocks_entire_batch(self):
        self.live[0x0727] = 12
        result = self.link.write_values(self.payload({"P2-54": "H.325", "P7-39": "10"}))
        self.assertFalse(result["written"])
        self.assertEqual(result["failed"][0][1].key, "valid.live_value")
        self.link.client.write_register.assert_not_called()

    def test_changed_revision_blocks_entire_batch(self):
        self.live[0x0810] = 3745
        result = self.link.write_values(self.payload({"P2-54": "H.325", "P7-39": "10"}))
        self.assertFalse(result["written"])
        self.assertEqual(result["failed"][0][1].key, "valid.scale_changed")
        self.link.client.write_register.assert_not_called()

    def test_unconfirmed_revisions_stay_locked(self):
        for version in (None, 3730, 3745, 0x1234):
            session = Session(PROFILE, loaded={} if version is None else {"P8-16": version})
            for code, text in (("P2-54", "H.321"), ("P2-55", "H.000"), ("P7-39", "11"), ("P8-22", "11")):
                with self.subTest(version=version, code=code):
                    self.assertIsNotNone(session.validate(self.parameters[code], text))

    def test_backup_values_are_preserved_but_not_replayed_without_edits(self):
        payload = self.session.settings_payload(self.session.loaded, 1)
        loaded = parse_settings_file(payload, load_catalog())
        session = Session(loaded.profile, loaded=loaded.values)
        self.assertEqual(session.loaded, self.session.loaded)
        targets, problems = session.collect_write_targets(PROFILE.parameters)
        self.assertFalse(problems)
        self.assertFalse(targets)


if __name__ == "__main__":
    unittest.main()
