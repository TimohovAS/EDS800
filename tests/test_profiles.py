import unittest

from inverter_parameter_editor import InverterParameterEditor
from inverter_profiles import EN600_2S0007_PROFILE, EN600_V2_PROFILE, PROFILES


class InverterProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = EN600_2S0007_PROFILE
        self.editor = InverterParameterEditor.__new__(InverterParameterEditor)
        self.by_code = {
            parameter["code"]: parameter for parameter in self.profile.parameters
        }

    def test_profiles_are_registered(self):
        self.assertEqual(
            set(PROFILES),
            {
                "eds800",
                "en600_2s0007",
                "en600_2s0007_v2",
                "en600_2s0007_v5",
            },
        )

    def test_en600_parameter_map_is_complete_and_unique(self):
        self.assertEqual(len(self.profile.parameters), 651)
        self.assertEqual(len(EN600_V2_PROFILE.parameters), 562)
        codes = [parameter["code"] for parameter in self.profile.parameters]
        addresses = [parameter["address"] for parameter in self.profile.parameters]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(len(addresses), len(set(addresses)))
        self.assertEqual(codes[0], "F00.00")
        self.assertEqual(codes[-1], "F26.17")

    def test_en600_documented_addresses(self):
        self.assertEqual(self.by_code["F05.03"]["address"], 0x0503)
        self.assertEqual(self.by_code["F02.26"]["address"], 0x021A)
        self.assertEqual(self.by_code["F02.26"]["minimum"], 95)
        self.assertEqual(self.by_code["F02.26"]["maximum"], 115)
        self.assertEqual(self.by_code["F19.16"]["address"], 0x1310)
        self.assertEqual(self.by_code["F26.17"]["address"], 0x1A11)

    def test_en600_scaling_and_display_metadata(self):
        self.assertEqual(self.by_code["F01.01"]["scale"], 100)
        self.assertEqual(self.by_code["F00.25"]["scale"], 1)
        self.assertEqual(self.by_code["F01.03"]["maximum"], 20)
        self.assertEqual(self.by_code["F00.01"]["encoding"], "numeric")
        legacy_by_code = {
            parameter["code"]: parameter for parameter in EN600_V2_PROFILE.parameters
        }
        self.assertEqual(legacy_by_code["F02.25"]["encoding"], "numeric")
        self.assertEqual(self.by_code["F05.01"]["encoding"], "bcd")
        self.assertEqual(self.by_code["F05.01"]["display_width"], 3)
        self.assertEqual(self.by_code["F15.01"]["scale"], 10)
        self.assertEqual(
            self.editor._format_value(5, self.by_code["F05.01"]),
            "005",
        )
        self.assertEqual(
            self.editor._format_value(0x0500, self.by_code["F00.14"]),
            "500",
        )
        self.assertEqual(
            self.editor._encode_value(self.by_code["F00.14"], "500"),
            0x0500,
        )
        self.assertEqual(
            self.editor._format_value(0x1000, self.by_code["F01.16"]),
            "1000",
        )
        self.assertEqual(self.by_code["F13.14"]["encoding"], "bcd")
        self.assertEqual(
            self.editor._format_value(0x0011, self.by_code["F13.14"]),
            "011",
        )
        self.assertEqual(
            self.editor._encode_value(self.by_code["F13.14"], "011"),
            0x0011,
        )
        self.assertEqual(
            self.editor._format_value(0x2000, self.by_code["F14.14"]),
            "2000",
        )
        self.assertEqual(
            self.editor._encode_value(self.by_code["F14.14"], "2000"),
            0x2000,
        )
        self.assertEqual(
            self.editor._format_value(0x0000, self.by_code["F16.02"]),
            "00",
        )
        self.assertEqual(self.by_code["F05.18"]["encoding"], "function_code")
        self.assertEqual(
            self.editor._format_value(0x2500, self.by_code["F05.18"]),
            "25.00",
        )
        self.assertEqual(
            self.editor._encode_value(self.by_code["F05.18"], "25.00"),
            0x2500,
        )
        self.assertEqual(
            self.editor._format_value(5000, self.by_code["F01.01"]),
            "50.00",
        )
        self.assertEqual(self.by_code["F11.07"]["scale"], 100)
        self.assertEqual(self.by_code["F11.08"]["scale"], 100)
        self.assertEqual(
            self.editor._format_value(50, self.by_code["F11.07"]),
            "000.50",
        )
        self.assertEqual(
            self.editor._format_value(25, self.by_code["F11.08"]),
            "00.25",
        )
        self.assertEqual(
            self.editor._encode_value(self.by_code["F11.07"], "000.50"),
            50,
        )
        self.assertEqual(
            self.editor._encode_value(self.by_code["F11.08"], "00.25"),
            25,
        )

    def test_en600_read_batches_are_contiguous_and_bounded(self):
        chunks = self.editor._contiguous_chunks(
            self.profile.parameters,
            self.profile.max_read_registers,
        )
        self.assertTrue(chunks)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 10)
            addresses = [parameter["address"] for parameter in chunk]
            self.assertEqual(
                addresses,
                list(range(addresses[0], addresses[0] + len(addresses))),
            )

    def test_en600_hex_parameter_round_trip(self):
        parameter = self.by_code["F10.01"]
        raw = self.editor._encode_value(parameter, "A20")
        self.assertEqual(raw, 0xA20)
        self.assertEqual(self.editor._format_value(raw, parameter), "A20")

    def test_en600_action_parameters_are_not_replayed_by_bulk_write(self):
        self.assertTrue(self.by_code["F00.14"]["write_only_if_edited"])
        self.assertTrue(self.by_code["F00.27"]["write_only_if_edited"])

    def test_en600_reserved_parameters_are_visible_but_read_only(self):
        self.assertFalse(any(code.startswith("F27.") for code in self.by_code))
        reserved = [
            parameter
            for parameter in self.profile.parameters
            if "reserved" in parameter["description"].lower()
        ]
        self.assertTrue(reserved)
        self.assertTrue(all(parameter["read_only"] for parameter in reserved))
        self.assertTrue(self.by_code["F07.17"]["read_only"])
        self.assertEqual(self.by_code["F07.17"]["display_width"], 5)
        self.assertEqual(
            self.editor._format_value(0, self.by_code["F07.17"]),
            "00000",
        )

    def test_en600_fault_records_are_read_only(self):
        fault_records = [
            parameter
            for parameter in self.profile.parameters
            if parameter["group"] == "F26"
        ]
        self.assertTrue(fault_records)
        self.assertTrue(all(parameter["read_only"] for parameter in fault_records))


if __name__ == "__main__":
    unittest.main()
