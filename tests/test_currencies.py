"""Currency changes cannot relabel posted financial history."""
import sqlite3
import unittest

import erp
from currencies import CURRENCIES, currency_label, currency_metadata, normalize_currency, validate_currency_change


class CurrencyCase(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE journal(id INTEGER PRIMARY KEY)')

    def tearDown(self):
        self.db.close()

    def test_choose_base_currency_before_financial_activity(self):
        self.assertEqual(validate_currency_change(self.db, 'ج.م', 'SAR'), 'SAR')
        self.assertEqual(normalize_currency(' usd '), 'USD')
        self.assertFalse(currency_metadata(self.db)['currency_locked'])
        self.assertEqual(len({row['code'] for row in CURRENCIES}), len(CURRENCIES))
        self.assertEqual(currency_label('ج.م', 'en'), 'EGP')
        self.assertEqual(currency_label('SAR', 'ar'), 'ر.س')

    def test_posted_history_locks_currency_but_accepts_equivalent_legacy_label(self):
        self.db.execute('INSERT INTO journal DEFAULT VALUES')
        self.assertTrue(currency_metadata(self.db)['currency_locked'])
        with self.assertRaises(erp.BusinessError):
            validate_currency_change(self.db, 'ج.م', 'USD')
        self.assertEqual(validate_currency_change(self.db, 'ج.م', 'EGP'), 'EGP')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0], 1)

    def test_unsupported_currency_cannot_change_money_precision(self):
        for code in ('', 'JPY', 'KWD', 'not-a-currency'):
            with self.subTest(code=code), self.assertRaises(erp.BusinessError):
                validate_currency_change(self.db, 'EGP', code)

    def test_custom_legacy_currency_is_preserved_by_unrelated_settings_saves(self):
        self.db.execute('INSERT INTO journal DEFAULT VALUES')
        label = 'عملة الشركة الخاصة'
        self.assertEqual(validate_currency_change(self.db, label, label), label)
        self.assertEqual(currency_label(label, 'en'), label)
        with self.assertRaises(erp.BusinessError):
            validate_currency_change(self.db, label, 'EGP')
