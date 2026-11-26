"""VH5-45P5-B: official wire addresses, safe ambiguity handling, no hardware."""
from collections import Counter
from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

from enc_editor import codecs, connection, diagnostics
from enc_editor.catalog import CatalogError, _split_code, _validate_parameters, load_catalog
from enc_editor.i18n import Translator
from enc_editor.session import Session, parse_settings_file
from enc_editor.transport import ModbusLink, contiguous_chunks, create_link

CATALOG = load_catalog()
PROFILE = CATALOG["xinje_vh5"]
PARAMETERS = PROFILE.by_code()


def reply(values=()):
    result = Mock(registers=list(values))
    result.isError.return_value = False
    return result


class VH5ProfileTests(unittest.TestCase):
    def test_identity_and_factory_link_match_p9_table(self):
        self.assertEqual(PROFILE.manufacturer, "XINJE")
        self.assertIn("VH5-45P5-B", PROFILE.model)
        self.assertEqual(PROFILE.link.frame, "19200 8E1")
        self.assertEqual(PROFILE.link.device_id, 1)
        self.assertEqual(PROFILE.link.max_read_registers, 12)
        self.assertEqual(PROFILE.link.maximum_device_id, 247)
        self.assertEqual(PROFILE.supported_protocols, ("modbus_rtu",))
        self.assertIsNone(PROFILE.link.persist_coil)
        self.assertEqual(len(PROFILE.parameters), 548)
        self.assertEqual(len(PROFILE.groups), 22)
        self.assertEqual(sum(not p["read_only"] for p in PROFILE.parameters), 427)

    def test_documented_addresses_are_zero_based_and_suffixes_are_decimal(self):
        for code, address in (("P0-10", 0x000A), ("P0-13", 0x000D), ("P1-03", 0x0103),
                              ("P9-03", 0x0903), ("A0-15", 0xA00F),
                              ("A0-09", 0xA009), ("U0-33", 0x7021), ("MB.16", 0x1210)):
            if code == "A0-15":
                # Appendix example is not a documented function-table row.
                self.assertNotIn(code, PARAMETERS)
                continue
            self.assertEqual(PARAMETERS[code]["address"], address, code)
        self.assertEqual(_split_code("PA-10"), ("PA", 10))
        self.assertEqual(_split_code("AD-15"), ("AD", 15))
        for p in PROFILE.parameters:
            if not p["read_only"]:
                group, number = _split_code(p["code"])
                self.assertEqual(p["address"], (PROFILE.group_ids[group] << 8) | number, p["code"])

    def test_published_conflicts_are_not_writable_and_duplicate_addresses_are_omitted(self):
        for code, address in (("P3-01", 0x0300), ("P3-15", 0x0311), ("P3-16", 0x0312),
                              ("AD-12", 0xAD08), ("AD-13", 0xAD09), ("AD-14", 0xAD0A), ("AD-15", 0xAD0B)):
            self.assertEqual(PARAMETERS[code]["address"], address)
            self.assertTrue(PARAMETERS[code]["read_only"])
            self.assertIn("address conflicts", PARAMETERS[code]["note"])
        for code in ("PC-41", "PC-42", "P8-03", "P8-05", "P8-06", "P0-11", "U4-00"):
            self.assertNotIn(code, PARAMETERS)
        self.assertTrue(all(n == 1 for n in Counter(p["address"] for p in PROFILE.parameters).values()))

    def test_no_guessed_scaling_for_configurable_or_firmware_dependent_fields(self):
        for code in ("P0-05", "P9-02", "PE-00", "P2-16", "PC-43"):
            p = PARAMETERS[code]
            self.assertTrue(p["read_only"], code)
            self.assertEqual((p["scale"], p["unit"]), (1, ""), code)
            self.assertIn("сыр", PROFILE.text(p, "note", "ru").lower())

    def test_frequency_current_resistance_and_signed_torque_scales(self):
        for code, raw, display in (("P0-10", 5000, "50.00"), ("P1-03", 1300, "13.00"),
                                   ("P1-06", 1234, "1.234"), ("U0-00", 5000, "50.00"),
                                   ("U0-02", 5400, "540.0"), ("PF-02", 65535, "-0.1")):
            self.assertEqual(codecs.format_value(raw, PARAMETERS[code]), display, code)
            self.assertEqual(codecs.encode_value(PARAMETERS[code], display), raw, code)
        self.assertEqual(PARAMETERS["P1-03"]["scale"], 100)  # 5.5 kW is <=55 kW.

    def test_sparse_choices_and_frequency_dependencies(self):
        self.assertIsNotNone(codecs.validate_value(PARAMETERS["P0-03"], "4"))
        self.assertIsNone(codecs.validate_value(PARAMETERS["P0-03"], "6"))
        session = Session(PROFILE)
        session.apply_read({"P0-13": 5000})
        session.edited["P0-10"] = "60.00"
        targets, problems = session.collect_write_targets(PROFILE.parameters, edited_only=True)
        self.assertFalse(targets)
        self.assertTrue(problems)

    def test_state_fault_decoding_and_unknown_codes(self):
        t = Translator("ru")
        self.assertIn("Перегрев", diagnostics.decode(PROFILE.diagnostics, "MB.16", 13, t))
        self.assertIn("Тайм-аут", diagnostics.decode(PROFILE.diagnostics, "U0-75", 44, t))
        self.assertIn("Остановлен", diagnostics.decode(PROFILE.diagnostics, "MB.00", 3, t))
        self.assertIn("19", diagnostics.decode(PROFILE.diagnostics, "MB.16", 19, t))
        self.assertEqual(diagnostics.decode(PROFILE.diagnostics, "MB.16", codecs.READ_ERROR, t), t("diag.read_error"))
        self.assertFalse(PROFILE.diagnostics.get("reset"))
        self.assertIn("VH5", PROFILE.diagnostics["intro"]["ru"])

    def test_no_process_commands_and_no_implicit_communication_reconfiguration(self):
        self.assertFalse(any(0x1000 <= p["address"] <= 0x1105 for p in PROFILE.parameters))
        for code in ("P1-35", "A2-35", "P8-02"):
            self.assertTrue(PARAMETERS[code]["read_only"])
        session = Session(PROFILE)
        session.apply_read({"P9-01": 1, "P9-03": 1, "P0-10": 5000})
        targets, problems = session.collect_write_targets(PROFILE.parameters)
        self.assertFalse(problems)
        self.assertEqual([t.code for t in targets], ["P0-10"])

    def test_settings_round_trip_and_localized_names(self):
        session = Session(PROFILE)
        payload = session.settings_payload({"P0-10": 5000, "P1-03": 1300}, 7)
        loaded = parse_settings_file(payload, CATALOG)
        self.assertEqual(loaded.profile.key, "xinje_vh5")
        self.assertEqual(loaded.device_id, 7)
        self.assertEqual(loaded.values["P0-10"], 5000)
        self.assertEqual(PROFILE.text(PARAMETERS["P0-10"], "description", "ru"), "Предустановленная частота")
        self.assertIn("Двигатель", PROFILE.group_label("P1", "ru"))
        self.assertEqual(connection.settings_for(PROFILE, {"parity": "N"}).frame, "19200 8N1")


class VH5TimeTests(unittest.TestCase):
    def setUp(self):
        self.session = Session(PROFILE)

    def test_seconds_round_trip_for_all_three_resolutions(self):
        for mode, scale, shown in ((0, 1, "123"), (1, 10, "12.3"), (2, 100, "1.23")):
            for code in ("P0-18", "P0-19"):
                with self.subTest(mode=mode, code=code):
                    self.session.apply_read({"PC-09": mode, code: 123})
                    parameter = PARAMETERS[code]
                    self.assertFalse(parameter["read_only"])
                    self.assertEqual(parameter["unit"], "s")
                    self.assertEqual(self.session.display(parameter), shown)
                    self.session.edited[code] = "10"
                    targets, problems = self.session.collect_write_targets([parameter], edited_only=True)
                    self.assertFalse(problems)
                    self.assertEqual(targets[0].raw_value, 10 * scale)
                    self.assertEqual(targets[0].parameter["scale_context"],
                                     {"code": "PC-09", "address": 0x0C09, "value": mode})

    def test_limits_and_step_follow_selector_without_rounding_user_input(self):
        parameter = PARAMETERS["P0-18"]
        for mode, limit, valid, invalid in ((0, "65000", "1", "1.1"),
                                           (1, "6500.0", "1.1", "1.11"),
                                           (2, "650.00", "1.11", "1.111")):
            with self.subTest(mode=mode):
                self.session.apply_read({"PC-09": mode})
                self.assertIsNone(self.session.validate(parameter, limit))
                self.assertIsNone(self.session.validate(parameter, valid))
                self.assertEqual(self.session.validate(parameter, invalid).key, "valid.resolution")
                self.assertEqual(self.session.validate(parameter, "65001").key, "valid.between")
                self.assertIsNotNone(self.session.validate(parameter, "-1"))

    def test_missing_failed_or_unsupported_selector_never_guesses_default(self):
        parameter = PARAMETERS["P0-18"]
        for values in ({"P0-18": 100}, {"P0-18": 100, "PC-09": codecs.READ_ERROR},
                       {"P0-18": 100, "PC-09": 3}):
            with self.subTest(values=values):
                session = Session(PROFILE)
                session.apply_read(values)
                self.assertEqual(session.display(parameter), codecs.SCALE_ERROR)
                self.assertEqual(session.validate(parameter, "10").key, "valid.scale_unknown")
                targets, problems = session.collect_write_targets([parameter])
                self.assertFalse(targets)
                self.assertEqual(problems[0][1].key, "valid.scale_unknown")
        with self.assertRaises(codecs.CodecError):
            codecs.encode_value(parameter, "10")
        self.assertEqual(codecs.format_value(100, parameter), codecs.SCALE_ERROR)

    def test_group_read_includes_selector_once_but_other_groups_are_unchanged(self):
        group = self.session.group_parameters("P0")
        expanded = self.session.read_parameters_with_context(group)
        self.assertEqual([p["code"] for p in expanded].count("PC-09"), 1)
        self.assertEqual(len(expanded), len(group) + 1)
        self.assertEqual(len(self.session.read_parameters_with_context(PROFILE.parameters)), 548)
        expanded_motor = self.session.read_parameters_with_context(self.session.group_parameters("P1"))
        self.assertIn("P0-13", [p["code"] for p in expanded_motor])

    def test_editing_selector_does_not_reinterpret_cached_display(self):
        self.session.apply_read({"PC-09": 1, "P0-18": 100})
        self.session.edited["PC-09"] = "2"
        self.assertEqual(self.session.display(PARAMETERS["P0-18"]), "10.0")
        self.session.apply_write({"PC-09": 2})
        self.assertNotIn("P0-18", self.session.loaded)  # must reread from drive

    def test_batch_orders_selector_first_and_preserves_seconds(self):
        self.session.apply_read({"PC-09": 1, "P0-18": 100, "P0-19": 200})
        self.session.edited.update({"PC-09": "2", "P0-18": "3.25"})
        targets, problems = self.session.collect_write_targets(
            [PARAMETERS[c] for c in ("P0-18", "P0-19", "PC-09")])
        self.assertFalse(problems)
        self.assertEqual([(t.code, t.raw_value) for t in targets],
                         [("PC-09", 2), ("P0-18", 325), ("P0-19", 2000)])
        self.session.apply_write({t.code: t.raw_value for t in targets}, {"PC-09": 2})
        self.assertEqual(self.session.display(PARAMETERS["P0-18"]), "3.25")
        self.assertEqual(self.session.display(PARAMETERS["P0-19"]), "20.00")

    def test_selector_edit_outside_write_scope_is_not_used(self):
        self.session.apply_read({"PC-09": 1})
        self.session.edited.update({"PC-09": "2", "P0-18": "3.2"})
        targets, problems = self.session.collect_write_targets([PARAMETERS["P0-18"]], edited_only=True)
        self.assertFalse(problems)
        self.assertEqual(targets[0].raw_value, 32)

    def test_read_changed_selector_invalidates_only_unread_cached_times(self):
        self.session.apply_read({"PC-09": 1, "P0-18": 100, "P0-19": 200})
        self.session.apply_read({"PC-09": 2, "P0-18": 1000})
        self.assertEqual(self.session.display(PARAMETERS["P0-18"]), "10.00")
        self.assertNotIn("P0-19", self.session.loaded)

    def test_settings_round_trip_contains_selector_and_engineering_display(self):
        self.session.apply_read({"PC-09": 2, "P0-18": 125, "P0-19": 550})
        self.session.edited["P0-18"] = "2.25"
        targets, problems = self.session.collect_write_targets(PROFILE.parameters, edited_only=True)
        self.assertFalse(problems)
        values = dict(self.session.loaded, **{t.code: t.raw_value for t in targets})
        loaded = parse_settings_file(self.session.settings_payload(values, 1), CATALOG)
        restored = Session(loaded.profile, loaded=dict(loaded.values))
        self.assertEqual(restored.display(PARAMETERS["P0-18"]), "2.25")
        self.assertEqual(restored.display(PARAMETERS["P0-19"]), "5.50")

    def test_catalog_rejects_broken_context_metadata(self):
        for field, value in (("scale_from", "no-such-code"), ("scale_from", "P0-18"),
                             ("scale_values", {"0": 1}), ("scale_values", {"0": -1}),
                             ("maximum_raw", 70000)):
            with self.subTest(field=field, value=value):
                parameters = deepcopy(list(PROFILE.parameters))
                next(p for p in parameters if p["code"] == "P0-18")[field] = value
                with self.assertRaises(CatalogError):
                    _validate_parameters(PROFILE.key, parameters, PROFILE.group_ids, "explicit")

    def test_generator_keeps_the_dynamic_time_definition_and_translation(self):
        from tools import extract_vh5_parameters as extractor
        from tools.vh5_metadata import metadata
        rows = [dict(code=code, description=PARAMETERS[code]["description"],
                     range=PARAMETERS[code]["range"], address=PARAMETERS[code]["address"],
                     modify="○", factory="Model setting", monitor_unit="", manual_pdf_page=43)
                for code in ("P0-18", "P0-19")]
        # Test the generator override, not PDF extraction or a live device.
        with patch.object(extractor, "table_rows", return_value=rows), patch("pdfplumber.open"):
            generated, _rows = extractor.extract("not-opened.pdf")
        ru, _diagnosis = metadata(generated)
        for parameter in generated[:2]:
            code = parameter["code"]
            self.assertEqual(parameter, PARAMETERS[code])
            self.assertEqual(ru[code], dict(PROFILE.translations["ru"][code]))


class VH5TransportTests(unittest.TestCase):
    def setUp(self):
        self.link = create_link("mock", 7, PROFILE.link)
        self.link.client = Mock()
        self.link.client.read_holding_registers.side_effect = lambda **kw: reply([0] * kw["count"])
        self.link.client.write_register.return_value = reply()

    def test_reads_never_cross_group_or_exceed_twelve(self):
        self.assertIsInstance(self.link, ModbusLink)
        for chunk in contiguous_chunks(PROFILE.parameters, PROFILE.link.max_read_registers):
            self.assertLessEqual(len(chunk), 12)
            self.assertEqual(len({p["address"] >> 8 for p in chunk}), 1)
        self.link.read_values([PARAMETERS["U0-00"]])
        self.link.client.read_holding_registers.assert_called_once_with(address=0x7000, count=1, device_id=7)
        self.link.client.write_register.assert_not_called()

    def test_parameter_write_uses_fc06_eeprom_address_not_command_or_persist_coil(self):
        self.link.write_values([(PARAMETERS["P0-10"], 5000, "50.00")])
        self.link.client.write_register.assert_called_once_with(address=0x000A, value=5000, device_id=7)
        self.link.client.write_coil.assert_not_called()
        self.link.client.write_registers.assert_not_called()

    def time_targets(self, mode=1, include_selector=False):
        session = Session(PROFILE)
        session.apply_read({"PC-09": mode, "P0-18": 100})
        session.edited["P0-18"] = "12"
        if include_selector:
            session.edited["PC-09"] = "2"
        targets, problems = session.collect_write_targets(PROFILE.parameters, edited_only=True)
        self.assertFalse(problems)
        return session, [t.as_tuple() for t in targets]

    def test_time_write_checks_live_selector_before_fc06(self):
        _session, targets = self.time_targets()
        self.link.client.read_holding_registers.side_effect = lambda **kw: reply([1])
        result = self.link.write_values(targets)
        self.assertEqual(result["written"], {"P0-18": 120})
        self.link.client.read_holding_registers.assert_called_once_with(address=0x0C09, count=1, device_id=7)
        self.link.client.write_register.assert_called_once_with(address=0x0012, value=120, device_id=7)
        self.link.client.write_coil.assert_not_called()

    def test_changed_or_failed_selector_prevents_all_batch_writes(self):
        for actual in (2, 3, codecs.READ_ERROR):
            with self.subTest(actual=actual):
                session, targets = self.time_targets()
                self.link.client.write_register.reset_mock()
                self.link.read_parameter = Mock(return_value=actual)
                targets.append((PARAMETERS["P0-10"], 5000, "50.00"))
                result = self.link.write_values(targets)
                self.assertFalse(result["written"])
                self.assertEqual(len(result["failed"]), 2)
                self.assertEqual(result["failed"][0][1].key, "valid.scale_changed")
                self.link.client.write_register.assert_not_called()
                self.link.client.write_coil.assert_not_called()
                session.apply_write(result["written"], result["context"])
                self.assertNotIn("P0-18", session.loaded)
                self.assertEqual(session.edited["P0-18"], "12")

    def test_unresolved_raw_time_cannot_bypass_context_check(self):
        result = self.link.write_values([(PARAMETERS["P0-18"], 100, "100")])
        self.assertFalse(result["written"])
        self.assertEqual(result["failed"][0][1].key, "valid.scale_unknown")
        self.link.client.write_register.assert_not_called()

    def test_batch_selector_is_written_and_read_back_before_times(self):
        session, targets = self.time_targets(include_selector=True)
        self.link.client.read_holding_registers.side_effect = [reply([1]), reply([2])]
        result = self.link.write_values(list(reversed(targets)))  # transport also guards ordering
        calls = self.link.client.mock_calls
        writes = [c.kwargs for c in calls if c[0] == "write_register"]
        self.assertEqual([w["address"] for w in writes], [0x0C09, 0x0012])
        self.assertEqual(writes[1]["value"], 1200)
        self.assertEqual(self.link.client.read_holding_registers.call_count, 2)
        session.apply_write(result["written"], result["context"])
        self.assertEqual(session.display(PARAMETERS["P0-18"]), "12.00")

    def test_failed_selector_write_blocks_times_when_readback_is_unchanged(self):
        _session, targets = self.time_targets(include_selector=True)
        self.link.client.read_holding_registers.side_effect = lambda **kw: reply([1])
        error = Mock()
        error.isError.return_value = True
        self.link.client.write_register.return_value = error
        result = self.link.write_values(targets)
        self.assertFalse(result["written"])
        self.assertEqual(len(result["failed"]), 2)
        self.assertEqual(self.link.client.write_register.call_count, 1)

    def test_lost_selector_ack_with_confirmed_readback_updates_display_context(self):
        session, targets = self.time_targets(include_selector=True)
        self.link.client.read_holding_registers.side_effect = [reply([1]), reply([2])]
        error = Mock()
        error.isError.return_value = True
        self.link.client.write_register.side_effect = [error, reply()]
        result = self.link.write_values(targets)
        self.assertEqual(result["written"], {"P0-18": 1200})
        session.apply_write(result["written"], result["context"])
        self.assertEqual(session.display(PARAMETERS["P0-18"]), "12.00")
        self.assertEqual(session.edited, {"PC-09": "2"})
