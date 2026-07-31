"""Revision detection is data-driven and never writes to the drive."""

import unittest

from enc_editor import detection
from enc_editor.catalog import load_catalog

CATALOG = load_catalog()
AUTO = CATALOG["en600_auto"]


class FakeResult:
    def __init__(self, registers=None, error=False):
        self.registers = registers or []
        self._error = error

    def isError(self):
        return self._error

    def __str__(self):
        return "Modbus error"


class FakeLink:
    """Records every read; a write would raise AttributeError."""

    def __init__(self, responses):
        self.responses = responses
        self.reads = []

    def read_registers(self, address, count=1):
        self.reads.append((address, count))
        return self.responses.get(address, FakeResult(error=True))


PROBE = 0x021A
LINK_CHECK = 0x0000


class DetectionTests(unittest.TestCase):
    def test_only_auto_profiles_need_detection(self):
        self.assertTrue(detection.needs_detection(AUTO))
        for key in ("eds800", "en600_v2", "en600_v5"):
            self.assertFalse(detection.needs_detection(CATALOG[key]))

    def test_value_inside_the_documented_range_selects_v5(self):
        link = FakeLink({LINK_CHECK: FakeResult([1]), PROBE: FakeResult([100])})
        result = detection.detect(CATALOG, AUTO, link)
        self.assertIs(result.profile, CATALOG["en600_v5"])
        self.assertEqual(result.value, 100)
        self.assertEqual(result.probe_code, "F02.26")

    def test_missing_probe_register_falls_back_to_the_legacy_map(self):
        link = FakeLink({LINK_CHECK: FakeResult([1]), PROBE: FakeResult(error=True)})
        result = detection.detect(CATALOG, AUTO, link)
        self.assertIs(result.profile, CATALOG["en600_v2"])
        self.assertIsNone(result.value)
        self.assertEqual(result.displayed_value, "N/A")

    def test_out_of_range_value_falls_back(self):
        link = FakeLink({LINK_CHECK: FakeResult([1]), PROBE: FakeResult([7])})
        self.assertIs(detection.detect(CATALOG, AUTO, link).profile, CATALOG["en600_v2"])

    def test_a_dead_link_raises_instead_of_guessing(self):
        link = FakeLink({LINK_CHECK: FakeResult(error=True)})
        with self.assertRaises(ConnectionError):
            detection.detect(CATALOG, AUTO, link)

    def test_detection_reads_only_two_registers(self):
        link = FakeLink({LINK_CHECK: FakeResult([1]), PROBE: FakeResult([100])})
        detection.detect(CATALOG, AUTO, link)
        self.assertEqual(link.reads, [(LINK_CHECK, 1), (PROBE, 1)])


if __name__ == "__main__":
    unittest.main()
