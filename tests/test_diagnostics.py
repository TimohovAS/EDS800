"""Diagnostic decoding and reset interlocks, with no drive or serial port."""
import copy
import unittest
from unittest.mock import Mock

from pymodbus.exceptions import ModbusException

from enc_editor import diagnostics
from enc_editor.catalog import load_catalog
from enc_editor.codecs import READ_ERROR
from enc_editor.i18n import Translator
from enc_editor.session import Session
from enc_editor.transport import ModbusLink, TaskCancelled

PROFILE = load_catalog()["danfoss_fc51"]
DATA = PROFILE.diagnostics
PARAMETERS = PROFILE.by_code()


def reply(words=(), bits=(), error=False):
    return Mock(registers=list(words), bits=list(bits), isError=Mock(return_value=error))


class DecodingTests(unittest.TestCase):
    def decode(self, code, raw, language="ru"):
        return diagnostics.decode(DATA, code, raw, Translator(language))

    def test_alarm_bits_are_not_fault_codes(self):
        self.assertIn("Сверхток", self.decode("16-90", 1 << 5))
        self.assertIn("Отсутствует фаза W", self.decode("15-30[0]", 32))
        self.assertIn("Сверхток", self.decode("15-30[0]", 13))

    def test_all_simultaneous_flags_including_top_bit(self):
        result = self.decode("16-90", (1 << 5) | (1 << 11) | (1 << 31))
        self.assertIn("Бит 5: Сверхток", result)
        self.assertIn("Бит 11: Перенапряжение", result)
        self.assertIn("Бит 31: Недостаточный ток", result)
        self.assertEqual(result.count("; "), 2)

    def test_unknown_values_never_disappear(self):
        self.assertIn("Неописанный бит 3", self.decode("16-90", 1 << 3))
        self.assertIn("Неизвестный код ошибки 255", self.decode("15-30[0]", 255))
        self.assertIn("Undocumented bit 32", self.decode("16-90", 1 << 32, "en"))

    def test_missing_and_read_error_are_not_zero(self):
        results = {self.decode("16-90", raw) for raw in (0, None, READ_ERROR, -1)}
        self.assertEqual(len(results), 4)
        self.assertIn("Нет активных флагов", self.decode("16-90", 0))
        self.assertIn("Нет записанного события", self.decode("15-30[9]", 0))

    def test_language_fallback_and_non_diagnostic_parameter(self):
        self.assertIn("Overcurrent", self.decode("16-90", 32, "en"))
        self.assertIn("Overcurrent", self.decode("16-90", 32, "sr"))
        self.assertEqual(self.decode("1-23", 50), "")

    def test_warning_and_extended_status_are_separate_maps(self):
        self.assertIn("предел тока", self.decode("16-92", 1 << 25))
        self.assertIn("База параметров занята", self.decode("16-94", 1 << 31))
        self.assertIn("Работает".lower(), self.decode("16-03", 1 << 11).lower())

    def test_all_ten_history_entries_and_manual_fault_codes_present(self):
        codes = {2, 4, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 25, 27, 28, 29,
                 30, 31, 32, 38, 44, 47, 51, 52, 53, 54, 55, 59, 63, 80,
                 84, 85, 86, 87, 88, 89, 90, 91, 92}
        self.assertEqual(set(map(int, DATA["tables"]["faults"])), codes)
        for index in range(10):
            self.assertIn("Внутренняя неисправность", self.decode(f"15-30[{index}]", 38))

    def test_raw_values_and_saved_settings_are_not_decoded_text(self):
        session = Session(PROFILE)
        session.apply_read({"16-90": 1 << 31, "15-30[0]": 13})
        self.decode("16-90", session.loaded["16-90"])
        self.assertEqual(session.display(PARAMETERS["16-90"]), "2147483648")
        self.assertEqual(session.loaded["15-30[0]"], 13)
        self.assertEqual(session.edited, {})

    def test_invalid_diagnostic_data_rejected(self):
        for mutate in (
            lambda d: d["fields"].update({"1-23": {"kind": "bits", "table": "status"}}),
            lambda d: d["tables"]["status"].update({"16": {"en": "out of range"}}),
            lambda d: d["fields"]["16-90"].update(table="missing"),
            lambda d: d.update(reset="unknown"),
        ):
            data = copy.deepcopy(DATA)
            mutate(data)
            with self.assertRaises(ValueError):
                diagnostics.validate(data, PARAMETERS)


class RemoteResetTests(unittest.TestCase):
    def setUp(self):
        self.link = ModbusLink("test", 7, PROFILE.link_for_protocol("modbus_rtu"))
        self.link.client = Mock()
        self.link.client.read_holding_registers.return_value = reply([8])  # trip, no RUN
        self.bits = [False] * 16
        self.bits[10] = True
        self.link.client.read_coils.return_value = reply(bits=self.bits)
        self.link.client.write_coil.return_value = reply()
        self.link.cancel.wait = Mock(return_value=False)

    def reset(self):
        self.link.reset_fc_trip(PARAMETERS["16-03"])

    def test_reset_pulses_only_zero_based_coil_seven(self):
        self.reset()
        self.link.client.read_coils.assert_called_once_with(address=0, count=16, device_id=7)
        calls = self.link.client.write_coil.call_args_list
        self.assertEqual([c.kwargs for c in calls], [
            {"address": 7, "value": value, "device_id": 7} for value in (False, True, False)
        ])
        self.link.client.write_register.assert_not_called()
        self.link.client.write_registers.assert_not_called()

    def test_existing_high_reset_gets_new_leading_edge(self):
        self.bits[7] = True
        self.link.client.read_coils.return_value = reply(bits=self.bits)
        self.reset()
        self.assertEqual([c.kwargs["value"] for c in self.link.client.write_coil.call_args_list],
                         [False, True, False])

    def test_run_jog_or_ignored_control_word_refuse_all_writes(self):
        for bit, value, reason in ((6, True, "diag.reset_running"), (8, True, "diag.reset_running"),
                                   (10, False, "diag.reset_ignored")):
            bits = self.bits.copy()
            bits[bit] = value
            self.link.client.read_coils.return_value = reply(bits=bits)
            with self.subTest(bit=bit), self.assertRaises(diagnostics.ResetRefused) as caught:
                self.reset()
            self.assertEqual(caught.exception.key, reason)
        self.link.client.write_coil.assert_not_called()

    def test_trip_lock_running_or_auto_restart_refuse_all_writes(self):
        for bit in (6, 11, 12):
            self.link.client.read_holding_registers.return_value = reply([1 << bit])
            with self.subTest(bit=bit), self.assertRaises(diagnostics.ResetRefused):
                self.reset()
        self.link.client.read_coils.assert_not_called()
        self.link.client.write_coil.assert_not_called()

    def test_unreadable_status_or_control_word_refuses_all_writes(self):
        self.link.client.read_holding_registers.return_value = reply(error=True)
        with self.assertRaises(diagnostics.ResetRefused):
            self.reset()
        self.link.client.read_holding_registers.return_value = reply([8])
        for response in (reply(error=True), reply(bits=[True])):
            self.link.client.read_coils.return_value = response
            with self.assertRaises(diagnostics.ResetRefused):
                self.reset()
        self.link.client.write_coil.assert_not_called()

    def test_cancel_during_pulse_still_clears_reset(self):
        self.link.cancel.wait.side_effect = lambda timeout: self.link.cancel.set()
        with self.assertRaises(TaskCancelled):
            self.reset()
        self.assertEqual(self.link.client.write_coil.call_args.kwargs["value"], False)
        self.assertEqual(self.link.client.write_coil.call_count, 3)

    def test_lost_on_response_still_attempts_clear(self):
        self.link.client.write_coil.side_effect = [reply(), ModbusException("timeout"), reply()]
        with self.assertRaises(ModbusException):
            self.reset()
        self.assertEqual([c.kwargs["value"] for c in self.link.client.write_coil.call_args_list],
                         [False, True, False])

    def test_failed_initial_clear_never_asserts_reset(self):
        self.link.client.write_coil.return_value = reply(error=True)
        with self.assertRaises(ModbusException):
            self.reset()
        self.assertEqual(self.link.client.write_coil.call_count, 1)
        self.assertFalse(self.link.client.write_coil.call_args.kwargs["value"])

    def test_failed_cleanup_is_not_reported_as_success(self):
        self.link.client.write_coil.side_effect = [reply(), reply(), reply(error=True)]
        with self.assertRaises(ModbusException):
            self.reset()


if __name__ == "__main__":
    unittest.main()
