import base64
import datetime as dt
import json
import os
import secrets
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from http.server import ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import erp
import server


class ERPCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'test.sqlite3'
        erp.initialize(self.path)
        self.db=erp.connect(self.path)
        self.db.execute("INSERT INTO users(id,name,username,password,role) VALUES(1,'Test','admin','unused','admin')")
        self.db.commit()
        self.user={'id':1,'role':'admin','name':'Test'}
        self.wid=self.db.execute('SELECT id FROM warehouses LIMIT 1').fetchone()[0]
        self.bid=self.db.execute('SELECT id FROM branches LIMIT 1').fetchone()[0]
        self.unit=self.db.execute('SELECT id FROM units LIMIT 1').fetchone()[0]
        with erp.transaction(self.db):
            self.pid=erp.save_resource(self.db,'products',dict(name='صنف اختبار',sku='T-001',unit_id=self.unit,cost=100,price=150,min_stock=2),1)
            self.cid=erp.save_resource(self.db,'customers',dict(name='عميل',classification='عادي',credit_limit=100000),1)
            self.sid=erp.save_resource(self.db,'suppliers',dict(name='مورد'),1)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def doc(self,kind,qty=10,price=None,**extra):
        data=dict(kind=kind,date=erp.today(),warehouse_id=self.wid,lines=[dict(product_id=self.pid,quantity=qty,price=price if price is not None else (150 if kind in ('sale','sale_return','inspection') else 100))],tax_rate=14)
        if kind in ('sale','sale_return','inspection'):
            data['customer_id']=self.cid
        if kind in ('purchase','purchase_return','purchase_order'):
            data['supplier_id']=self.sid
        data.update(extra)
        with erp.transaction(self.db):
            return erp.save_document(self.db,data,self.user)

    def stock(self,wid=None):
        row=self.db.execute('SELECT quantity FROM stock WHERE warehouse_id=? AND product_id=?',(wid or self.wid,self.pid)).fetchone()
        return row[0] if row else 0

    def balanced(self):
        rows=self.db.execute('SELECT j.id,SUM(l.debit) debit,SUM(l.credit) credit FROM journal j JOIN journal_lines l ON l.journal_id=j.id GROUP BY j.id').fetchall()
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r['debit'],r['credit'])

    def employee(self):
        with erp.transaction(self.db):
            return erp.save_resource(self.db,'employees',dict(name='موظف',code='EMP-1',branch_id=self.bid,hire_date='2020-01-01',salary=9000,allowance=1000,overtime_rate=50,leave_balance=21,status='نشط'),1)

    def test_purchase_sale_payment_and_returns(self):
        purchase=self.doc('purchase',qty=10,paid=200)
        sale=self.doc('sale',qty=3,paid=100)
        self.assertEqual(self.stock(),7)
        self.assertEqual(erp.party_balance(self.db,'customer',self.cid),41300)
        self.assertEqual(erp.party_balance(self.db,'supplier',self.sid),94000)
        with erp.transaction(self.db):
            erp.save_payment(self.db,dict(document_id=sale,direction='in',amount=413,method='bank',date=erp.today()),self.user)
        self.assertEqual(erp.party_balance(self.db,'customer',self.cid),0)
        self.doc('sale_return',qty=1,source_id=sale,paid=171)
        self.doc('purchase_return',qty=2,source_id=purchase,paid=228)
        self.assertEqual(self.stock(),6)
        self.assertEqual(erp.party_balance(self.db,'customer',self.cid),0)
        self.balanced()

    def test_failed_sale_is_atomic(self):
        self.doc('purchase',qty=2)
        before=self.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
        with self.assertRaisesRegex(erp.BusinessError,'رصيد غير كاف'):
            self.doc('sale',qty=3,paid=10)
        self.assertEqual(self.stock(),2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],before)
        self.assertEqual(erp.party_balance(self.db,'customer',self.cid),0)

    def test_multiple_lines_rollback_if_later_item_missing(self):
        self.doc('purchase',qty=4)
        with erp.transaction(self.db):
            second=erp.save_resource(self.db,'products',dict(name='ثاني',sku='T-002',unit_id=self.unit,cost=1,price=2),1)
        with self.assertRaises(erp.BusinessError):
            self.doc('sale',lines=[dict(product_id=self.pid,quantity=2,price=150),dict(product_id=second,quantity=1,price=2)])
        self.assertEqual(self.stock(),4)

    def test_draft_post_once(self):
        doc=self.doc('purchase',qty=4,post=False)
        self.assertEqual(self.stock(),0)
        with erp.transaction(self.db):
            erp.post_document(self.db,doc,self.user)
        self.assertEqual(self.stock(),4)
        with self.assertRaises(erp.BusinessError),erp.transaction(self.db):
            erp.post_document(self.db,doc,self.user)
        self.assertEqual(self.stock(),4)

    def test_transfer_and_zero_count(self):
        self.doc('purchase',qty=10)
        with erp.transaction(self.db):
            w2=erp.save_resource(self.db,'warehouses',dict(name='ثانٍ',branch_id=self.bid),1)
        self.doc('transfer',qty=4,target_warehouse_id=w2,tax_rate=0)
        self.assertEqual(self.stock(),6)
        self.assertEqual(self.stock(w2),4)
        self.doc('adjustment',qty=0,tax_rate=0)
        self.assertEqual(self.stock(),0)
        self.balanced()

    def test_returns_cannot_exceed_source_even_from_drafts(self):
        self.doc('purchase',qty=10)
        sale=self.doc('sale',qty=4)
        first=self.doc('sale_return',qty=3,source_id=sale,post=False)
        second=self.doc('sale_return',qty=3,source_id=sale,post=False)
        with erp.transaction(self.db):
            erp.post_document(self.db,first,self.user)
        with self.assertRaisesRegex(erp.BusinessError,'المتبقية'),erp.transaction(self.db):
            erp.post_document(self.db,second,self.user)
        self.assertEqual(self.stock(),9)

    def test_return_proportionally_reverses_discount(self):
        self.doc('purchase',qty=10,discount=100)
        sale=self.doc('sale',qty=4,discount=60)
        ret=self.doc('sale_return',qty=2,source_id=sale)
        detail=erp.document_detail(self.db,ret)
        self.assertEqual(detail['discount'],30)
        self.assertEqual(detail['tax'],37.8)
        self.assertEqual(detail['total'],307.8)
        self.balanced()

    def test_credit_limit_rolls_back(self):
        self.doc('purchase',qty=10)
        self.db.execute('UPDATE customers SET credit_limit=10000 WHERE id=?',(self.cid,))
        self.db.commit()
        with self.assertRaisesRegex(erp.BusinessError,'ائتمان'):
            self.doc('sale',qty=1)
        self.assertEqual(self.stock(),10)

    def test_expired_product_cannot_be_sold(self):
        self.doc('purchase',qty=10)
        self.db.execute("UPDATE products SET expiry_date='2020-01-01' WHERE id=?",(self.pid,))
        self.db.commit()
        with self.assertRaisesRegex(erp.BusinessError,'الصلاحية'):
            self.doc('sale',qty=1)

    def test_order_conversion_once(self):
        order=self.doc('purchase_order',qty=4)
        self.assertEqual(self.stock(),0)
        self.doc('purchase',qty=4,source_id=order)
        with self.assertRaisesRegex(erp.BusinessError,'بالفعل'):
            self.doc('purchase',qty=4,source_id=order)
        self.assertEqual(self.stock(),4)

    def test_unbalanced_journal_rejected(self):
        with self.assertRaisesRegex(erp.BusinessError,'غير متوازن'),erp.transaction(self.db):
            erp.journal(self.db,erp.today(),'غير متوازن',[dict(code='1100',debit=1000),dict(code='3100',credit=999)],1)

    def test_payroll_overtime_absence_loans_and_no_duplicate(self):
        eid=self.employee()
        month=erp.today()[:7]
        with erp.transaction(self.db):
            erp.save_resource(self.db,'attendance',dict(employee_id=eid,date=month+'-01',status='حاضر',overtime_hours=2,deduction=100),1)
            erp.save_resource(self.db,'attendance',dict(employee_id=eid,date=month+'-02',status='غائب'),1)
            erp.save_loan(self.db,dict(employee_id=eid,date=month+'-01',amount=1200,installment=300),self.user)
            erp.run_payroll(self.db,dict(month=month,bonus=200),self.user)
        line=self.db.execute('SELECT * FROM payroll_lines').fetchone()
        self.assertEqual(line['net'],960000) # 9000 + 1000 + 100 + 200 - 100 - 300 - 300
        self.assertEqual(self.db.execute('SELECT balance FROM loans').fetchone()[0],90000)
        with self.assertRaisesRegex(erp.BusinessError,'بالفعل'),erp.transaction(self.db):
            erp.run_payroll(self.db,dict(month=month),self.user)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM payroll').fetchone()[0],1)
        self.balanced()

    def test_leave_overlap_and_balance_validation(self):
        eid=self.employee()
        with erp.transaction(self.db):
            erp.save_resource(self.db,'leaves',dict(employee_id=eid,start_date='2026-11-01',end_date='2026-11-10',type='سنوية',status='معتمدة'),1)
        with self.assertRaisesRegex(erp.BusinessError,'تتداخل'),erp.transaction(self.db):
            erp.save_resource(self.db,'leaves',dict(employee_id=eid,start_date='2026-11-09',end_date='2026-11-12',type='سنوية',status='معتمدة'),1)
        with self.assertRaisesRegex(erp.BusinessError,'غير كاف'),erp.transaction(self.db):
            erp.save_resource(self.db,'leaves',dict(employee_id=eid,start_date='2026-12-01',end_date='2026-12-15',type='سنوية',status='معتمدة'),1)

    def test_depreciation_never_below_salvage_and_no_duplicate(self):
        with erp.transaction(self.db):
            asset=erp.save_resource(self.db,'assets',dict(name='حاسب',code='A-001',purchase_date='2026-01-01',cost=1200,salvage=200,life_months=2,branch_id=self.bid),1)
            erp.depreciate(self.db,dict(month='2026-01'),self.user)
        with self.assertRaises(erp.BusinessError),erp.transaction(self.db):
            erp.depreciate(self.db,dict(month='2026-01'),self.user)
        with erp.transaction(self.db):
            erp.depreciate(self.db,dict(month='2026-02'),self.user)
        self.assertEqual(self.db.execute('SELECT SUM(amount) FROM depreciation WHERE asset_id=?',(asset,)).fetchone()[0],100000)
        with self.assertRaises(erp.BusinessError),erp.transaction(self.db):
            erp.depreciate(self.db,dict(month='2026-03'),self.user)
        self.balanced()

    def test_reports_cover_all_modules_and_balance(self):
        self.doc('purchase',qty=10)
        self.doc('sale',qty=3,paid=100)
        for name in server.REPORT_MODULES:
            rows=erp.report(self.db,name,{})
            self.assertIsInstance(rows,list,name)
        trial=erp.report(self.db,'trial_balance',{})
        self.assertAlmostEqual(sum(r['debit'] for r in trial),sum(r['credit'] for r in trial))
        sheet=erp.report(self.db,'balance_sheet',{})
        assets=sum(r['value'] for r in sheet if r['type']=='أصول')
        other=sum(r['value'] for r in sheet if r['type']!='أصول')
        self.assertAlmostEqual(assets,other)

    def test_password_hash_unique_salt(self):
        password=secrets.token_urlsafe(20)
        hashed=erp.password_hash(password)
        self.assertNotEqual(hashed,erp.password_hash(password))
        self.assertTrue(erp.password_matches(password,hashed))
        self.assertFalse(erp.password_matches('wrong',hashed))

    def test_individual_bonus_and_deduction_are_frozen_in_payroll(self):
        eid=self.employee()
        with erp.transaction(self.db):
            aid=erp.save_resource(self.db,'employee_adjustments',dict(employee_id=eid,date=erp.today(),type='مكافأة',amount=500),1)
            erp.save_resource(self.db,'employee_adjustments',dict(employee_id=eid,date=erp.today(),type='خصم',amount=100),1)
            erp.run_payroll(self.db,dict(month=erp.today()[:7]),self.user)
        self.assertEqual(self.db.execute('SELECT net FROM payroll_lines').fetchone()[0],1040000)
        with self.assertRaises(erp.BusinessError),erp.transaction(self.db):
            erp.save_resource(self.db,'employee_adjustments',dict(employee_id=eid,date=erp.today(),type='مكافأة',amount=900),1,aid)

    def test_consistent_backup_restore_and_retention(self):
        import backups
        self.doc('purchase',qty=10)
        self.doc('sale',qty=2)
        old=erp.DB_PATH
        erp.DB_PATH=self.path
        try:
            directory=Path(self.tmp.name)/'backups'
            directory.mkdir()
            manual=directory/'important-manual.sqlite3'
            manual.write_bytes(b'preserve-me')
            for _ in range(3):
                result=backups.create_backup(directory,retain=2)
            self.assertEqual(len(list(directory.glob('erp-auto-*.sqlite3'))),2)
            self.assertEqual(manual.read_bytes(),b'preserve-me')
            restored=sqlite3.connect(result)
            self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(restored.execute('SELECT quantity FROM stock').fetchone()[0],8)
            self.assertEqual(restored.execute('SELECT COUNT(*) FROM documents').fetchone()[0],2)
            restored.close()
        finally:
            erp.DB_PATH=old

    def test_non_finite_and_negative_amounts(self):
        for value in ('NaN','Infinity','-Infinity','999999999999999'):
            with self.assertRaises(erp.BusinessError):
                erp.money(value)
        with self.assertRaises(erp.BusinessError):
            self.doc('purchase',price=-1)


class HTTPCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment=patch.dict(os.environ,{'ERP_DATABASE_URL':'','ERP_DATABASE_TOKEN':'','ERP_SETUP_TOKEN':'','VERCEL':''})
        cls.environment.start()
        cls.tmp=tempfile.TemporaryDirectory()
        cls.old_db,cls.old_data=erp.DB_PATH,erp.DATA
        erp.DATA=Path(cls.tmp.name)
        erp.DB_PATH=erp.DATA/'http.sqlite3'
        erp.initialize()
        cls.httpd=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.thread=threading.Thread(target=cls.httpd.serve_forever,daemon=True)
        cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.httpd.server_address[1]}'
        cls.client=build_opener(HTTPCookieProcessor())
        cls.password=secrets.token_urlsafe(20)
        cls.request('setup','POST',dict(name='مسؤول',username='admin',company_name='اختبار',password=cls.password))

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()
        erp.DB_PATH,erp.DATA=cls.old_db,cls.old_data
        cls.tmp.cleanup()
        cls.environment.stop()

    @classmethod
    def request(cls,path,method='GET',data=None,client=None,headers=None):
        request=Request(cls.base+'/api/'+path,method=method,data=json.dumps(data).encode() if data is not None else None,headers=headers if headers is not None else {'Content-Type':'application/json','X-ERP-Request':'1'})
        try:
            response=(client or cls.client).open(request)
        except HTTPError as exc:
            response=exc
        raw=response.read()
        return response.status,json.loads(raw) if response.headers.get('Content-Type','').startswith('application/json') else raw,response.headers

    def test_auth_and_csrf(self):
        self.assertEqual(self.request('dashboard',client=build_opener())[0],401)
        self.assertEqual(self.request('settings','PUT',{},headers={'Content-Type':'application/json'})[0],403)
        code,data,headers=self.request('auth')
        self.assertEqual(code,200)
        self.assertEqual(data['user']['role'],'admin')
        self.assertIn('frame-ancestors',headers['Content-Security-Policy'])

    def test_bootstrap_and_demo_workflow(self):
        status,data,_=self.request('bootstrap')
        self.assertEqual(status,200)
        self.assertIn('products',data['resources'])
        status,data,_=self.request('demo','POST',{})
        self.assertEqual(status,200,data)
        status,dashboard,_=self.request('dashboard')
        self.assertGreater(dashboard['sales'],0)
        self.assertEqual(dashboard['employees'],4)
        self.assertEqual(self.request('demo','POST',{})[0],400)
        status,backup,headers=self.request('backup')
        self.assertEqual(status,200)
        self.assertEqual(backup[:16],b'SQLite format 3\x00')

    def test_role_enforced_by_server(self):
        password=secrets.token_urlsafe(20)
        status,data,_=self.request('users','POST',dict(name='مندوب',username='sales',password=password,role='sales'))
        self.assertEqual(status,200,data)
        client=build_opener(HTTPCookieProcessor())
        self.assertEqual(self.request('login','POST',dict(username='sales',password=password),client=client)[0],200)
        self.assertEqual(self.request('resources/employees',client=client)[0],403)
        self.assertEqual(self.request('journal',client=client)[0],403)
        self.assertEqual(self.request('backup',client=client)[0],403)
        self.assertEqual(self.request('resources/products','POST',dict(name='ممنوع'),client=client)[0],403)
        status,data,_=self.request('catalog',client=client)
        self.assertEqual(status,200)
        self.assertTrue(all('cost' not in p for p in data['products']))

    def test_employee_attachment_roundtrip_and_type_restrictions(self):
        status,employees,_=self.request('resources/employees')
        eid=employees[0]['id']
        pdf=b'%PDF-1.7\n% Test fixture\n%%EOF'
        status,data,_=self.request(f'employees/{eid}/files','POST',dict(name='contract.pdf',content=base64.b64encode(pdf).decode()))
        self.assertEqual(status,200,data)
        fid=data['id']
        status,files,_=self.request(f'employees/{eid}/files')
        self.assertTrue(any(f['id']==fid for f in files))
        status,content,headers=self.request(f'files/{fid}')
        self.assertEqual(content,pdf)
        self.assertIn('attachment',headers['Content-Disposition'])
        self.assertEqual(self.request(f'employees/{eid}/files','POST',dict(name='script.html',content=base64.b64encode(b'<script>alert(1)</script>').decode()))[0],400)
        self.assertEqual(self.request(f'files/{fid}','DELETE')[0],200)

    def test_qr_generated_from_product_barcode(self):
        _,catalog,_=self.request('catalog')
        pid=catalog['products'][0]['id']
        status,data,_=self.request(f'products/{pid}/qr')
        self.assertEqual(status,200,data)
        self.assertIn('<svg',data['svg'])
        self.assertIn('<path',data['svg'])

    def test_viewer_cannot_download_backup_or_admin_data(self):
        password=secrets.token_urlsafe(20)
        status,data,_=self.request('users','POST',dict(name='قراءة',username='viewer',password=password,role='viewer'))
        self.assertEqual(status,200,data)
        client=build_opener(HTTPCookieProcessor())
        self.assertEqual(self.request('login','POST',dict(username='viewer',password=password),client=client)[0],200)
        for path in ('backup','users','audit','settings'):
            self.assertEqual(self.request(path,client=client)[0],403,path)
        self.assertEqual(self.request('resources/employees',client=client)[0],200)
        self.assertEqual(self.request('resources/customers','POST',dict(name='ممنوع'),client=client)[0],403)

    def test_inspection_progress_and_conversion(self):
        _,docs,_=self.request('documents?kind=inspection')
        did=docs[0]['id']
        status,data,_=self.request(f'documents/{did}/progress','PUT',dict(progress='تمت المعاينة'))
        self.assertEqual(status,200,data)
        _,doc,_=self.request(f'documents/{did}')
        self.assertEqual(doc['progress'],'تمت المعاينة')

    def test_report_csv_and_formula_escape(self):
        self.request('resources/customers','POST',dict(name='=1+1',classification='عادي'))
        status,body,headers=self.request('reports/customer_balances?format=csv')
        self.assertEqual(status,200)
        self.assertTrue(body.startswith(b'\xef\xbb\xbf'))
        self.assertIn(b"'=1+1",body)


if __name__=='__main__':
    unittest.main(verbosity=2)
