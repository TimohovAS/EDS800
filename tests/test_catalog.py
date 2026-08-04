"""Invariants every profile directory must satisfy.

These tests are written against the catalogue as a whole, so a model added
later is covered without touching this file.
"""

import unittest

from enc_editor import codecs
from enc_editor.catalog import ENCODING_FIELDS, REQUIRED_PARAMETER_FIELDS, load_catalog

CATALOG = load_catalog()


class CatalogInvariantTests(unittest.TestCase):
    def test_catalog_is_not_empty(self):
        self.assertTrue(len(CATALOG))

    def test_every_profile_has_identity_and_link(self):
        for profile in CATALOG:
            with self.subTest(profile=profile.key):
                self.assertTrue(profile.model)
                self.assertTrue(profile.label("en"))
                self.assertIn(profile.link.parity, {"N", "E", "O"})
                self.assertGreaterEqual(profile.link.max_read_registers, 1)
                self.assertTrue(1 <= profile.link.device_id <= 247)

    def test_parameters_are_complete_unique_and_addressable(self):
        for profile in CATALOG:
            codes, addresses = set(), set()
            for parameter in profile.parameters:
                with self.subTest(profile=profile.key, code=parameter["code"]):
                    self.assertFalse(REQUIRED_PARAMETER_FIELDS - parameter.keys())
                    self.assertNotIn(parameter["code"], codes)
                    self.assertNotIn(parameter["address"], addresses)
                    self.assertTrue(0 <= parameter["address"] <= 0xFFFF)
                    codes.add(parameter["code"])
                    addresses.add(parameter["address"])

    def test_addresses_follow_the_manifest_group_table(self):
        for profile in CATALOG:
            if not profile.group_ids:
                continue
            for parameter in profile.parameters:
                group, _, number = parameter["code"].partition(".")
                expected = (profile.group_ids[group] << 8) | int(number)
                with self.subTest(profile=profile.key, code=parameter["code"]):
                    self.assertEqual(parameter["address"], expected)

    def test_every_group_has_a_manual_title(self):
        for profile in CATALOG:
            for group in profile.groups:
                with self.subTest(profile=profile.key, group=group):
                    self.assertNotEqual(profile.group_label(group, "en"), group)
                    self.assertTrue(profile.group_label(group, "ru"))

    def test_every_encoding_is_registered_and_complete(self):
        for profile in CATALOG:
            for parameter in profile.parameters:
                encoding = parameter["encoding"]
                with self.subTest(profile=profile.key, code=parameter["code"]):
                    self.assertIn(encoding, codecs.CODECS)
                    for name in ENCODING_FIELDS.get(encoding, ()):
                        self.assertIn(name, parameter)

    def test_defaults_are_writable_values_or_notes(self):
        for profile in CATALOG:
            for parameter in profile.parameters:
                default = parameter["default"]
                with self.subTest(profile=profile.key, code=parameter["code"]):
                    self.assertIsInstance(default, str)
                    if default and parameter["encoding"] == "numeric":
                        float(default)  # must not raise
                    if not default:
                        self.assertIsInstance(parameter.get("default_note", ""), str)

    def test_writable_maximums_fit_one_register(self):
        for profile in CATALOG:
            for parameter in profile.parameters:
                if parameter.get("read_only"):
                    continue
                with self.subTest(profile=profile.key, code=parameter["code"]):
                    self.assertLessEqual(parameter["maximum"] * parameter["scale"], 0xFFFF)

    def test_digit_limits_match_the_field_width(self):
        for profile in CATALOG:
            for parameter in profile.parameters:
                limits = parameter.get("digit_limits")
                if not limits:
                    continue
                with self.subTest(profile=profile.key, code=parameter["code"]):
                    width = parameter.get("digits") or parameter.get("display_width")
                    self.assertEqual(len(limits), width)
                    self.assertTrue(all(c == "*" or c in "0123456789ABCDEF" for c in limits))

    def test_keypad_fields_carry_digit_limits(self):
        """Digit fields without limits would accept impossible combinations."""
        for profile in CATALOG:
            missing = [
                parameter["code"]
                for parameter in profile.parameters
                if parameter["encoding"] in ("bcd", "hex")
                and not parameter.get("read_only")
                and not parameter.get("digit_limits")
            ]
            with self.subTest(profile=profile.key):
                # Only rows whose manual text is unusable may lack limits.
                self.assertLessEqual(len(missing), 1, missing)

    def test_documented_defaults_pass_validation(self):
        """A default the manual prints must be a value the editor accepts."""
        for profile in CATALOG:
            for parameter in profile.parameters:
                if parameter.get("read_only") or not parameter["default"]:
                    continue
                with self.subTest(profile=profile.key, code=parameter["code"]):
                    self.assertIsNone(codecs.validate_value(parameter, parameter["default"]))

    def test_every_value_formats_without_raising(self):
        for profile in CATALOG:
            for parameter in profile.parameters:
                with self.subTest(profile=profile.key, code=parameter["code"]):
                    self.assertIsInstance(codecs.format_value(0x1234, parameter), str)

    def test_translations_cover_every_parameter(self):
        for profile in CATALOG:
            codes = {parameter["code"] for parameter in profile.parameters}
            for language, catalogue in profile.translations.items():
                with self.subTest(profile=profile.key, language=language):
                    self.assertEqual(codes - catalogue.keys(), set())
                    self.assertTrue(
                        all(entry.get("description") for entry in catalogue.values())
                    )

    def test_translated_text_falls_back_to_english(self):
        for profile in CATALOG:
            for parameter in profile.parameters:
                with self.subTest(profile=profile.key, code=parameter["code"]):
                    # An unknown language never blanks the table.
                    self.assertEqual(
                        profile.text(parameter, "description", "xx"),
                        parameter["description"],
                    )
                    self.assertTrue(profile.text(parameter, "range", "ru") or not parameter["range"])

    def test_same_as_rows_are_explicit_and_inherit_validation(self):
        for profile in CATALOG:
            by_code = profile.by_code()
            for parameter in profile.parameters:
                if "same as above" not in parameter["range"].lower():
                    continue
                with self.subTest(profile=profile.key, code=parameter["code"]):
                    source_code = parameter.get("same_as")
                    self.assertIn(source_code, by_code)
                    source = by_code[source_code]
                    for field in ("minimum", "maximum", "scale", "encoding"):
                        self.assertEqual(parameter[field], source[field])
                    self.assertIn(source_code, profile.range_text(parameter, "ru"))

    def test_range_text_names_every_structured_reference(self):
        for profile in CATALOG:
            for parameter in profile.parameters:
                text = profile.range_text(parameter, "ru")
                for field in ("same_as", "minimum_from", "maximum_from"):
                    reference = parameter.get(field)
                    if reference:
                        with self.subTest(
                            profile=profile.key, code=parameter["code"], field=field
                        ):
                            self.assertIn(reference, text)

    def test_keys_are_unique_and_resolvable(self):
        seen = set()
        for profile in CATALOG:
            with self.subTest(key=profile.key):
                self.assertNotIn(profile.key, seen)
                seen.add(profile.key)
                self.assertIs(CATALOG.resolve(profile.key), profile)
        with self.assertRaises(KeyError):
            CATALOG.resolve("no_such_model")

    def test_detection_targets_exist_and_borrow_a_table(self):
        for profile in CATALOG:
            if not profile.detect:
                continue
            with self.subTest(profile=profile.key):
                self.assertTrue(profile.parameters)
                targets = [rule["profile"] for rule in profile.detect.get("rules", ())]
                targets.append(profile.detect["fallback"])
                for target in targets:
                    self.assertIn(target, CATALOG)
                probe = profile.detect.get("probe")
                self.assertIn(probe, {p["code"] for p in profile.parameters})

    def test_labels_are_unique_per_language(self):
        for language in ("en", "ru", "sr"):
            labels = CATALOG.labels(language)
            with self.subTest(language=language):
                self.assertEqual(len(labels), len(CATALOG))


class KnownModelTests(unittest.TestCase):
    """Spot checks that pin the shipped models to their manuals."""

    def test_expected_models_are_present(self):
        self.assertEqual(
            set(CATALOG.keys),
            {"eds800", "en600_auto", "en600_v2", "en600_v5"},
        )

    def test_eds800_documented_addresses(self):
        by_code = CATALOG["eds800"].by_code()
        self.assertEqual(len(CATALOG["eds800"].parameters), 198)
        self.assertEqual(by_code["F0.03"]["address"], 0x0003)
        self.assertEqual(by_code["F2.11"]["address"], 0x020B)
        self.assertEqual(by_code["Fd.14"]["address"], 0x0D0E)
        self.assertTrue(all(p["read_only"] for p in CATALOG["eds800"].parameters if p["group"] == "Fd"))

    def test_en600_documented_addresses_and_sizes(self):
        v5 = CATALOG["en600_v5"]
        v2 = CATALOG["en600_v2"]
        self.assertEqual(len(v5.parameters), 651)
        self.assertEqual(len(v2.parameters), 562)
        by_code = v5.by_code()
        self.assertEqual(by_code["F05.03"]["address"], 0x0503)
        self.assertEqual(by_code["F02.26"]["address"], 0x021A)
        self.assertEqual(by_code["F26.17"]["address"], 0x1A11)
        self.assertTrue(all(p["read_only"] for p in v5.parameters if p["group"] == "F26"))

    def test_en600_action_parameters_are_not_replayed(self):
        by_code = CATALOG["en600_v5"].by_code()
        self.assertTrue(by_code["F00.14"]["write_only_if_edited"])
        self.assertTrue(by_code["F00.27"]["write_only_if_edited"])

    def test_en600_auto_borrows_the_v5_table(self):
        self.assertEqual(
            CATALOG["en600_auto"].parameters, CATALOG["en600_v5"].parameters
        )

    def test_russian_catalogue_is_loaded_for_both_revisions(self):
        for key in ("en600_v2", "en600_v5"):
            profile = CATALOG[key]
            with self.subTest(profile=key):
                self.assertEqual(profile.translated_languages, ("ru",))
                parameter = profile.by_code()["F01.01"]
                self.assertNotEqual(
                    profile.text(parameter, "description", "ru"),
                    parameter["description"],
                )

    def test_russian_ranges_use_a_decimal_dot(self):
        profile = CATALOG["en600_v5"]
        parameter = profile.by_code()["F01.11"]
        self.assertNotIn(",0", profile.text(parameter, "range", "ru"))

    def test_v5_russian_f0119_documents_both_control_digits(self):
        profile = CATALOG["en600_v5"]
        parameter = profile.by_code()["F01.19"]
        text = profile.text(parameter, "range", "ru")
        self.assertIn("Разряд единиц", text)
        self.assertIn("Разряд десятков", text)
        self.assertIn("десятичной точки", text)

    def test_v5_frequency_limit_ranges_name_the_related_parameter(self):
        profile = CATALOG["en600_v5"]
        by_code = profile.by_code()
        self.assertIn("F01.12", profile.text(by_code["F01.11"], "range", "ru"))
        self.assertIn("F01.11", profile.text(by_code["F01.12"], "range", "ru"))

    def test_en600_page_boundary_enums_are_complete(self):
        expected = {
            "en600_v2": {
                "F00.01": (65, "57~65"),
                "F08.18": (96, "94~96"),
                "F09.00": (60, "42~60"),
                "F09.35": (25, "20~25"),
                "F18.00": (15, "11~15"),
                "F26.00": (50, "40~50"),
            },
            "en600_v5": {
                "F00.01": (70, "67~70"),
                "F01.00": (14, "10~14"),
                "F01.06": (8, "8:"),
                "F08.18": (96, "93~96"),
                "F09.00": (60, "53~60"),
                "F09.35": (25, "20~25"),
                "F14.17": (8, "8:"),
                "F16.05": (4, "3~4"),
                "F18.00": (15, "11~15"),
                "F26.00": (50, "42~50"),
            },
        }
        for profile_key, cases in expected.items():
            profile = CATALOG[profile_key]
            by_code = profile.by_code()
            for code, (maximum, marker) in cases.items():
                with self.subTest(profile=profile_key, code=code):
                    self.assertEqual(by_code[code]["maximum"], maximum)
                    english = by_code[code]["range"].replace("～", "~")
                    russian = profile.text(by_code[code], "range", "ru").replace("～", "~")
                    self.assertIn(marker, english)
                    self.assertIn(marker, russian)

    def test_en600_hex_ranges_use_hexadecimal_limits(self):
        for profile_key in ("en600_v2", "en600_v5"):
            by_code = CATALOG[profile_key].by_code()
            with self.subTest(profile=profile_key, code="F05.08"):
                self.assertEqual(by_code["F05.08"]["maximum"], 0xFF)
            for number in range(1, 16):
                code = f"F10.{number:02d}"
                with self.subTest(profile=profile_key, code=code):
                    self.assertEqual(by_code[code]["maximum"], 0xE22)

    def test_en600_reserved_enum_tails_remain_selectable(self):
        for profile_key in ("en600_v2", "en600_v5"):
            parameter = CATALOG[profile_key].by_code()["F00.19"]
            with self.subTest(profile=profile_key):
                self.assertEqual(parameter["maximum"], 10)

    def test_v5_page_boundary_composite_fields_have_all_digits(self):
        by_code = CATALOG["en600_v5"].by_code()
        self.assertEqual(by_code["F00.21"]["digit_limits"], "2111")
        self.assertEqual(by_code["F10.00"]["digit_limits"], "1123")
        for code in ("F00.21", "F10.00"):
            text = CATALOG["en600_v5"].text(by_code[code], "range", "ru")
            self.assertIn("Разряд сотен", text)
            self.assertIn("Разряд тысяч", text)

    def test_v2_page_boundary_composite_fields_have_all_digits(self):
        profile = CATALOG["en600_v2"]
        by_code = profile.by_code()
        expected = {
            "F00.21": "1111",
            "F05.02": "135",
            "F06.00": "2222",
            "F06.21": "11111",
            "F19.32": "1222",
        }
        for code, digit_limits in expected.items():
            with self.subTest(code=code):
                self.assertEqual(by_code[code]["digit_limits"], digit_limits)
                text = profile.text(by_code[code], "range", "ru")
                self.assertIn("Разряд", text)

    def test_v2_russian_composite_and_conditional_text_is_complete(self):
        profile = CATALOG["en600_v2"]
        by_code = profile.by_code()
        pwm = profile.text(by_code["F04.10"], "range", "ru")
        self.assertIn("Разряд сотен", pwm)
        self.assertIn("Разряд тысяч", pwm)
        torque = profile.text(by_code["F18.16"], "range", "ru")
        self.assertIn("F00.24", torque)


if __name__ == "__main__":
    unittest.main()
