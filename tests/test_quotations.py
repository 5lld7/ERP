"""Quotation sharing boundaries, snapshots and public bearer-link behavior."""
import hashlib
import json
import os
import secrets
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import erp
import quotations
import server
from database import Connection, read_schema_version


class QuotationCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_address[1]}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous_paths = erp.DATA, erp.DB_PATH
        erp.DATA = Path(self.directory.name)
        erp.DB_PATH = erp.DATA / 'quotations.sqlite3'
        self.environment = patch.dict(os.environ, {
            'ERP_DATABASE_URL': '', 'ERP_DATABASE_TOKEN': '', 'VERCEL': '',
            'ERP_COOKIE_SECURE': '0', 'ERP_DB_DRIVER': os.environ.get('ERP_DB_DRIVER', 'sqlite'),
        })
        self.environment.start()
        erp.initialize()
        self.db = erp.connect()
        self.cookies = {}
        with erp.transaction(self.db):
            for uid, role in enumerate(('admin', 'sales', 'viewer', 'inventory'), 1):
                self.db.execute('INSERT INTO users(id,name,username,password,role) VALUES(?,?,?,?,?)',
                                (uid, role, role, 'unused', role))
                token = secrets.token_urlsafe(32)
                self.cookies[role] = f'erp_session={token}'
                self.db.execute('INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)',
                                (hashlib.sha256(token.encode()).hexdigest(), uid, int(time.time()) + 3600))
            unit = self.db.execute('SELECT id FROM units LIMIT 1').fetchone()[0]
            self.warehouse = self.db.execute('SELECT id FROM warehouses LIMIT 1').fetchone()[0]
            self.product = erp.save_resource(self.db, 'products', {
                'name': 'Door installation', 'sku': 'DOOR-1', 'unit_id': unit,
                'cost': 9988.76, 'price': 150, 'min_stock': 0,
            }, 1)
            self.customer = erp.save_resource(self.db, 'customers', {
                'name': 'Customer Ahmed', 'classification': 'عادي', 'phone': '01012345678',
                'address': 'Customer private address', 'tax_number': 'customer-private-tax',
            }, 1)
        self.user = {'id': 1, 'role': 'admin'}
        self.document = self.make_document()

    def tearDown(self):
        self.db.close()
        self.environment.stop()
        erp.DATA, erp.DB_PATH = self.previous_paths
        self.directory.cleanup()

    def make_document(self, kind='inspection'):
        with erp.transaction(self.db):
            return erp.save_document(self.db, {
                'kind': kind, 'date': '2026-10-19', 'warehouse_id': self.warehouse,
                'customer_id': self.customer, 'post': False,
                'note': 'INTERNAL-NOTE-SHOULD-NOT-BE-IN-PDF', 'location': 'Installation location',
                'lines': [{'product_id': self.product, 'quantity': 2, 'price': 150}],
                'discount': 10, 'tax_rate': 14,
            }, self.user)

    def fetch(self, path, method='GET', data=None, role='admin', language='en', protection=True):
        headers = {'Content-Type': 'application/json', 'Accept-Language': language}
        if protection:
            headers['X-ERP-Request'] = '1'
        if role:
            headers['Cookie'] = self.cookies[role]
        request = Request(self.base + path, method=method, headers=headers,
                          data=json.dumps(data or {}).encode() if method in ('POST', 'PUT') else None)
        try:
            response = build_opener().open(request)
        except HTTPError as error:
            response = error
        content = response.read()
        if response.headers.get('Content-Type', '').startswith('application/json'):
            content = json.loads(content)
        return response.status, content, response.headers

    def share(self, language='en'):
        status, result, _ = self.fetch(f'/api/documents/{self.document}/share?lang={language}', 'POST', role='sales')
        self.assertEqual(status, 200, result)
        return result

    def test_pdf_requires_sales_read_access_and_is_a_real_pdf(self):
        path = f'/api/documents/{self.document}/pdf?lang=en'
        self.assertEqual(self.fetch(path, role=None)[0], 401)
        self.assertEqual(self.fetch(path, role='inventory')[0], 403)
        for role in ('viewer', 'sales', 'admin'):
            status, pdf, headers = self.fetch(path, role=role)
            self.assertEqual(status, 200)
            self.assertEqual(headers['Content-Type'], 'application/pdf')
            self.assertTrue(pdf.startswith(b'%PDF-'))
            self.assertIn('attachment', headers['Content-Disposition'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM document_shares').fetchone()[0], 0)

    def test_share_requires_write_permission_and_request_protection(self):
        path = f'/api/documents/{self.document}/share?lang=en'
        self.assertEqual(self.fetch(path, 'POST', role=None)[0], 401)
        self.assertEqual(self.fetch(path, 'POST', role='viewer')[0], 403)
        self.assertEqual(self.fetch(path, 'POST', role='inventory')[0], 403)
        self.assertEqual(self.fetch(path, 'POST', role='sales', protection=False)[0], 403)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM document_shares').fetchone()[0], 0)

    def test_share_returns_customer_contact_and_public_pdf_without_metadata(self):
        result = self.share()
        self.assertEqual(result['customer_name'], 'Customer Ahmed')
        self.assertEqual(result['whatsapp_phone'], '201012345678')
        self.assertEqual(result['currency'], 'EGP')
        self.assertEqual(result['language'], 'en')
        self.assertAlmostEqual(result['expires_at'], int(time.time()) + quotations.SHARE_TTL, delta=2)
        token = parse_qs(urlsplit(result['url']).query)['token'][0]
        row = self.db.execute('SELECT * FROM document_shares').fetchone()
        self.assertEqual(row['token_hash'], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotEqual(row['token_hash'], token)
        self.assertNotIn(token.encode(), bytes(row['pdf']))
        with patch.object(server.Handler, 'session', side_effect=AssertionError('Public PDF must precede session checks')):
            status, pdf, headers = self.fetch(result['url'], role=None)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'application/pdf')
        self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(pdf, bytes(row['pdf']))
        self.assertTrue(pdf.startswith(b'%PDF-'))
        self.assertEqual(self.fetch('/api/bootstrap', role=None)[0], 401)
        self.assertEqual(self.db.execute('SELECT progress FROM documents WHERE id=?', (self.document,)).fetchone()[0], 'جديدة')

    def test_shared_pdf_is_immutable_after_document_currency_and_customer_changes(self):
        result = self.share('ar')
        original = self.fetch(result['url'], role=None)[1]
        with erp.transaction(self.db):
            self.db.execute('UPDATE customers SET name=?,phone=? WHERE id=?', ('Different Customer', '+447700900123', self.customer))
            self.db.execute('UPDATE documents SET total=987654,discount=12345 WHERE id=?', (self.document,))
            self.db.execute('UPDATE document_lines SET price=777777,total=1555554 WHERE document_id=?', (self.document,))
            self.db.execute('UPDATE settings SET value=? WHERE key=?', ('"USD"', 'currency'))
        self.assertEqual(self.fetch(result['url'] + '&lang=en', role=None)[1], original)
        row = self.db.execute('SELECT language,currency FROM document_shares').fetchone()
        self.assertEqual((row['language'], row['currency']), ('ar', 'EGP'))

    def test_invalid_missing_and_expired_tokens_share_the_same_localized_error(self):
        result = self.share()
        missing = self.fetch('/api/quotations/shared', role=None)
        invalid = self.fetch('/api/quotations/shared?token=bad-token', role=None)
        nonexistent = self.fetch('/api/quotations/shared?token=' + secrets.token_urlsafe(32), role=None)
        with erp.transaction(self.db):
            self.db.execute('UPDATE document_shares SET expires_at=?', (int(time.time()),))
        expired = self.fetch(result['url'], role=None)
        for status, body, _ in (missing, invalid, nonexistent, expired):
            self.assertEqual(status, 404)
            self.assertEqual(body, {'error': 'The quotation link is invalid or has expired.'})
        self.assertEqual(self.fetch(result['url'], role=None, language='ar')[1], {'error': quotations.SHARE_UNAVAILABLE})

    def test_missing_or_invalid_customer_phone_blocks_share_but_not_pdf(self):
        for phone in ('', '123', '01012345678 ext 9', '+000123456789'):
            with erp.transaction(self.db):
                self.db.execute('UPDATE customers SET phone=? WHERE id=?', (phone, self.customer))
            self.assertEqual(self.fetch(f'/api/documents/{self.document}/share', 'POST')[0], 400)
            self.assertEqual(self.fetch(f'/api/documents/{self.document}/pdf?lang=en')[0], 200)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM document_shares').fetchone()[0], 0)

    def test_share_ignores_caller_supplied_phone_and_details(self):
        status, result, _ = self.fetch(f'/api/documents/{self.document}/share?lang=en', 'POST', {
            'customer_phone': '+447700900123', 'customer_name': 'Impostor', 'total': 1,
        })
        self.assertEqual(status, 200)
        self.assertEqual(result['whatsapp_phone'], '201012345678')
        self.assertEqual(result['customer_name'], 'Customer Ahmed')
        self.assertEqual(result['total'], 330.6)

    def test_non_inspection_documents_and_unknown_suffixes_are_rejected(self):
        sale = self.make_document('sale')
        for suffix, method in (('pdf?lang=en', 'GET'), ('share?lang=en', 'POST')):
            self.assertEqual(self.fetch(f'/api/documents/{sale}/{suffix}', method)[0], 400)
        for suffix in ('unexpected', 'pdf/extra'):
            self.assertEqual(self.fetch(f'/api/documents/{self.document}/{suffix}')[0], 404)
            self.assertEqual(self.fetch(f'/api/documents/{self.document}/{suffix}', 'DELETE')[0], 404)
        self.assertIsNotNone(self.db.execute('SELECT id FROM documents WHERE id=?', (self.document,)).fetchone())
        self.assertEqual(self.fetch(f'/api/documents/{self.document}/share')[0], 405)
        self.assertEqual(self.fetch(f'/api/documents/{self.document}/pdf', 'POST')[0], 405)

    def test_query_tokens_do_not_enter_application_access_logs(self):
        result = self.share()
        token = parse_qs(urlsplit(result['url']).query)['token'][0]
        with patch.object(server.LOG, 'info') as logger:
            self.assertEqual(self.fetch(result['url'], role=None)[0], 200)
        self.assertTrue(logger.called)
        self.assertNotIn(token, str(logger.call_args_list))
        self.assertNotIn('?token=', str(logger.call_args_list))

    def test_shares_removed_on_document_deletion(self):
        result = self.share()
        self.assertEqual(self.fetch(f'/api/documents/{self.document}', 'DELETE')[0], 200)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM document_shares').fetchone()[0], 0)
        self.assertEqual(self.fetch(result['url'], role=None)[0], 404)

    def test_native_backup_includes_shared_pdf_and_hash_without_raw_token(self):
        result = self.share()
        token = parse_qs(urlsplit(result['url']).query)['token'][0]
        native = Connection(erp.DB_PATH)
        target_path = erp.DATA / 'backup.sqlite3'
        target = sqlite3.connect(target_path)
        try:
            native.backup(target)
            copied = target.execute('SELECT pdf,token_hash FROM document_shares').fetchone()
            self.assertTrue(copied[0].startswith(b'%PDF-'))
            self.assertEqual(copied[1], hashlib.sha256(token.encode()).hexdigest())
            self.assertEqual(target.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(read_schema_version(target), erp.SCHEMA_VERSION)
        finally:
            target.close()
            native.close()
        self.assertNotIn(token.encode(), target_path.read_bytes())

    def test_migration_preserves_existing_currency_and_adds_snapshot_table(self):
        with erp.transaction(self.db):
            self.db.execute('UPDATE settings SET value=? WHERE key=?', ('"ج.م"', 'currency'))
            self.db.execute("UPDATE erp_metadata SET value=3 WHERE key='schema_version'")
            self.db.execute('DROP TABLE document_shares')
        erp.initialize()
        self.assertEqual(erp.settings(self.db)['currency'], 'ج.م')
        self.assertEqual(read_schema_version(self.db), erp.SCHEMA_VERSION)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM document_shares').fetchone()[0], 0)


class PhoneCase(unittest.TestCase):
    def test_egypt_local_and_international_formats(self):
        numbers = ('01012345678', '+20 10 1234 5678', '00201012345678', '201012345678', '٠١٠١٢٣٤٥٦٧٨')
        for value in numbers:
            self.assertEqual(quotations.whatsapp_phone(value), '201012345678')
        self.assertEqual(quotations.whatsapp_phone('+44 (7700) 900123'), '447700900123')
        self.assertEqual(quotations.whatsapp_phone('00971501234567'), '971501234567')
        for value in ('', '123', '010123', '001234', '+1;alert(1)', '00', '0' * 12):
            with self.assertRaises(erp.BusinessError):
                quotations.whatsapp_phone(value)


if __name__ == '__main__':
    unittest.main()
