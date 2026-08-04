"""Regression tests for the EN600 PDF table extractor."""

import unittest

from tools.extract_en600_parameters import infer_limits, inherit_same_as


class ExtractorTests(unittest.TestCase):
    def test_hex_ranges_are_read_as_hexadecimal(self):
        for text, maximum in (("00~FFH", 0xFF), ("000H~E22H", 0xE22)):
            with self.subTest(text=text):
                self.assertEqual(infer_limits(text, 1, 2, "hex")[1], maximum)

    def test_enum_ranges_include_reserved_tail(self):
        self.assertEqual(
            infer_limits("0: disabled 1: enabled 2~15: Reserved", 1, None)[1],
            15,
        )

    def test_same_as_inherits_storage_and_validation_fields(self):
        source = {
            "code": "F08.18",
            "minimum": 0.0,
            "maximum": 96.0,
            "scale": 1,
            "encoding": "numeric",
            "display_width": 2,
        }
        target = {
            "code": "F08.19",
            "minimum": 0.0,
            "maximum": 65535.0,
            "scale": 1,
            "encoding": "numeric",
        }
        inherit_same_as(target, source)
        self.assertEqual(target["same_as"], "F08.18")
        self.assertEqual(target["maximum"], 96.0)
        self.assertEqual(target["display_width"], 2)


if __name__ == "__main__":
    unittest.main()
