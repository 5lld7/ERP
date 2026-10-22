"""Cleaning/pest-control workflows and permission boundaries over real HTTP.

Every test uses an isolated database and signs in through the login endpoint;
no authorization method or session lookup is patched.
"""
import base64
import datetime as dt
import json
import os
import secrets
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import unquote
from urllib.request import HTTPCookieProcessor, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import erp
import server


class IndustryHTTPCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = secrets.token_urlsafe(24)
        cls.password_hash = erp.password_hash(cls.password)
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
        self.old_paths = erp.DATA, erp.DB_PATH
        erp.DATA = Path(self.directory.name)
        erp.DB_PATH = erp.DATA / 'industry.sqlite3'
        self.environment = patch.dict(os.environ, {
            'ERP_DATABASE_URL': '', 'ERP_DATABASE_TOKEN': '', 'VERCEL': '',
            'ERP_SETUP_TOKEN': '', 'ERP_COOKIE_SECURE': '0',
            'ERP_DB_DRIVER': os.environ.get('ERP_DB_DRIVER', 'sqlite'),
        })
        self.environment.start()
        erp.initialize()
        self.db = erp.connect()
        self.clients = {}
        self.users = {}
        with erp.transaction(self.db):
            for role in ('admin', 'sales', 'technician', 'inventory', 'hr', 'viewer'):
                uid = self.db.execute('INSERT INTO users(name,username,password,role) VALUES(?,?,?,?)',
                                      (role, role, self.password_hash, role)).lastrowid
                self.users[role] = {'id': uid, 'name': role, 'role': role}
            self.unit = self.db.execute('SELECT id FROM units ORDER BY id LIMIT 1').fetchone()[0]
            self.branch = self.db.execute('SELECT id FROM branches ORDER BY id LIMIT 1').fetchone()[0]
            self.warehouse = self.db.execute('SELECT id FROM warehouses ORDER BY id LIMIT 1').fetchone()[0]
            self.customer = erp.save_resource(self.db, 'customers', {
                'name': 'مؤسسة العميل', 'classification': 'مؤسسة', 'phone': '01012345678',
                'address': 'عنوان العميل',
            }, self.users['admin']['id'])
            self.product = erp.save_resource(self.db, 'products', {
                'name': 'عبوة مبيد', 'sku': 'HTTP-PRODUCT', 'unit_id': self.unit,
                'cost': 30, 'price': 75, 'min_stock': 0,
            }, self.users['admin']['id'])
            self.service = erp.save_resource(self.db, 'services', {
                'name': 'مكافحة حشرات', 'sku': 'HTTP-SERVICE', 'unit_id': self.unit,
                'price': 250, 'service_method': 'طريقة خدمة محفوظة لا يغيرها الفني',
            }, self.users['admin']['id'])

    def tearDown(self):
        self.db.close()
        self.environment.stop()
        erp.DATA, erp.DB_PATH = self.old_paths
        self.directory.cleanup()

    def request(self, path, method='GET', data=None, role='admin', language='en'):
        if role is not None and role not in self.clients:
            client = build_opener(HTTPCookieProcessor())
            login = Request(self.base + '/api/login', method='POST',
                            data=json.dumps({'username': role, 'password': self.password}).encode(),
                            headers={'Content-Type': 'application/json', 'X-ERP-Request': '1'})
            response = client.open(login)
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read())['ok'])
            self.clients[role] = client
        headers = {'Content-Type': 'application/json', 'X-ERP-Request': '1',
                   'Accept-Language': language}
        request = Request(self.base + path, method=method, headers=headers,
                          data=json.dumps(data if data is not None else {}).encode()
                          if method in ('POST', 'PUT') else None)
        try:
            response = (self.clients[role] if role is not None else build_opener()).open(request)
        except HTTPError as error:
            response = error
        body = response.read()
        if response.headers.get('Content-Type', '').startswith('application/json'):
            body = json.loads(body)
        return response.status, body, response.headers

    def quote(self, **changes):
        data = dict(kind='inspection', date=erp.today(), warehouse_id=self.warehouse,
                    customer_id=self.customer, post=False, tax_rate=14, discount=0,
                    lines=[{'product_id': self.service, 'quantity': 2, 'price': 250}])
        data.update(changes)
        return data

    def appointment(self, **changes):
        data = dict(customer_name='عميل موعد جديد', date=erp.today(), time='14:30',
                    address='عنوان المعاينة التفصيلي', phone='01012345678',
                    service_status='معاينة', service_id=self.service, site_type='فيلا')
        data.update(changes)
        return data

    def test_technician_bootstrap_and_direct_routes_do_not_expose_finance_or_hr(self):
        with erp.transaction(self.db):
            sale = erp.save_document(self.db, self.quote(kind='sale'), self.users['admin'])
            inspection = erp.save_document(self.db, self.quote(), self.users['admin'])
        status, boot, _ = self.request('/api/bootstrap', role='technician')
        self.assertEqual(status, 200)
        self.assertEqual(set(boot['kinds']), {'inspection'})
        self.assertEqual(set(boot['reports']), {'inspections'})
        self.assertIn('appointments', boot['resources'])
        self.assertIn('technician', boot['roles'])
        self.assertTrue({'employees', 'accounts', 'assets', 'loans'}.isdisjoint(boot['resources']))
        for path in (f'/api/documents/{sale}', '/api/resources/employees',
                     '/api/reports/trial_balance', '/api/reports/sales', '/api/payroll'):
            with self.subTest(path=path):
                self.assertEqual(self.request(path, role='technician')[0], 403)
        self.assertEqual(self.request(f'/api/documents/{inspection}', role='technician')[0], 200)
        self.assertEqual(self.request('/api/documents', 'POST', self.quote(kind='sale'), role='technician')[0], 403)
        status, documents, _ = self.request('/api/documents', role='technician')
        self.assertEqual(status, 200)
        self.assertEqual({row['kind'] for row in documents}, {'inspection'})
        status, dashboard, _ = self.request('/api/dashboard', role='technician')
        self.assertEqual(status, 200)
        self.assertTrue({'sales', 'cash', 'receivables', 'payables', 'employees', 'chart'}.isdisjoint(dashboard))
        self.assertTrue(all(row['kind'] == 'inspection' for row in dashboard['recent_documents']))

    def test_raw_quote_price_discount_and_tax_tampering_cannot_bypass_the_manager(self):
        for role in ('technician', 'sales'):
            for overrides in (
                {'lines': [{'product_id': self.service, 'quantity': 2, 'price': 1}]},
                {'discount': 1}, {'tax_rate': 0},
            ):
                before = self.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
                with self.subTest(role=role, overrides=overrides):
                    status, body, _ = self.request('/api/documents', 'POST', self.quote(**overrides), role=role)
                    self.assertEqual(status, 403, body)
                    self.assertEqual(self.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0], before)
            status, result, _ = self.request('/api/documents', 'POST', self.quote(), role=role)
            self.assertEqual(status, 200, result)
            _, stored, _ = self.request(f"/api/documents/{result['id']}", role=role)
            self.assertEqual(stored['lines'][0]['price'], 250)
            self.assertEqual(stored['discount'], 0)
        status, result, _ = self.request('/api/documents', 'POST', self.quote(
            lines=[{'product_id': self.service, 'quantity': 2, 'price': 200}], discount=15))
        self.assertEqual(status, 200, result)
        _, approved, _ = self.request(f"/api/documents/{result['id']}")
        self.assertEqual((approved['lines'][0]['price'], approved['discount']), (200, 15))

    def test_technician_cannot_reprice_the_catalog_or_create_an_offer_to_bypass_quote_rules(self):
        offer = dict(name='Unauthorized discount', product_id=self.service, price=1,
                     start_date=erp.today(), end_date=erp.today())
        for role in ('technician', 'sales'):
            with self.subTest(role=role):
                status, body, _ = self.request('/api/resources/price_lists', 'POST', offer, role=role)
                self.assertEqual(status, 403, body)
        changed = dict(name='مكافحة حشرات', sku='HTTP-SERVICE', unit_id=self.unit,
                       price=1, service_method='محاولة تغيير طريقة الخدمة')
        self.assertEqual(self.request(f'/api/resources/services/{self.service}', 'PUT', changed,
                                      role='technician')[0], 403)
        self.assertEqual(self.db.execute('SELECT price FROM products WHERE id=?', (self.service,)).fetchone()[0], 25000)

    def test_service_method_is_server_owned_and_hidden_from_inspection_ui_responses(self):
        status, catalog, _ = self.request('/api/catalog', role='technician')
        self.assertEqual(status, 200)
        service = next(item for item in catalog['services'] if item['id'] == self.service)
        self.assertNotIn('service_method', service)
        self.assertNotIn('cost', service)
        tampered = self.quote(lines=[{'product_id': self.service, 'quantity': 2, 'price': 250,
                                     'service_method': 'CLIENT-METHOD-MUST-NOT-BE-SAVED'}])
        status, result, _ = self.request('/api/documents', 'POST', tampered, role='technician')
        self.assertEqual(status, 200, result)
        stored_method = self.db.execute('SELECT service_method FROM document_lines WHERE document_id=?',
                                        (result['id'],)).fetchone()[0]
        self.assertEqual(stored_method, 'طريقة خدمة محفوظة لا يغيرها الفني')
        for role in ('technician', 'admin'):
            _, detail, _ = self.request(f"/api/documents/{result['id']}", role=role)
            self.assertNotIn('service_method', detail['lines'][0])
        self.db.execute('UPDATE products SET service_method=? WHERE id=?', ('New catalogue method', self.service))
        self.db.commit()
        self.assertEqual(self.db.execute('SELECT service_method FROM document_lines WHERE document_id=?',
                                         (result['id'],)).fetchone()[0], stored_method)

    def test_services_aliases_do_not_update_or_delete_inventory_products(self):
        status, products, _ = self.request('/api/resources/products')
        self.assertEqual(status, 200)
        self.assertIn(self.product, [row['id'] for row in products])
        self.assertNotIn(self.service, [row['id'] for row in products])
        status, services, _ = self.request('/api/resources/services')
        self.assertEqual(status, 200)
        self.assertEqual([row['id'] for row in services], [self.service])
        changed = dict(name='Must not rename a product', sku='HTTP-PRODUCT', unit_id=self.unit,
                       price=1, service_method='No')
        self.assertIn(self.request(f'/api/resources/services/{self.product}', 'PUT', changed)[0], (400, 404))
        self.assertIn(self.request(f'/api/resources/services/{self.product}', 'DELETE')[0], (400, 404))
        row = self.db.execute('SELECT name,item_type FROM products WHERE id=?', (self.product,)).fetchone()
        self.assertEqual((row['name'], row['item_type']), ('عبوة مبيد', 'product'))
        self.assertEqual(self.request(f'/api/resources/services/{self.service}', 'DELETE')[0], 200)
        self.assertIsNone(self.db.execute('SELECT 1 FROM products WHERE id=?', (self.service,)).fetchone())

    def test_appointment_booking_preserves_requested_fields_and_validates_the_dropdowns(self):
        booking = self.appointment(service_status='إعادة العمل', site_type='مبنى تجاري')
        status, result, _ = self.request('/api/resources/appointments', 'POST', booking, role='technician')
        self.assertEqual(status, 200, result)
        status, bookings, _ = self.request('/api/resources/appointments', role='technician')
        self.assertEqual(status, 200)
        stored = next(row for row in bookings if row['id'] == result['id'])
        for key, value in booking.items():
            self.assertEqual(stored[key], value)
        for changes in ({'service_status': 'موعد مجهول'}, {'site_type': 'خيمة'}, {'time': '25:99'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.request('/api/resources/appointments', 'POST', self.appointment(**changes),
                                              role='technician')[0], 400)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM appointments').fetchone()[0], 1)

    def test_employee_identity_expiries_and_each_uploaded_file_remain_independently_downloadable(self):
        future = (dt.date.today() + dt.timedelta(days=30)).isoformat()
        data = dict(name='موظف خدمات', code='HTTP-EMP', national_id='RES-101', nationality='مصري',
                    residency_expiry=future, passport_expiry=future, driving_license_expiry=future,
                    branch_id=self.branch, hire_date=erp.today(), salary=5000, status='نشط')
        status, result, _ = self.request('/api/resources/employees', 'POST', data, role='hr')
        self.assertEqual(status, 200, result)
        employee = result['id']
        _, employees, _ = self.request('/api/resources/employees', role='hr')
        row = next(item for item in employees if item['id'] == employee)
        for key in ('national_id', 'nationality', 'residency_expiry', 'passport_expiry', 'driving_license_expiry'):
            self.assertEqual(row[key], data[key])
        files = [('إقامة.pdf', b'%PDF-1.4\nresidency fixture\n%%EOF'),
                 ('صورة.png', b'\x89PNG\r\n\x1a\nimage fixture'),
                 ('جواز.pdf', b'%PDF-1.4\npassport fixture\n%%EOF')]
        ids = []
        for filename, content in files:
            status, uploaded, _ = self.request(f'/api/employees/{employee}/files', 'POST',
                {'name': filename, 'content': base64.b64encode(content).decode()}, role='hr')
            self.assertEqual(status, 200, uploaded)
            ids.append(uploaded['id'])
        _, listed, _ = self.request(f'/api/employees/{employee}/files', role='hr')
        self.assertEqual({item['id'] for item in listed}, set(ids))
        for file_id, (filename, content) in zip(ids, files):
            status, actual, headers = self.request(f'/api/files/{file_id}', role='hr')
            self.assertEqual((status, actual), (200, content))
            self.assertIn(filename, unquote(headers['Content-Disposition']))
            self.assertEqual(self.request(f'/api/files/{file_id}', role='technician')[0], 403)
        self.assertEqual(self.request(f'/api/employees/{employee}/files', role='sales')[0], 403)

    def test_notifications_have_persistent_user_scoped_unread_counts(self):
        tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        status, result, _ = self.request('/api/resources/appointments', 'POST', self.appointment(date=tomorrow))
        self.assertEqual(status, 200, result)
        status, admin_feed, _ = self.request('/api/notifications')
        self.assertEqual(status, 200, admin_feed)
        status, technician_feed, _ = self.request('/api/notifications', role='technician')
        self.assertEqual(status, 200, technician_feed)
        self.assertGreater(technician_feed['unread_count'], 0)
        self.assertGreater(admin_feed['unread_count'], 0)
        own_ids = {item['id'] for item in technician_feed['items'] if not item.get('read_at')}
        other_ids = {item['id'] for item in admin_feed['items'] if not item.get('read_at')}
        self.assertTrue(own_ids.isdisjoint(other_ids))
        # Supplying another account's IDs must never clear this user's alerts.
        self.request('/api/notifications/read', 'POST', {'ids': list(other_ids)}, role='technician')
        _, unchanged, _ = self.request('/api/notifications', role='technician')
        self.assertEqual(unchanged['unread_count'], technician_feed['unread_count'])
        status, _, _ = self.request('/api/notifications/read', 'POST', {}, role='technician')
        self.assertEqual(status, 200)
        _, read_again, _ = self.request('/api/notifications', role='technician')
        self.assertEqual(read_again['unread_count'], 0)
        _, independent, _ = self.request('/api/notifications')
        self.assertEqual(independent['unread_count'], admin_feed['unread_count'])
        self.assertEqual(self.request('/api/notifications', role=None)[0], 401)


if __name__ == '__main__':
    unittest.main(verbosity=2)
