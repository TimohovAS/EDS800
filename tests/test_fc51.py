"""FC 51 wire-format checks without a connected motor drive."""
import unittest
from unittest.mock import Mock

from enc_editor import codecs
from enc_editor.catalog import CatalogError, LinkSettings, _validate_parameters, load_catalog
from enc_editor.session import Session, parse_settings_file
from enc_editor.transport import ModbusLink, TaskCancelled, contiguous_chunks

CATALOG = load_catalog()
PROFILE = CATALOG["danfoss_fc51"]
PARAMETERS = PROFILE.by_code()


def reply(words=(), error=False):
    return Mock(registers=list(words), isError=Mock(return_value=error))


class FC51CatalogueTests(unittest.TestCase):
    def test_manufacturer_filter_and_documented_link(self):
        self.assertEqual(CATALOG.manufacturers, ("ENC", "Danfoss", "VACON", "XINJE"))
        self.assertEqual(list(CATALOG.labels("ru", "Danfoss").values()), ["danfoss_fc51"])
        self.assertEqual(PROFILE.link.frame, "9600 8E1")
        self.assertEqual(PROFILE.link.protocol, "danfoss_fc")
        self.assertEqual(PROFILE.link_for_protocol("modbus_rtu").frame, "19200 8E1")
        self.assertEqual(PROFILE.link.index_register, 8)
        self.assertEqual(PROFILE.link.persist_coil, 64)

    def test_documented_addresses_and_widths(self):
        self.assertEqual(PARAMETERS["0-03"]["address"], 29)
        self.assertEqual(PARAMETERS["3-03"]["address"], 3029)
        self.assertEqual(PARAMETERS["3-03"]["register_count"], 2)
        self.assertEqual(PARAMETERS["3-03"]["scale"], 1000)
        self.assertEqual(PARAMETERS["1-24"]["scale"], 100)
        self.assertEqual(PARAMETERS["15-43"]["register_count"], 10)
        self.assertEqual(len(PROFILE.parameters), 334)

    def test_arrays_have_distinct_codes_and_explicit_indices(self):
        for code, count in (("3-10", 8), ("1-55", 6), ("4-61", 2), ("13-51", 20), ("15-30", 10)):
            rows = [p for p in PROFILE.parameters if p["code"].startswith(code + "[")]
            self.assertEqual([p["array_index"] for p in rows], list(range(count)))
            self.assertEqual(len({p["address"] for p in rows}), 1)
        self.assertTrue(PARAMETERS["8-43[0]"]["read_only"])
        self.assertTrue(PARAMETERS["8-43[1]"]["read_only"])

    def test_sparse_enum_and_numeric_resolution(self):
        self.assertIsNone(codecs.validate_value(PARAMETERS["1-00"], "3"))
        self.assertEqual(codecs.validate_value(PARAMETERS["1-00"], "2").key, "valid.options")
        self.assertEqual(codecs.validate_value(PARAMETERS["1-23"], "50.5").key, "valid.resolution")
        for text in ("NaN", "inf", "-inf"):
            self.assertEqual(codecs.validate_value(PARAMETERS["3-03"], text).key, "valid.number")

    def test_actions_and_communications_require_explicit_edits(self):
        session = Session(PROFILE)
        values = {c: 0 for c in ("1-29", "14-22", "13-03", "15-06", "8-30")}
        session.apply_read(values)
        targets, problems = session.collect_write_targets([PARAMETERS[c] for c in values])
        self.assertFalse(targets)
        self.assertFalse(problems)

    def test_catalog_rejects_bad_register_width_or_index(self):
        for override in ({"register_count": 0}, {"data_bits": 64}, {"array_index": 9}, {"maximum": 4294967296}):
            p = dict(PARAMETERS["3-03"], **override)
            with self.subTest(override=override), self.assertRaises(CatalogError):
                _validate_parameters("test", [p], {"3": 3}, "danfoss_pnu")


class FC51ValueTests(unittest.TestCase):
    def test_signed_16_and_32_bit_values_round_trip(self):
        for code, text, raw in (("1-62", "-400", 0xFE70), ("3-10[7]", "-25.00", 0xF63C),
                                ("3-02", "-20.500", 0xFFFFAFEC), ("3-03", "1000.000", 1000000)):
            p = PARAMETERS[code]
            with self.subTest(code=code):
                self.assertIsNone(codecs.validate_value(p, text))
                self.assertEqual(codecs.encode_value(p, text), raw)
                self.assertEqual(codecs.format_value(raw, p), text)

    def test_unsigned_32_bit_readouts_are_not_truncated(self):
        self.assertEqual(codecs.format_value(0xFFFFFFFF, PARAMETERS["16-90"]), "4294967295")

    def test_identification_string(self):
        raw = int.from_bytes(b"FC 51 2.70".ljust(20, b"\x00"), "big")
        self.assertEqual(codecs.format_value(raw, PARAMETERS["15-43"]), "FC 51 2.70")

    def test_settings_preserve_32_bit_and_indexed_values(self):
        session = Session(PROFILE)
        values = {"3-02": 0xFFFFAFEC, "3-03": 1000000, "3-10[7]": 0xF63C}
        loaded = parse_settings_file(session.settings_payload(values, 7), CATALOG)
        self.assertEqual(loaded.values, values)
        session.apply_read(loaded.values)
        self.assertEqual(session.display(PARAMETERS["3-02"]), "-20.500")
        with self.assertRaises(ValueError):
            parse_settings_file(session.settings_payload({"3-03": 1 << 32}, 1), CATALOG)

    def test_signed_dependencies_compare_engineering_values(self):
        session = Session(PROFILE)
        session.apply_read({"3-02": codecs.encode_value(PARAMETERS["3-02"], "-20"),
                            "3-03": codecs.encode_value(PARAMETERS["3-03"], "-10")})
        session.edited = {"3-02": "-5", "3-03": "5"}
        targets, problems = session.collect_write_targets([PARAMETERS["3-02"], PARAMETERS["3-03"]])
        self.assertFalse(problems)
        self.assertEqual([t.code for t in targets], ["3-03", "3-02"])


class FC51TransportTests(unittest.TestCase):
    def setUp(self):
        self.link = ModbusLink("test", 7, PROFILE.link_for_protocol("modbus_rtu"))
        self.link.client = Mock()
        self.link.client.write_register.return_value = reply()
        self.link.client.write_registers.return_value = reply()
        self.link.client.write_coil.return_value = reply()

    def test_read_32_bits_requests_two_registers_high_word_first(self):
        self.link.client.read_holding_registers.return_value = reply([0, 35000])
        self.assertEqual(self.link.read_values([PARAMETERS["3-03"]]), {"3-03": 35000})
        self.link.client.read_holding_registers.assert_called_once_with(address=3029, count=2, device_id=7)

    def test_array_index_is_selected_before_every_read(self):
        self.link.client.read_holding_registers.side_effect = [reply([100]), reply([200])]
        rows = [PARAMETERS["3-10[0]"], PARAMETERS["3-10[7]"]]
        self.assertEqual(self.link.read_values(rows), {"3-10[0]": 100, "3-10[7]": 200})
        self.assertEqual([c.kwargs["value"] for c in self.link.client.write_register.call_args_list], [0, 7])
        self.assertTrue(all(c.kwargs["address"] == 8 for c in self.link.client.write_register.call_args_list))

    def test_failed_index_selection_never_reads_stale_array_element(self):
        self.link.client.write_register.return_value = reply(error=True)
        self.assertEqual(self.link.read_values([PARAMETERS["3-10[7]"]]), {"3-10[7]": codecs.READ_ERROR})
        self.link.client.read_holding_registers.assert_not_called()

    def test_short_read_is_an_error(self):
        self.link.client.read_holding_registers.return_value = reply([1])
        self.assertEqual(self.link.read_values([PARAMETERS["3-03"]]), {"3-03": codecs.READ_ERROR})

    def test_write_32_bits_uses_function_16_and_enables_eeprom(self):
        p = PARAMETERS["3-03"]
        raw = codecs.encode_value(p, "1000")
        result = self.link.write_values([(p, raw, "1000")])
        self.assertEqual(result["written"], {"3-03": 1000000})
        self.link.client.write_coil.assert_called_once_with(address=64, value=True, device_id=7)
        self.link.client.write_registers.assert_called_once_with(address=3029, values=[15, 16960], device_id=7)

    def test_write_array_selects_index_before_single_register(self):
        p = PARAMETERS["3-10[7]"]
        self.link.write_values([(p, 0xF63C, "-25.00")])
        calls = self.link.client.write_register.call_args_list
        self.assertEqual([(c.kwargs["address"], c.kwargs["value"]) for c in calls], [(8, 7), (3099, 0xF63C)])

    def test_persistence_failure_prevents_all_parameter_writes(self):
        self.link.client.write_coil.return_value = reply(error=True)
        result = self.link.write_values([(PARAMETERS["3-03"], 50000, "50")])
        self.assertFalse(result["written"])
        self.assertEqual(len(result["failed"]), 1)
        self.link.client.write_registers.assert_not_called()

    def test_connection_settings_written_last(self):
        self.link.write_values([(PARAMETERS["8-31"], 2, "2"), (PARAMETERS["1-23"], 50, "50")])
        addresses = [c.kwargs["address"] for c in self.link.client.write_register.call_args_list]
        self.assertEqual(addresses, [1229, 8309])

    def test_legacy_single_register_transport_has_no_extra_writes(self):
        link = ModbusLink("test", 1, LinkSettings())
        link.client = self.link.client
        p = CATALOG["eds800"].by_code()["F0.01"]
        link.write_values([(p, 5000, "50")])
        link.client.write_register.assert_called_once_with(address=1, value=5000, device_id=1)
        link.client.write_coil.assert_not_called()

    def test_batch_sizes_count_registers_and_do_not_mix_indices(self):
        rows = [{"code": "A", "address": 100, "register_count": 2},
                {"code": "B", "address": 102}, {"code": "C", "address": 103}]
        self.assertEqual([len(c) for c in contiguous_chunks(rows, 3)], [2, 1])
        self.assertEqual([len(c) for c in contiguous_chunks([PARAMETERS["3-10[0]"], PARAMETERS["3-10[1]"]])], [1, 1])

    def test_cancellation_prevents_bus_writes(self):
        self.link.cancel.set()
        with self.assertRaises(TaskCancelled):
            self.link.write_values([(PARAMETERS["3-03"], 50000, "50")])
        self.link.client.write_coil.assert_not_called()


if __name__ == "__main__":
    unittest.main()
