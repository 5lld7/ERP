"""Customer PDFs include only the saved service method, below quote totals."""
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


class ServiceMethodPDFCase(unittest.TestCase):
    def setUp(self):
        self.settings = {'company_name': 'Serviq Test', 'currency': 'EGP'}
        self.document = {
            'customer': 'عميل الاختبار Customer', 'number': 'INS-METHOD-01', 'date': '2026-10-22',
            'subtotal': 150, 'discount': 0, 'tax_rate': 14, 'tax': 21, 'total': 171,
            'note': 'PRIVATE-DOCUMENT-NOTE',
            'lines': [
                {'product_id': 1, 'item_type': 'service', 'name': 'Cleaning service خدمة تنظيف',
                 'sku': 'SRV-01', 'quantity': 1, 'unit': 'زيارة', 'unit_en': 'Visit',
                 'price': 100, 'total': 100, 'cost': 'PRIVATE-SERVICE-COST',
                 'service_method': 'METHOD-START\nحماية الموقع ثم تنفيذ الخدمة.\nMETHOD-END'},
                {'product_id': 2, 'item_type': 'product', 'name': 'Cleaning product',
                 'sku': 'PRD-01', 'quantity': 1, 'unit': 'عبوة', 'unit_en': 'Pack',
                 'price': 50, 'total': 50, 'service_method': 'PRIVATE-PRODUCT-METHOD',
                 'note': 'PRIVATE-PRODUCT-NOTE'},
            ],
        }

    def extract(self, content):
        if not shutil.which('pdftotext'):
            self.skipTest('Poppler pdftotext is unavailable')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'quote.pdf'
            path.write_bytes(content)
            text = subprocess.run(['pdftotext', '-layout', str(path), '-'],
                                  check=True, capture_output=True).stdout.decode('utf-8')
        return re.sub('[\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', text)

    def test_service_method_is_after_totals_in_both_languages_and_excludes_private_fields(self):
        original = copy.deepcopy(self.document)
        for language, heading in (('ar', 'طريقة عمل الخدمة'), ('en', 'Service delivery method')):
            with self.subTest(language=language):
                text = self.extract(render_quotation(self.document, self.settings, language))
                self.assertIn(heading, text)
                self.assertLess(text.index('171.00'), text.index(heading))
                self.assertGreater(text.index('METHOD-START'), text.index(heading))
                self.assertIn('METHOD-END', text)
                for private in ('PRIVATE-DOCUMENT-NOTE', 'PRIVATE-PRODUCT-METHOD',
                                'PRIVATE-PRODUCT-NOTE', 'PRIVATE-SERVICE-COST'):
                    self.assertNotIn(private, text)
        self.assertEqual(self.document, original)

    def test_product_or_blank_service_method_does_not_create_method_section(self):
        self.document['lines'][0]['service_method'] = '  \n  '
        text = self.extract(render_quotation(self.document, self.settings, 'en'))
        self.assertNotIn('Service delivery method', text)
        self.assertNotIn('PRIVATE-PRODUCT-METHOD', text)

    def test_long_saved_methods_paginate_without_truncating_service_instructions(self):
        method = 'LONG-METHOD-START\n' + '\n'.join(
            f'Step {index:03d}: Clean the site and follow the service procedure. تنظيف وتعقيم الموقع.'
            for index in range(1, 151)) + '\nLONG-METHOD-END'
        self.document['lines'][0]['service_method'] = method
        content = render_quotation(self.document, self.settings, 'ar')
        self.assertGreater(len(re.findall(rb'/Type /Page\b', content)), 2)
        text = self.extract(content)
        self.assertIn('LONG-METHOD-START', text)
        self.assertIn('LONG-METHOD-END', text)
        self.assertIn('Step 150', text)

    def test_unit_uses_supplied_english_label_only_for_english_pdf(self):
        english = self.extract(render_quotation(self.document, self.settings, 'en'))
        arabic = self.extract(render_quotation(self.document, self.settings, 'ar'))
        self.assertIn('Visit', english)
        self.assertIn('Pack', english)
        self.assertNotIn('زيارة', english)
        self.assertIn('زيارة', arabic)


if __name__ == '__main__':
    unittest.main()
