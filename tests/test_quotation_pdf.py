"""Public quotation export checks, using only synthetic company/customer data."""
import copy
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quotation_pdf import render_quotation


class QuotationPDFCase(unittest.TestCase):
    def setUp(self):
        self.settings = {
            'company_name': 'شركة الاختبار Test company',
            'company_address': 'Synthetic Street 12', 'company_phone': '+20 123456789',
            'tax_number': 'TAX-101', 'currency': 'SAR',
            'secret': 'DO-NOT-EXPORT-COMPANY-SECRET',
        }
        self.document = {
            'customer': 'شركة أحمد / Ahmed Customer',
            'number': 'QUO-TEST-101', 'date': '2026-10-19',
            'appointment_date': '2026-10-22', 'location': 'Test inspection site',
            'subtotal': 3000, 'discount': 100, 'tax_rate': 14, 'tax': 406, 'total': 3306,
            'note': 'PRIVATE-INTERNAL-NOTE', 'profit': 'PRIVATE-INTERNAL-PROFIT',
            'audit': 'PRIVATE-INTERNAL-AUDIT',
            'lines': [{
                'name': 'خدمة معاينة Inspection service', 'sku': 'SKU-TEST-1',
                'unit': 'قطعة', 'quantity': 2, 'price': 1500, 'total': 3000,
                'cost': 'PRIVATE-INTERNAL-COST',
            }],
        }

    def extract(self, content):
        if not shutil.which('pdftotext'):
            self.skipTest('Poppler pdftotext is unavailable; PDF structure tests still run')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'quotation.pdf'
            path.write_bytes(content)
            text = subprocess.run(['pdftotext', '-layout', str(path), '-'],
                                  check=True, capture_output=True).stdout.decode('utf-8')
        # PDF extractors insert directional formatting marks around Arabic runs.
        return re.sub('[\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', text)

    def test_unicode_fonts_and_valid_pdf_for_both_languages(self):
        for language in ('ar', 'en'):
            with self.subTest(language=language):
                content = render_quotation(self.document, self.settings, language)
                self.assertTrue(content.startswith(b'%PDF-'))
                self.assertTrue(content.rstrip().endswith(b'%%EOF'))
                self.assertIn(b'/FontFile2', content)
                self.assertIn(b'/ToUnicode', content)
                self.assertEqual(len(re.findall(rb'/Type /Page\b', content)), 1)

    def test_client_pdf_includes_quote_customer_prices_and_currency_only(self):
        for language, title in (('ar', 'عرض سعر معاينة'), ('en', 'Inspection quotation')):
            with self.subTest(language=language):
                text = self.extract(render_quotation(self.document, self.settings, language))
                for public in (title, 'Serviq', 'أحمد', 'Ahmed Customer', 'QUO-TEST-101',
                               '2026-10-19', '2026-10-22', 'Test inspection site',
                               'Test company', 'Synthetic Street 12', '+20 123456789', 'TAX-101',
                               'Inspection service', 'SKU-TEST-1', '1,500.00',
                               '3,000.00', '100.00', '406.00', '3,306.00', 'SAR'):
                    self.assertIn(public, text)
                for private in ('PRIVATE-INTERNAL', 'DO-NOT-EXPORT', 'cost', 'profit', 'audit'):
                    self.assertNotIn(private, text)

    def test_long_quote_paginates_and_preserves_first_and_last_item(self):
        self.document['lines'] = [dict(self.document['lines'][0],
                                      name=f'Inspection service {index:03d} خدمة معاينة',
                                      sku=f'LONG-{index:03d}') for index in range(1, 131)]
        content = render_quotation(self.document, self.settings, 'ar')
        self.assertGreater(len(re.findall(rb'/Type /Page\b', content)), 3)
        text = self.extract(content)
        self.assertIn('LONG-001', text)
        self.assertIn('LONG-130', text)
        self.assertIn('3,306.00', text)
        self.assertGreater(text.count('سعر الوحدة'), 1)

    def test_requests_do_not_mutate_source_or_leak_previous_customers(self):
        original = copy.deepcopy((self.document, self.settings))
        render_quotation(self.document, self.settings, 'ar')
        self.assertEqual(original, (self.document, self.settings))
        other = dict(self.document, customer='Independent Customer')
        text = self.extract(render_quotation(other, self.settings, 'en'))
        self.assertIn('Independent Customer', text)
        self.assertNotIn('Ahmed Customer', text)

    def test_existing_legacy_egp_currency_is_supported(self):
        self.settings['currency'] = 'ج.م'
        text = self.extract(render_quotation(self.document, self.settings, 'en'))
        self.assertIn('EGP', text)

    def test_long_valid_product_description_continues_without_truncation(self):
        self.document['lines'][0]['name'] = 'START-MARKER ' + 'وصف الخدمة Service description ' * 65 + ' END-MARKER'
        content = render_quotation(self.document, self.settings, 'ar')
        text = self.extract(content)
        self.assertIn('START-MARKER', text)
        self.assertIn('END-MARKER', text)
        self.assertIn('3,306.00', text)


if __name__ == '__main__':
    unittest.main()
