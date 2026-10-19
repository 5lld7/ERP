"""Bilingual response tests use temporary data and no external credentials."""
import csv
import io
import json
import os
import secrets
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import erp
import server
from api import index
from database import DatabaseUnavailable
from localization import csv_row_values, request_language, translate_error


class LanguageCase(unittest.TestCase):
    def test_language_preference_fallback_and_explicit_export(self):
        self.assertEqual(request_language({}), 'ar')
        self.assertEqual(request_language({'Accept-Language': 'fr, en-US;q=.8, ar;q=.4'}), 'en')
        self.assertEqual(request_language({'Accept-Language': 'en;q=0, ar;q=.9'}), 'ar')
        self.assertEqual(request_language({'Accept-Language': 'en;q=invalid, de'}), 'ar')
        self.assertEqual(request_language({'Accept-Language': 'ar'}, '/api/reports/sales?format=csv&lang=en'), 'en')

    def test_dynamic_errors_preserve_customer_entered_arabic(self):
        product = 'المبيعات «اختبار» + @عربي'
        self.assertEqual(translate_error(f'رصيد غير كافٍ للصنف «{product}». المتاح: 2.5', 'en'),
                         f'Insufficient stock for “{product}”. Available: 2.5')
        employee = 'محمد أحمد'
        self.assertEqual(translate_error(f'خصومات الموظف {employee} تتجاوز مستحقاته', 'en'),
                         f'Deductions for {employee} exceed the employee earnings.')
        self.assertEqual(translate_error('حقل اسم الصنف مطلوب', 'en'), 'Item name is required.')

    def test_csv_fixed_labels_are_contextual_and_never_translate_custom_notes(self):
        row = {'date': '2026-01-01', 'direction': 'قبض', 'method': 'نقدي', 'account': 'المبيعات',
               'amount': 12.5, 'note': 'إجازة'}
        original = dict(row)
        self.assertEqual(csv_row_values('cashflow', row, 'en'),
                         ['2026-01-01', 'Receipt', 'Cash', 'المبيعات', 12.5, 'إجازة'])
        self.assertEqual(row, original)
        self.assertEqual(csv_row_values('statement', {'description': 'الرصيد الافتتاحي'}, 'en', 0), ['Opening balance'])
        self.assertEqual(csv_row_values('statement', {'description': 'الرصيد الافتتاحي'}, 'en', 1), ['الرصيد الافتتاحي'])
        self.assertEqual(csv_row_values('moves', {'reason': 'sale'}, 'en'), ['Sales invoice'])
        self.assertEqual(csv_row_values('moves', {'reason': 'sale'}, 'ar'), ['فاتورة مبيعات'])
        self.assertEqual(csv_row_values('moves', {'reason': 'فاتورة مبيعات'}, 'en'), ['Sales invoice'])
        self.assertEqual(csv_row_values('moves', {'reason': 'سبب مخصص'}, 'en'), ['سبب مخصص'])


class BilingualHTTPCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.old_data = erp.DATA, erp.DB_PATH
        erp.DATA = Path(cls.directory.name)
        erp.DB_PATH = erp.DATA / 'languages.sqlite3'
        cls.environment = patch.dict(os.environ, {
            'ERP_DATABASE_URL': '', 'ERP_DATABASE_TOKEN': '', 'VERCEL': '',
            'ERP_COOKIE_SECURE': '0', 'ERP_DB_DRIVER': os.environ.get('ERP_DB_DRIVER', 'sqlite'),
            'ERP_SETUP_TOKEN': secrets.token_urlsafe(32),
        })
        cls.environment.start()
        erp.initialize()
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_address[1]}'
        cls.client = build_opener(HTTPCookieProcessor())
        cls.password = secrets.token_urlsafe(20)
        response = cls.fetch('/api/setup', 'POST', {
            'name': 'المدير', 'company_name': 'الحسابات', 'username': 'admin',
            'password': cls.password, 'setup_token': os.environ['ERP_SETUP_TOKEN'],
        }, language='en')
        assert response[0] == 200, response
        db = erp.connect()
        try:
            unit = db.execute('SELECT id FROM units LIMIT 1').fetchone()[0]
            with erp.transaction(db):
                erp.save_resource(db, 'products', dict(name='المبيعات', sku='=SUM(1,2)', unit_id=unit,
                                                      cost=3, price=5, min_stock=0), 1)
                erp.save_resource(db, 'customers', dict(name='إجازة', classification='عادي'), 1)
                # A renamed built-in account is user data and must survive export.
                db.execute('UPDATE accounts SET name=? WHERE code=?', ('حسابي بالعربي', '1100'))
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()
        cls.environment.stop()
        erp.DATA, erp.DB_PATH = cls.old_data
        cls.directory.cleanup()

    @classmethod
    def fetch(cls, path, method='GET', data=None, language=None, authenticated=True, headers=None):
        request_headers = {'Content-Type': 'application/json', 'X-ERP-Request': '1'}
        if language is not None:
            request_headers['Accept-Language'] = language
        request_headers.update(headers or {})
        request = Request(cls.base + path, method=method,
                          data=json.dumps(data).encode() if data is not None else None,
                          headers=request_headers)
        try:
            response = (cls.client if authenticated else build_opener()).open(request)
        except HTTPError as error:
            response = error
        body = response.read()
        return response.status, (json.loads(body) if response.headers.get('Content-Type', '').startswith('application/json') else body), response.headers

    def test_default_arabic_and_english_error_contract(self):
        status, arabic, headers = self.fetch('/api/bootstrap', authenticated=False)
        self.assertEqual((status, arabic), (401, {'error': 'يرجى تسجيل الدخول'}))
        self.assertEqual(headers['Content-Language'], 'ar')
        status, english, headers = self.fetch('/api/bootstrap', language='en', authenticated=False)
        self.assertEqual((status, english), (401, {'error': 'Please sign in.'}))
        self.assertEqual(headers['Content-Language'], 'en')
        self.assertEqual(headers['Vary'], 'Accept-Language')

    def test_business_validation_errors_are_translated_without_api_key_changes(self):
        status, body, _ = self.fetch('/api/resources/products', 'POST', {}, language='en')
        self.assertEqual(status, 400)
        self.assertEqual(body, {'error': 'Item name is required.'})
        status, body, _ = self.fetch('/api/resources/products', 'POST', {})
        self.assertEqual(status, 400)
        self.assertEqual(body, {'error': 'حقل اسم الصنف مطلوب'})

    def test_success_json_preserves_arabic_records_and_enum_values(self):
        _, arabic, _ = self.fetch('/api/resources/customers')
        status, english, _ = self.fetch('/api/resources/customers', language='en')
        self.assertEqual(status, 200)
        self.assertEqual(english, arabic)
        self.assertEqual(english[0]['name'], 'إجازة')
        self.assertEqual(english[0]['classification'], 'عادي')
        _, bootstrap, _ = self.fetch('/api/bootstrap', language='en')
        self.assertEqual(bootstrap['settings']['company_name'], 'الحسابات')
        self.assertEqual(bootstrap['resources']['products']['fields'][0]['key'], 'name')
        accounts = {account['code']: account for account in bootstrap['refs']['accounts']}
        self.assertEqual(accounts['1000']['name'], 'الأصول')
        self.assertEqual(accounts['1100']['name'], 'حسابي بالعربي')
        self.assertEqual(set(accounts['1000']), {'id', 'name', 'code'})
        self.assertEqual(set(bootstrap['refs']['customers'][0]), {'id', 'name'})

    def test_concurrent_requests_do_not_leak_language(self):
        languages = ['en', 'ar'] * 8
        def fetch_language(language):
            return self.fetch('/api/bootstrap', language=language, authenticated=False)[1]['error']
        with ThreadPoolExecutor(max_workers=8) as pool:
            messages = list(pool.map(fetch_language, languages))
        self.assertEqual(messages, ['Please sign in.' if language == 'en' else 'يرجى تسجيل الدخول' for language in languages])

    def test_bilingual_csv_headers_preserve_arabic_products_and_formula_protection(self):
        status, content, headers = self.fetch('/api/reports/stock?format=csv&lang=en', language='ar')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Language'], 'en')
        rows = list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
        self.assertEqual(rows[0]['Name'], 'المبيعات')
        self.assertEqual(rows[0]['SKU'], "'=SUM(1,2)")
        self.assertIn('Quantity', rows[0])
        status, content, _ = self.fetch('/api/reports/stock?format=csv')
        rows = list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
        self.assertEqual(rows[0]['الاسم'], 'المبيعات')
        self.assertIn('الكمية', rows[0])

    def test_csv_chart_translates_only_recognized_builtin_account_names(self):
        _, content, _ = self.fetch('/api/reports/trial_balance?format=csv&lang=en')
        rows = {row['Code']: row for row in csv.DictReader(io.StringIO(content.decode('utf-8-sig')))}
        self.assertEqual(rows['1000']['Name'], 'Assets')
        self.assertEqual(rows['1000']['Type'], 'Assets')
        self.assertEqual(rows['1100']['Name'], 'حسابي بالعربي')

    def test_vercel_startup_errors_translate_and_keep_error_codes(self):
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), index.handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        with patch.object(index, 'ensure_ready', side_effect=DatabaseUnavailable('DATABASE_TOKEN_MISSING')):
            thread.start()
            try:
                request = Request(f'http://127.0.0.1:{httpd.server_address[1]}/api/auth', headers={'Accept-Language': 'en'})
                with self.assertRaises(HTTPError) as caught:
                    build_opener().open(request)
                body = json.loads(caught.exception.read())
                self.assertEqual(caught.exception.code, 503)
                self.assertEqual(body['code'], 'DATABASE_TOKEN_MISSING')
                self.assertTrue(body['error'].startswith('ERP_DATABASE_TOKEN is missing'))
                self.assertTrue(body['error'].endswith('[DATABASE_TOKEN_MISSING]'))
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join()


if __name__ == '__main__':
    unittest.main(verbosity=2)
