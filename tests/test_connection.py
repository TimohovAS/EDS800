"""PC-only serial settings, persistence and profile isolation."""
from dataclasses import replace
import unittest

from enc_editor.catalog import load_catalog
from enc_editor.connection import SettingsError, restore_overrides, serial_payload, settings_for

CATALOG = load_catalog()
FC = CATALOG["danfoss_fc51"]
ENC = CATALOG["eds800"]


class ConnectionSettingsTests(unittest.TestCase):
    def test_factory_defaults_and_modbus_preset(self):
        native = settings_for(FC)
        self.assertEqual((native.protocol, native.frame, native.maximum_device_id),
                         ("danfoss_fc", "9600 8E1", 126))
        modbus = settings_for(FC, {"protocol": "modbus_rtu"})
        self.assertEqual((modbus.frame, modbus.maximum_device_id), ("19200 8E1", 247))
        self.assertEqual(ENC.supported_protocols, ("modbus_rtu",))
        self.assertEqual(settings_for(ENC).frame, "9600 8N1")

    def test_overrides_do_not_mutate_profile_or_protocol_specific_addresses(self):
        changed = settings_for(FC, {"protocol": "modbus_rtu", "baudrate": 38400,
                                    "parity": "N", "stopbits": 2, "timeout": 2.5,
                                    "persist_coil": 999, "index_register": 999})
        self.assertEqual(changed.frame, "38400 8N2")
        self.assertEqual(changed.timeout, 2.5)
        self.assertEqual(changed.persist_coil, 64)
        self.assertEqual(changed.index_register, 8)
        self.assertEqual(FC.link.frame, "9600 8E1")

    def test_supported_baudrates_are_profile_data(self):
        for protocol in FC.supported_protocols:
            for rate in (2400, 4800, 9600, 19200, 38400):
                self.assertEqual(settings_for(FC, {"protocol": protocol, "baudrate": rate}).baudrate, rate)
            with self.assertRaises(SettingsError):
                settings_for(FC, {"protocol": protocol, "baudrate": 115200})

    def test_invalid_frames_protocols_numbers_and_timeout_are_rejected(self):
        for values in ({"protocol": "unknown"}, {"baudrate": 0}, {"baudrate": True},
                       {"baudrate": "9600"}, {"bytesize": 7}, {"bytesize": True},
                       {"parity": "x"}, {"stopbits": 3}, {"stopbits": True},
                       {"timeout": 0}, {"timeout": 31}, {"timeout": True},
                       {"timeout": "1"}, {"timeout": float("inf")}, {"timeout": float("nan")}):
            with self.subTest(values=values), self.assertRaises(SettingsError):
                settings_for(FC, values)

    def test_fc_requires_even_parity_and_one_stop_bit(self):
        for values in ({"parity": "N"}, {"parity": "O"}, {"stopbits": 2}):
            with self.assertRaises(SettingsError) as caught:
                settings_for(FC, values)
            self.assertEqual(caught.exception.key, "connection.fc_frame")

    def test_fc_cannot_be_selected_for_enc(self):
        with self.assertRaises(SettingsError):
            settings_for(ENC, {"protocol": "danfoss_fc"})

    def test_only_serial_overrides_are_saved(self):
        fields = serial_payload(FC.link)
        self.assertEqual(set(fields), {"protocol", "baudrate", "parity", "stopbits", "bytesize", "timeout"})
        self.assertNotIn("device_id", fields)
        self.assertNotIn("persist_coil", fields)

    def test_valid_persisted_overrides_round_trip_per_profile(self):
        enc = serial_payload(replace(ENC.link, baudrate=19200))
        fc = serial_payload(settings_for(FC, {"protocol": "modbus_rtu", "baudrate": 38400}))
        restored = restore_overrides(CATALOG, {"eds800": enc, "danfoss_fc51": fc})
        self.assertEqual(restored, {"eds800": enc, "danfoss_fc51": fc})
        self.assertEqual(settings_for(ENC, restored["eds800"]).baudrate, 19200)
        self.assertEqual(settings_for(FC, restored["danfoss_fc51"]).baudrate, 38400)

    def test_malformed_and_obsolete_preferences_are_ignored(self):
        for saved in (None, [], "bad", {"gone": {}}, {"eds800": "bad"},
                      {"eds800": {"protocol": "danfoss_fc"}}, {"danfoss_fc51": {"timeout": False}}):
            with self.subTest(saved=saved):
                self.assertEqual(restore_overrides(CATALOG, saved), {})


if __name__ == "__main__":
    unittest.main()
