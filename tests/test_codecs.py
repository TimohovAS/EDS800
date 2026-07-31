"""Value codecs: formatting, encoding and validation round-trips."""

import unittest

from enc_editor import codecs
from enc_editor.catalog import load_catalog

CATALOG = load_catalog()
EDS800 = CATALOG["eds800"].by_code()
EN600 = CATALOG["en600_v5"].by_code()


class NumericCodecTests(unittest.TestCase):
    def test_scaled_round_trip(self):
        parameter = EDS800["F0.01"]
        raw = codecs.encode_value(parameter, "50.25")
        self.assertEqual(raw, 5025)
        self.assertEqual(codecs.format_value(raw, parameter), "50.25")

    def test_padded_integer_display(self):
        self.assertEqual(codecs.format_value(0, EN600["F07.17"]), "00000")

    def test_padded_decimal_display(self):
        self.assertEqual(codecs.format_value(50, EN600["F11.07"]), "000.50")
        self.assertEqual(codecs.format_value(25, EN600["F11.08"]), "00.25")
        self.assertEqual(codecs.encode_value(EN600["F11.07"], "000.50"), 50)

    def test_range_is_enforced(self):
        parameter = EDS800["F0.14"]  # torque boost, 0~20 %
        self.assertIsNone(codecs.validate_value(parameter, "4.0"))
        problem = codecs.validate_value(parameter, "25")
        self.assertEqual(problem.key, "valid.between")
        self.assertEqual(codecs.validate_value(parameter, "abc").key, "valid.number")

    def test_read_only_parameters_are_rejected(self):
        problem = codecs.validate_value(EN600["F26.00"], "1")
        self.assertEqual(problem.key, "valid.read_only")

    def test_decimal_keypad_digits_are_checked(self):
        """F06.21 packs five 0/1 settings into one decimal register."""
        parameter = EN600["F06.21"]
        self.assertIsNone(codecs.validate_value(parameter, "11111"))
        self.assertIsNone(codecs.validate_value(parameter, "10101"))
        self.assertEqual(codecs.encode_value(parameter, "10101"), 10101)
        self.assertEqual(codecs.validate_value(parameter, "99999").key, "valid.between")
        self.assertEqual(codecs.validate_value(parameter, "22222").key, "valid.between")
        self.assertEqual(codecs.validate_value(parameter, "01210").key, "valid.digit_limits")
        self.assertEqual(codecs.validate_value(parameter, "10101.5").key, "valid.digit_limits")

    def test_values_wider_than_a_register_are_rejected(self):
        parameter = {
            "code": "T0.00",
            "encoding": "numeric",
            "scale": 1,
            "range": "0~99999",
            "minimum": 0,
            "maximum": 99999,
            "unit": "",
        }
        self.assertEqual(
            codecs.validate_value(parameter, "99999").key, "valid.register_range"
        )
        self.assertIsNone(codecs.validate_value(parameter, "65535"))


class BcdCodecTests(unittest.TestCase):
    def test_round_trip(self):
        parameter = EDS800["F2.11"]
        raw = codecs.encode_value(parameter, "1111")
        self.assertEqual(raw, 0x1111)
        self.assertEqual(codecs.format_value(raw, parameter), "1111")

    def test_keypad_widths_follow_the_manual(self):
        self.assertEqual(codecs.format_value(0x0500, EN600["F00.14"]), "500")
        self.assertEqual(codecs.format_value(0x1000, EN600["F01.16"]), "1000")
        self.assertEqual(codecs.format_value(0x0011, EN600["F13.14"]), "011")
        self.assertEqual(codecs.format_value(0x2000, EN600["F14.14"]), "2000")
        self.assertEqual(codecs.format_value(0x0000, EN600["F16.02"]), "00")
        self.assertEqual(codecs.encode_value(EN600["F13.14"], "011"), 0x0011)

    def test_impossible_digit_combinations_are_rejected(self):
        """A valid alphabet is not enough: each digit selects one setting."""
        for code, accepted, rejected in (
            ("F14.14", "2000", "2222"),  # documented as 0000~2112
            ("F00.14", "500", "555"),
            ("F13.14", "011", "911"),
        ):
            with self.subTest(code=code):
                parameter = EN600[code]
                self.assertIsNone(codecs.validate_value(parameter, accepted))
                problem = codecs.validate_value(parameter, rejected)
                self.assertEqual(problem.key, "valid.digit_limits")
                self.assertEqual(problem.params["pattern"], parameter["digit_limits"])

    def test_unconstrained_digits_stay_free(self):
        """A digit the manual does not describe must not be guessed at."""
        parameter = EN600["F00.21"]
        self.assertEqual(parameter["digit_limits"][:2], "**")
        self.assertIsNone(codecs.validate_value(parameter, "9911"))
        self.assertEqual(
            codecs.validate_value(parameter, "0099").key, "valid.digit_limits"
        )

    def test_digit_alphabet_is_enforced(self):
        parameter = EDS800["F0.03"]  # run direction, digits from "01"
        self.assertIsNone(codecs.validate_value(parameter, "010"))
        self.assertEqual(codecs.validate_value(parameter, "020").key, "valid.bcd_digits")
        self.assertEqual(codecs.validate_value(parameter, "01").key, "valid.bcd_digits")

    def test_undecodable_register_is_reported(self):
        self.assertEqual(codecs.format_value(0x0F0F, EDS800["F0.03"]), codecs.BCD_ERROR)


class HexCodecTests(unittest.TestCase):
    def test_round_trip(self):
        parameter = EN600["F10.01"]
        raw = codecs.encode_value(parameter, "A20")
        self.assertEqual(raw, 0xA20)
        self.assertEqual(codecs.format_value(raw, parameter), "A20")

    def test_width_is_enforced(self):
        self.assertEqual(codecs.validate_value(EN600["F10.01"], "A2").key, "valid.hex_digits")


class FunctionCodeCodecTests(unittest.TestCase):
    def test_round_trip(self):
        parameter = EN600["F05.18"]
        self.assertEqual(codecs.format_value(0x2500, parameter), "25.00")
        self.assertEqual(codecs.encode_value(parameter, "25.00"), 0x2500)

    def test_group_limit_is_enforced(self):
        parameter = EN600["F05.18"]
        self.assertIsNone(codecs.validate_value(parameter, "25.00"))
        self.assertEqual(
            codecs.validate_value(parameter, "99.00").key, "valid.function_group"
        )
        self.assertEqual(codecs.validate_value(parameter, "hello").key, "valid.function_code")

    def test_undecodable_register_is_reported(self):
        self.assertEqual(codecs.format_value(0xFFFF, EN600["F05.18"]), codecs.CODE_ERROR)


class RegistryTests(unittest.TestCase):
    def test_unknown_encoding_is_rejected(self):
        with self.assertRaises(KeyError):
            codecs.codec_for({"code": "X", "encoding": "morse"})

    def test_a_new_encoding_only_needs_registration(self):
        class DoublingCodec(codecs.Codec):
            name = "test_doubling"

            def format(self, raw, parameter):
                return str(int(raw) * 2)

            def encode(self, text, parameter):
                return int(text) // 2

            def validate(self, text, parameter):
                return None

        codecs.register(DoublingCodec())
        try:
            parameter = {"code": "T0.00", "encoding": "test_doubling", "scale": 1}
            self.assertEqual(codecs.format_value(21, parameter), "42")
            self.assertEqual(codecs.encode_value(parameter, "42"), 21)
        finally:
            codecs.CODECS.pop("test_doubling")

    def test_format_never_raises_on_bad_input(self):
        self.assertEqual(codecs.format_value("", EDS800["F0.01"]), "")
        self.assertEqual(codecs.format_value("junk", EDS800["F0.01"]), "junk")

    def test_encode_reports_a_translatable_problem(self):
        with self.assertRaises(codecs.CodecError) as caught:
            codecs.encode_value(EDS800["F0.01"], "junk")
        self.assertEqual(caught.exception.problem.key, "error.invalid_value")


if __name__ == "__main__":
    unittest.main()
