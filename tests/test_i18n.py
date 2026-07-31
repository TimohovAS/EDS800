import string
import unittest

from enc_editor.i18n import LANGUAGES, TRANSLATIONS, UNITS, Translator, _plural_index

# The product name is deliberately identical in every language.
UNTRANSLATED_KEYS = {"app.name"}


def placeholders(value):
    forms = (value,) if isinstance(value, str) else value
    return {
        field
        for form in forms
        for _, field, _, _ in string.Formatter().parse(form)
        if field
    }


class TranslationTableTests(unittest.TestCase):
    def test_every_language_is_registered(self):
        self.assertEqual({code for code, _, _ in LANGUAGES}, set(TRANSLATIONS))

    def test_translations_cover_every_english_key(self):
        expected = set(TRANSLATIONS["en"]) - UNTRANSLATED_KEYS
        for language in ("ru", "sr"):
            with self.subTest(language=language):
                self.assertEqual(expected - set(TRANSLATIONS[language]), set())

    def test_no_language_defines_unknown_keys(self):
        for language, table in TRANSLATIONS.items():
            with self.subTest(language=language):
                self.assertEqual(set(table) - set(TRANSLATIONS["en"]), set())

    def test_placeholders_match_english(self):
        for language, table in TRANSLATIONS.items():
            for key, value in table.items():
                with self.subTest(language=language, key=key):
                    self.assertEqual(
                        placeholders(value),
                        placeholders(TRANSLATIONS["en"][key]),
                    )

    def test_plural_entries_have_one_form_per_category(self):
        expected = {"en": 2, "ru": 3, "sr": 3}
        for language, table in TRANSLATIONS.items():
            for key, value in table.items():
                if isinstance(value, tuple):
                    with self.subTest(language=language, key=key):
                        self.assertEqual(len(value), expected[language])

    def test_slavic_plural_categories(self):
        for language in ("ru", "sr"):
            with self.subTest(language=language):
                self.assertEqual(_plural_index(language, 1), 0)
                self.assertEqual(_plural_index(language, 21), 0)
                self.assertEqual(_plural_index(language, 3), 1)
                self.assertEqual(_plural_index(language, 24), 1)
                self.assertEqual(_plural_index(language, 5), 2)
                self.assertEqual(_plural_index(language, 11), 2)
                self.assertEqual(_plural_index(language, 112), 2)
        self.assertEqual(_plural_index("en", 1), 0)
        self.assertEqual(_plural_index("en", 2), 1)


class TranslatorTests(unittest.TestCase):
    def test_unknown_language_falls_back_to_english(self):
        translator = Translator("de")
        self.assertEqual(translator.language, "en")
        self.assertEqual(translator("action.cancel"), "Cancel")

    def test_unknown_key_returns_itself(self):
        self.assertEqual(Translator("ru")("no.such.key"), "no.such.key")

    def test_plural_forms_are_selected_per_language(self):
        russian = Translator("ru")
        self.assertEqual(russian.plural("count.parameters", 1), "1 параметр")
        self.assertEqual(russian.plural("count.parameters", 3), "3 параметра")
        self.assertEqual(russian.plural("count.parameters", 12), "12 параметров")
        serbian = Translator("sr")
        self.assertEqual(serbian.plural("count.parameters", 1), "1 parametar")
        self.assertEqual(serbian.plural("count.parameters", 3), "3 parametra")
        self.assertEqual(serbian.plural("count.parameters", 12), "12 parametara")
        english = Translator("en")
        self.assertEqual(english.plural("count.parameters", 1), "1 parameter")
        self.assertEqual(english.plural("count.parameters", 3), "3 parameters")

    def test_every_message_formats_in_every_language(self):
        samples = {
            "model": "EN600",
            "parameters": "651",
            "groups": "26",
            "version": "2.3.0",
            "group": "F05",
            "page": 57,
            "value": "5",
            "shown": 10,
            "total": 20,
            "n": 3,
            "ok": 9,
            "written": 4,
            "failed": 1,
            "file": "settings.json",
            "note": "",
            "title": "Reading",
            "done": 5,
            "error": "boom",
            "code": "F00.01",
            "port": "COM3",
            "link": "9600 8N1",
            "device_id": 1,
            "scope": "group F05",
            "count": "3",
            "edited": "2",
            "rest": 2,
            "problems": "F00.01",
            "details": "F00.01: error",
            "problem": "must be a number",
            "minimum": "0",
            "maximum": "10",
            "unit": " Hz",
            "digits": 3,
            "chars": "0123456789",
            "profile": "eds800",
            "pattern": "2112",
        }
        for language in TRANSLATIONS:
            translator = Translator(language)
            for key, value in TRANSLATIONS[language].items():
                forms = (value,) if isinstance(value, str) else value
                for form in forms:
                    with self.subTest(language=language, key=key):
                        needed = {
                            field
                            for _, field, _, _ in string.Formatter().parse(form)
                            if field
                        }
                        form.format(**{name: samples[name] for name in needed})
            self.assertEqual(translator.language, language)


if __name__ == "__main__":
    unittest.main()
