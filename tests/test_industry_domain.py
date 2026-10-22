"""Industry-specific migrations, non-stock services and protected quotation prices."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import erp
from database import read_schema_version


class IndustryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'industry.sqlite3'
        self.environment = patch.dict(os.environ, {'ERP_DATABASE_URL':'', 'ERP_DATABASE_TOKEN':'', 'VERCEL':''})
        self.environment.start()
        erp.initialize(self.path)
        self.db = erp.connect(self.path)
        self.db.execute("INSERT INTO users(id,name,username,password,role) VALUES(1,'Manager','manager','unused','admin')")
        self.db.execute("INSERT INTO users(id,name,username,password,role) VALUES(2,'Technician','technician','unused','technician')")
        self.db.commit()
        self.admin = {'id':1, 'role':'admin'}
        self.technician = {'id':2, 'role':'technician'}
        self.warehouse = self.db.execute('SELECT id FROM warehouses LIMIT 1').fetchone()[0]
        self.unit = self.db.execute("SELECT id FROM units WHERE code='service'").fetchone()[0]
        with erp.transaction(self.db):
            self.customer = erp.save_resource(self.db,'customers',{'name':'عميل تنظيف','classification':'مؤسسة'},1)
            self.service = erp.save_resource(self.db,'services',dict(name='تنظيف شامل',sku='SVC-TEST',unit_id=self.unit,price=125,service_method='تنظيف الأسطح ثم التعقيم.'),1)

    def tearDown(self):
        self.db.close()
        self.environment.stop()
        self.tmp.cleanup()

    def document(self, kind='inspection', user=None, **changes):
        data = dict(kind=kind, date=erp.today(), warehouse_id=self.warehouse,
                    customer_id=self.customer, tax_rate=14,
                    lines=[dict(product_id=self.service,quantity=2,price=125)])
        data.update(changes)
        with erp.transaction(self.db):
            return erp.save_document(self.db,data,user or self.admin)

    def test_services_are_separate_from_stock_and_financially_post_as_income(self):
        self.assertNotIn(self.service,[row['id'] for row in erp.list_resource(self.db,'products')])
        self.assertEqual(erp.list_resource(self.db,'services')[0]['price'],125)
        sale = self.document('sale')
        self.assertFalse(self.db.execute('SELECT 1 FROM stock WHERE product_id=?',(self.service,)).fetchone())
        self.assertFalse(self.db.execute('SELECT 1 FROM stock_moves WHERE product_id=?',(self.service,)).fetchone())
        self.assertEqual(self.db.execute('SELECT cost FROM document_lines WHERE document_id=?',(sale,)).fetchone()[0],0)
        self.assertEqual(erp.party_balance(self.db,'customer',self.customer),28500)
        self.assertEqual(self.db.execute('SELECT SUM(debit-credit) FROM journal_lines').fetchone()[0],0)
        self.assertEqual(erp.report(self.db,'stock',{}),[])
        returned = self.document('sale_return',source_id=sale)
        self.assertEqual(erp.party_balance(self.db,'customer',self.customer),0)
        self.assertFalse(self.db.execute('SELECT 1 FROM stock_moves').fetchone())
        self.assertEqual(erp.document_detail(self.db,returned)['lines'][0]['item_type'],'service')

    def test_service_cannot_be_received_transferred_or_counted(self):
        for kind in ('receipt','purchase_order','adjustment','issue'):
            with self.subTest(kind=kind), self.assertRaises(erp.BusinessError):
                self.document(kind)
        with self.assertRaises(erp.BusinessError):
            erp.move_stock(self.db,self.warehouse,self.service,1,0,erp.today(),'test')
        self.assertFalse(self.db.execute('SELECT 1 FROM documents').fetchone())

    def test_service_alias_cannot_edit_product_records_or_forge_item_type(self):
        with erp.transaction(self.db):
            product = erp.save_resource(self.db,'products',dict(name='منظف',sku='STOCK-TEST',unit_id=self.unit,cost=10,price=20,item_type='service',service_method='forged'),1)
        row = self.db.execute('SELECT item_type,service_method FROM products WHERE id=?',(product,)).fetchone()
        self.assertEqual((row['item_type'],row['service_method']),('product',''))
        with self.assertRaises(erp.BusinessError):
            erp.save_resource(self.db,'services',dict(name='Changed',sku='STOCK-TEST',unit_id=self.unit,price=99),1,product)
        self.assertEqual(self.db.execute('SELECT name FROM products WHERE id=?',(product,)).fetchone()[0],'منظف')

    def test_technician_only_uses_stored_price_and_no_discount_or_tax_override(self):
        accepted = self.document(user=self.technician)
        self.assertEqual(erp.document_detail(self.db,accepted)['total'],285)
        for changes in (
            {'lines':[dict(product_id=self.service,quantity=2,price=1)]},
            {'discount':1}, {'tax_rate':0},
        ):
            with self.subTest(changes=changes), self.assertRaises(PermissionError):
                self.document(user=self.technician,**changes)
        with self.assertRaises(PermissionError):
            self.document('sale',user=self.technician)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],1)
        manager_quote = self.document(discount=5,lines=[dict(product_id=self.service,quantity=2,price=100)])
        self.assertEqual(erp.document_detail(self.db,manager_quote)['subtotal'],200)

    def test_approved_catalog_offer_is_used_for_locked_quotes(self):
        with erp.transaction(self.db):
            erp.save_resource(self.db,'price_lists',dict(name='عرض',product_id=self.service,customer_id=self.customer,price=110,start_date=erp.today(),end_date=erp.today()),1)
        with self.assertRaises(PermissionError):
            self.document(user=self.technician)
        did = self.document(user=self.technician,lines=[dict(product_id=self.service,quantity=2,price=110)])
        self.assertEqual(erp.document_detail(self.db,did)['subtotal'],220)

    def test_method_snapshot_ignores_payload_and_survives_service_edits_and_conversion(self):
        quote = self.document(lines=[dict(product_id=self.service,quantity=1,price=125,service_method='FORGED')])
        with erp.transaction(self.db):
            erp.save_resource(self.db,'services',dict(name='تنظيف شامل',sku='SVC-TEST',unit_id=self.unit,price=150,service_method='طريقة جديدة.'),1,self.service)
        detail = erp.document_detail(self.db,quote)
        self.assertEqual(detail['lines'][0]['service_method'],'تنظيف الأسطح ثم التعقيم.')
        sale = self.document('sale',source_id=quote,lines=[dict(product_id=self.service,quantity=1,price=125)])
        self.assertEqual(erp.document_detail(self.db,sale)['lines'][0]['service_method'],'تنظيف الأسطح ثم التعقيم.')
        self.assertEqual(detail['lines'][0]['unit_en'],'Service')

    def test_appointments_validate_required_fields_dates_times_and_fixed_options(self):
        appointment = dict(customer_name='عميل جديد',date=erp.today(),time='10:45',address='العنوان',phone='01012345678',service_type='إعادة عمل',site_type='تاون فيلا')
        with erp.transaction(self.db):
            saved = erp.save_resource(self.db,'appointments',appointment,1)
        self.assertEqual(erp.list_resource(self.db,'appointments')[0]['id'],saved)
        for change in ({'date':'2026-02-31'},{'time':'25:20'},{'site_type':'unknown'},{'phone':''},{'service_type':'unknown'}):
            with self.subTest(change=change), self.assertRaises(erp.BusinessError):
                erp.save_resource(self.db,'appointments',appointment|change,1)

    def test_employee_residency_and_licenses_have_independent_expiry_fields(self):
        employee = dict(name='Employee',code='E-TEST',national_id='RES-123',nationality='مصري',branch_id=self.db.execute('SELECT id FROM branches LIMIT 1').fetchone()[0],hire_date=erp.today(),salary=5000,status='نشط',residency_expiry='2027-01-01',passport_expiry='2028-02-03',driving_license_expiry='2029-03-04')
        with erp.transaction(self.db):
            employee_id = erp.save_resource(self.db,'employees',employee,1)
        row = next(item for item in erp.list_resource(self.db,'employees') if item['id']==employee_id)
        self.assertEqual(row['national_id'],'RES-123')
        self.assertEqual((row['residency_expiry'],row['passport_expiry'],row['driving_license_expiry']),('2027-01-01','2028-02-03','2029-03-04'))
        with self.assertRaises(erp.BusinessError):
            erp.save_resource(self.db,'employees',employee|{'passport_expiry':'not-a-date'},1)

    def test_technician_dashboard_hides_financial_aggregates(self):
        self.document('sale')
        quote = self.document(user=self.technician)
        dashboard = erp.dashboard(self.db,self.technician)
        for key in ('sales','chart','cash','receivables','payables','stock_value','employees'):
            self.assertNotIn(key,dashboard)
        self.assertEqual([row['id'] for row in dashboard['recent_documents']],[quote])

    def test_dashboard_low_stock_includes_empty_products_and_uses_all_warehouses(self):
        with erp.transaction(self.db):
            branch = self.db.execute('SELECT branch_id FROM warehouses WHERE id=?',(self.warehouse,)).fetchone()[0]
            warehouse = erp.save_resource(self.db,'warehouses',dict(name='Second warehouse',branch_id=branch),1)
            product_ids = []
            for name, minimum in (('Never stocked',1),('Above minimum',5),('At minimum',3)):
                product_ids.append(erp.save_resource(self.db,'products',dict(name=name,sku=name,unit_id=self.unit,cost=10,price=20,min_stock=minimum),1))
            empty, enough, low = product_ids
            for product, first, second in ((enough,2,4),(low,1,2)):
                self.db.execute('INSERT INTO stock(warehouse_id,product_id,quantity,avg_cost) VALUES(?,?,?,?)',(self.warehouse,product,first,1000))
                self.db.execute('INSERT INTO stock(warehouse_id,product_id,quantity,avg_cost) VALUES(?,?,?,?)',(warehouse,product,second,1000))
        rows = erp.dashboard(self.db,self.admin)['low_stock']
        self.assertEqual({row['id']:row['quantity'] for row in rows},{empty:0,low:3})
        self.assertNotIn(self.service,[row['id'] for row in rows])


class IndustryMigrationCase(unittest.TestCase):
    def test_existing_v4_company_rows_ids_and_file_blobs_survive_idempotent_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'old.sqlite3'
            db = sqlite3.connect(path)
            for name,spec in erp.RESOURCES.items():
                if name in ('services','appointments'):
                    continue
                columns = ['id INTEGER PRIMARY KEY']
                for field in spec['fields']:
                    if (name=='units' and field['key']=='name_en') or (name=='employees' and field['key'] in ('nationality','residency_expiry','passport_expiry','driving_license_expiry')):
                        continue
                    definition = f"{field['key']} {erp.SQL_TYPES[field['type']]}"
                    if field['type']=='ref':
                        definition += f" REFERENCES {field['ref']}(id)"
                    columns.append(definition)
                columns.append('created_at TEXT DEFAULT CURRENT_TIMESTAMP')
                db.execute(f'CREATE TABLE {name} ({",".join(columns)})')
            for statement in erp.SCHEMA.split(';'):
                if statement.strip() and 'notifications' not in statement:
                    db.execute(statement)
            db.execute("INSERT INTO units(id,name) VALUES(42,'قطعة')")
            db.execute("INSERT INTO units(id,name) VALUES(43,'وحدتي الخاصة')")
            db.execute("INSERT INTO products(id,name,sku,unit_id,price) VALUES(75,'Existing item','OLD-SKU',42,12345)")
            db.execute("INSERT INTO customers(id,name,classification) VALUES(90,'Company customer','جملة')")
            db.execute("INSERT INTO employees(id,name,code,national_id) VALUES(17,'Existing employee','EMP-OLD','OLD-RESIDENCY')")
            db.execute("INSERT INTO users(id,name,username,password,role) VALUES(1,'Original manager','original','unused','admin')")
            db.execute("INSERT INTO branches(id,name) VALUES(6,'Original branch')")
            db.execute("INSERT INTO warehouses(id,name,branch_id) VALUES(7,'Original warehouse',6)")
            db.execute("INSERT INTO documents(id,number,kind,date,customer_id,warehouse_id,subtotal,tax,total,created_by) VALUES(21,'OLD-QUOTE','inspection','2026-01-01',90,7,12345,0,12345,1)")
            db.execute("INSERT INTO document_lines(id,document_id,product_id,quantity,price,total,cost) VALUES(22,21,75,1,12345,12345,2468)")
            legacy_file = b'%PDF-original-employee-file'
            db.execute("INSERT INTO employee_files(id,employee_id,name,mime,size,content,uploaded_by) VALUES(30,17,'original.pdf','application/pdf',?,?,1)",(len(legacy_file),legacy_file))
            db.execute("INSERT INTO settings VALUES('company_name','\"Existing company\"')")
            db.execute('PRAGMA user_version=4')
            db.commit()
            db.close()
            with patch.dict(os.environ, {'ERP_DATABASE_URL':'','ERP_DATABASE_TOKEN':'','VERCEL':''}):
                erp.initialize(path)
                db = erp.connect(path)
                try:
                    self.assertEqual(read_schema_version(db),erp.SCHEMA_VERSION)
                    self.assertEqual(db.execute('SELECT unit_id,price FROM products WHERE id=75').fetchone()[0],42)
                    self.assertEqual(db.execute('SELECT price FROM products WHERE id=75').fetchone()[0],12345)
                    self.assertEqual(db.execute('SELECT classification FROM customers WHERE id=90').fetchone()[0],'مؤسسة')
                    self.assertEqual(db.execute('SELECT national_id FROM employees WHERE id=17').fetchone()[0],'OLD-RESIDENCY')
                    self.assertEqual(bytes(db.execute('SELECT content FROM employee_files WHERE id=30').fetchone()[0]),legacy_file)
                    original_quote = erp.document_detail(db,21)
                    self.assertEqual(original_quote['total'],123.45)
                    self.assertEqual(original_quote['lines'][0]['id'],22)
                    self.assertEqual(original_quote['lines'][0]['cost'],24.68)
                    self.assertEqual(original_quote['lines'][0]['service_method'],'')
                    self.assertEqual(db.execute('SELECT name FROM units WHERE id=43').fetchone()[0],'وحدتي الخاصة')
                    self.assertEqual(db.execute('SELECT name_en FROM units WHERE id=42').fetchone()[0],'Piece')
                    self.assertEqual(erp.settings(db)['company_name'],'Existing company')
                    self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchone())
                    count = db.execute('SELECT COUNT(*) FROM units').fetchone()[0]
                finally:
                    db.close()
                erp.initialize(path)
                db = erp.connect(path)
                try:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM units').fetchone()[0],count)
                finally:
                    db.close()
