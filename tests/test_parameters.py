import unittest

from inverter_parameter_editor import InverterParameterEditor
from parameters import PARAMETERS


class ParameterTableTests(unittest.TestCase):
    def setUp(self):
        self.editor = InverterParameterEditor.__new__(InverterParameterEditor)
        self.by_code = {parameter["code"]: parameter for parameter in PARAMETERS}

    def test_codes_and_addresses_are_unique(self):
        codes = [parameter["code"] for parameter in PARAMETERS]
        addresses = [parameter["address"] for parameter in PARAMETERS]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(len(addresses), len(set(addresses)))

    def test_documented_modbus_addresses(self):
        self.assertEqual(self.by_code["F0.03"]["address"], 0x0003)
        self.assertEqual(self.by_code["F2.11"]["address"], 0x020B)
        self.assertEqual(self.by_code["Fd.14"]["address"], 0x0D0E)

    def test_numeric_scaling_round_trip(self):
        parameter = self.by_code["F0.01"]
        raw = self.editor._encode_value(parameter, "50.25")
        self.assertEqual(raw, 5025)
        self.assertEqual(self.editor._format_value(raw, parameter), "50.25")

    def test_bcd_round_trip(self):
        parameter = self.by_code["F2.11"]
        raw = self.editor._encode_value(parameter, "1111")
        self.assertEqual(raw, 0x1111)
        self.assertEqual(self.editor._format_value(raw, parameter), "1111")

    def test_fault_history_is_read_only(self):
        fault_parameters = [
            parameter for parameter in PARAMETERS if parameter["group"] == "Fd"
        ]
        self.assertTrue(fault_parameters)
        self.assertTrue(all(parameter["read_only"] for parameter in fault_parameters))

    def test_defaults_match_declared_formats_and_ranges(self):
        for parameter in PARAMETERS:
            with self.subTest(code=parameter["code"]):
                minimum, maximum = map(float, parameter["range"].split("~"))
                default = parameter["default"]
                if default == "Device-specific":
                    continue
                if parameter["encoding"] == "bcd":
                    self.assertEqual(len(default), parameter["digits"])
                    self.assertTrue(
                        all(char in parameter["digit_chars"] for char in default)
                    )
                numeric_default = float(default)
                self.assertLessEqual(minimum, numeric_default)
                self.assertLessEqual(numeric_default, maximum)


if __name__ == "__main__":
    unittest.main()
