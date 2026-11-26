"""NXL ALFIFF20 map, safety restrictions and Modbus wire-address fixtures."""
from dataclasses import replace
import unittest
from unittest.mock import Mock

from enc_editor.catalog import CatalogError, _validate_parameters, load_catalog
from enc_editor import codecs, connection, diagnostics
from enc_editor.i18n import Translator
from enc_editor.session import Session, parse_settings_file
from enc_editor.transport import ModbusLink, create_link

CATALOG = load_catalog()
PROFILE = CATALOG["vacon_nxl"]
PARAMETERS = PROFILE.by_code()


def reply(words=()):
    return Mock(registers=list(words), isError=Mock(return_value=False))


class NXLCatalogueTests(unittest.TestCase):
    def test_identity_link_and_groups(self):
        self.assertEqual(PROFILE.manufacturer, "VACON")
        self.assertIn("NXL00075C5H1SSS00", PROFILE.model)
        self.assertEqual(PROFILE.link.frame, "9600 8N1")
        self.assertEqual(PROFILE.link.max_read_registers, 11)
        self.assertEqual(PROFILE.link.maximum_device_id, 255)
        self.assertIsNone(PROFILE.link.persist_coil)
        self.assertEqual(PROFILE.supported_protocols, ("modbus_rtu",))
        self.assertEqual(len(PROFILE.groups), 13)
        self.assertEqual(len(PROFILE.parameters), 170)
        self.assertEqual(sum(not p["read_only"] for p in PROFILE.parameters), 128)

    def test_ids_not_menu_numbers_determine_wire_addresses(self):
        for code, ident, address in (("V1.1", 1, 0), ("P2.1.1", 101, 100),
                                     ("P2.1.11", 505, 504), ("P2.9.10", 1016, 1015),
                                     ("R3.4", 114, 113), ("FB.2111", 2111, 2110)):
            with self.subTest(code=code):
                self.assertEqual(PARAMETERS[code]["parameter_id"], ident)
                self.assertEqual(PARAMETERS[code]["address"], address)

    def test_bad_or_missing_id_and_wrong_offset_are_rejected(self):
        base = PARAMETERS["P2.1.1"]
        for overrides in ({"parameter_id": None}, {"parameter_id": 0}, {"address": 101}):
            with self.subTest(overrides=overrides), self.assertRaises(CatalogError):
                _validate_parameters("bad", [dict(base, **overrides)], PROFILE.group_ids, "parameter_id")

    def test_aliases_share_one_physical_value_and_are_searchable(self):
        for canonical, alias in (("P2.1.15", "P2.2.12"), ("P2.1.16", "P2.3.5")):
            self.assertIn(alias, PARAMETERS[canonical]["aliases"])
            self.assertNotIn(alias, PARAMETERS)
            rows = Session(PROFILE).visible_parameters(query=alias)
            self.assertEqual([p["code"] for p in rows], [canonical])
        ids = [p["parameter_id"] for p in PROFILE.parameters]
        self.assertEqual(len(ids), len(set(ids)))

    def test_manual_corrections_and_sparse_enums(self):
        self.assertIsNone(codecs.validate_value(PARAMETERS["P2.9.1"], "2"))
        self.assertIsNone(codecs.validate_value(PARAMETERS["P2.2.6"], "0"))
        self.assertEqual(PARAMETERS["P2.4.2"]["allowed_values"], [0, 1, 3])
        self.assertIsNotNone(codecs.validate_value(PARAMETERS["P2.4.2"], "2"))
        self.assertEqual(PARAMETERS["P2.2.5"]["allowed_values"], [10, 11, 20, 21])
        self.assertIsNotNone(codecs.validate_value(PARAMETERS["P2.2.5"], "12"))
        self.assertEqual(PARAMETERS["P3.1"]["allowed_values"], [1, 2, 3])
        self.assertIn("3: Fieldbus", PARAMETERS["P3.1"]["range"])

    def test_unpublished_ids_and_process_commands_are_not_invented(self):
        for code in ("R3.2", "R3.5", "R3.6", "P6.10.2"):
            self.assertNotIn(code, PARAMETERS)
        self.assertFalse(any(2001 <= p["parameter_id"] <= 2011 for p in PROFILE.parameters))
        self.assertTrue(all(p["read_only"] for p in PROFILE.parameters if p["parameter_id"] >= 2101))

    def test_motor_dependent_currents_are_raw_and_readonly(self):
        for code in ("P2.1.5", "P2.1.9", "P2.4.3", "P2.4.8", "P2.7.12"):
            p = PARAMETERS[code]
            self.assertTrue(p["read_only"])
            self.assertEqual((p["scale"], p["unit"]), (1, ""))
            self.assertIn("СЫРОЙ", PROFILE.text(p, "note", "ru"))
        self.assertFalse(PARAMETERS["P2.1.6"]["change_while_running"])

    def test_scaled_and_signed_parameters(self):
        for code, text, raw in (("P2.1.1", "25.00", 2500), ("P2.1.3", "5.0", 50),
                                ("P2.7.7", "-5.0", (-50) & 0xFFFF),
                                ("P2.9.7", "-150.0", (-1500) & 0xFFFF)):
            p = PARAMETERS[code]
            self.assertIsNone(codecs.validate_value(p, text))
            self.assertEqual(codecs.encode_value(p, text), raw)
            self.assertEqual(codecs.format_value(raw, p), text)

    def test_physical_readout_scales_and_explicit_raw_monitoring(self):
        for code, raw, text in (("FB.2104", 2500, "25.00"), ("FB.2106", 76, "7.6"),
                                ("FB.2107", (-123) & 0xFFFF, "-12.3"),
                                ("FB.2110", 540, "540"), ("V1.26", 1000, "100.0")):
            self.assertEqual(codecs.format_value(raw, PARAMETERS[code]), text)
        self.assertEqual((PARAMETERS["V1.4"]["scale"], PARAMETERS["V1.4"]["unit"]), (1, ""))
        self.assertIn("raw", PARAMETERS["V1.4"]["description"])

    def test_dependencies_use_manual_references(self):
        self.assertEqual(PARAMETERS["P2.1.1"]["maximum_from"], "P2.1.2")
        self.assertEqual(PARAMETERS["P2.6.6"]["maximum_from"], "P2.6.4")
        session = Session(PROFILE)
        session.apply_read({"P2.1.1": 0, "P2.1.2": 5000})
        session.edited["P2.1.1"] = "60.00"
        targets, problems = session.collect_write_targets([PARAMETERS["P2.1.1"]])
        self.assertFalse(targets)
        self.assertTrue(problems)

    def test_action_values_are_not_replayed_by_bulk_restore(self):
        session = Session(PROFILE)
        session.apply_read({"P2.6.11": 1, "P3.1": 3, "P3.3": 1, "R3.4": 0, "P2.1.21": 1})
        targets, problems = session.collect_write_targets(PROFILE.parameters)
        self.assertEqual((targets, problems), ([], []))

    def test_russian_names_ranges_and_connection_presets(self):
        for p in PROFILE.parameters:
            self.assertTrue(PROFILE.text(p, "description", "ru"))
            self.assertTrue(PROFILE.range_text(p, "ru"))
        self.assertIn("Гц", PROFILE.range_text(PARAMETERS["P2.1.1"], "ru"))
        for rate in (300, 57600):
            self.assertEqual(connection.settings_for(PROFILE, {"baudrate": rate}).baudrate, rate)
        with self.assertRaises(connection.SettingsError):
            connection.settings_for(PROFILE, {"protocol": "danfoss_fc"})


class NXLTransportTests(unittest.TestCase):
    def setUp(self):
        self.link = create_link("fake", 7, PROFILE.link)
        self.link.client = Mock()
        self.link.client.read_holding_registers.side_effect = lambda **kw: reply([0] * kw["count"])
        self.link.client.write_register.return_value = reply()

    def test_read_first_monitor_uses_function03_address_zero(self):
        self.assertIsInstance(self.link, ModbusLink)
        self.link.read_values([PARAMETERS["V1.1"]])
        self.link.client.read_holding_registers.assert_called_once_with(address=0, count=1, device_id=7)
        self.link.client.write_register.assert_not_called()
        self.link.client.write_coil.assert_not_called()

    def test_batches_do_not_exceed_eleven_registers(self):
        rows = [p for p in PROFILE.parameters if 101 <= p["parameter_id"] <= 113]
        self.link.read_values(rows)
        self.assertEqual([(c.kwargs["address"], c.kwargs["count"])
                          for c in self.link.client.read_holding_registers.call_args_list], [(100, 11), (111, 2)])

    def test_write_parameter_never_uses_control_registers_or_fc51_eeprom_coil(self):
        p = PARAMETERS["P2.1.3"]
        self.assertEqual(self.link.write_values([(p, 50, "5.0")])["written"], {"P2.1.3": 50})
        self.link.client.write_register.assert_called_once_with(address=102, value=50, device_id=7)
        self.link.client.write_coil.assert_not_called()
        self.link.client.write_registers.assert_not_called()

    def test_forced_write_of_readonly_current_is_refused(self):
        result = self.link.write_values([(PARAMETERS["P2.1.9"], 50, "50")])
        self.assertFalse(result["written"])
        self.assertEqual(len(result["failed"]), 1)
        self.link.client.write_register.assert_not_called()
        self.link.client.write_coil.assert_not_called()

    def test_saved_values_keep_signed_bits_and_profile_identity(self):
        session = Session(PROFILE)
        values = {"P2.7.7": (-50) & 0xFFFF, "P2.1.3": 50}
        loaded = parse_settings_file(session.settings_payload(values, 7), CATALOG)
        self.assertEqual(loaded.profile.key, "vacon_nxl")
        self.assertEqual(loaded.values, values)
        self.assertEqual(parse_settings_file(session.settings_payload(values, 255), CATALOG).device_id, 255)


class NXLDiagnosticsTests(unittest.TestCase):
    def decode(self, code, value):
        return diagnostics.decode(PROFILE.diagnostics, code, value, Translator("ru"))

    def test_fault_codes_use_nxl_not_fc51_definitions(self):
        self.assertIn("Сверхток", self.decode("FB.2111", 1))
        self.assertIn("Перегрев преобразователя", self.decode("FB.2111", 14))
        self.assertIn("Неизвестный код ошибки 32", self.decode("FB.2111", 32))
        self.assertEqual(len(PROFILE.diagnostics["tables"]["faults"]), 28)

    def test_live_zero_missing_and_failed_reads_are_distinct(self):
        self.assertEqual(self.decode("FB.2111", 0), "Активных аварий нет")
        self.assertNotEqual(self.decode("FB.2111", None), self.decode("FB.2111", 0))
        self.assertIn("неизвестно", self.decode("FB.2111", codecs.READ_ERROR))

    def test_status_flags_are_nxl_bit_positions_and_reset_is_not_exposed(self):
        text = self.decode("FB.2101", (1 << 3) | (1 << 4))
        self.assertIn("Бит 3: Активна авария", text)
        self.assertIn("Бит 4: Активно предупреждение", text)
        self.assertNotIn("reset", PROFILE.diagnostics)


if __name__ == "__main__":
    unittest.main()
