"""The scan-cache schema fingerprint must change when known def/keyed names change at equal counts."""
import unittest

from rimworld_translator.extraction import _schema_fingerprint
from rimworld_translator.schema import TranslationSchema


class SchemaFingerprintNameTests(unittest.TestCase):
    def test_known_defs_names_matter_not_only_count(self):
        a = TranslationSchema(known_defs=frozenset({'Steel', 'Gold'}))
        b = TranslationSchema(known_defs=frozenset({'Steel', 'Silver'}))
        self.assertNotEqual(_schema_fingerprint(a), _schema_fingerprint(b))

    def test_known_keyed_names_matter_not_only_count(self):
        a = TranslationSchema(known_keyed=frozenset({'A', 'B'}))
        b = TranslationSchema(known_keyed=frozenset({'A', 'C'}))
        self.assertNotEqual(_schema_fingerprint(a), _schema_fingerprint(b))

    def test_defs_and_keyed_are_not_interchangeable(self):
        a = TranslationSchema(known_defs=frozenset({'X'}))
        b = TranslationSchema(known_keyed=frozenset({'X'}))
        self.assertNotEqual(_schema_fingerprint(a), _schema_fingerprint(b))

    def test_same_names_give_same_fingerprint(self):
        a = TranslationSchema(known_defs=frozenset({'Steel', 'Gold'}))
        b = TranslationSchema(known_defs=frozenset({'Gold', 'Steel'}))
        self.assertEqual(_schema_fingerprint(a), _schema_fingerprint(b))


if __name__ == '__main__':
    unittest.main()
