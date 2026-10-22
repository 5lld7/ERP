"""Appointment filters, atomic assignment/conversion, reminders and revenue ledgers."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import appointments
import erp
import notifications
from tests import test_industry_http as fixtures


class AppointmentCase(unittest.TestCase):
    setUpClass = classmethod(fixtures.IndustryHTTPCase.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.IndustryHTTPCase.tearDownClass.__func__)
    setUp = fixtures.IndustryHTTPCase.setUp
    tearDown = fixtures.IndustryHTTPCase.tearDown
    request = fixtures.IndustryHTTPCase.request
    quote = fixtures.IndustryHTTPCase.quote
    appointment = fixtures.IndustryHTTPCase.appointment

    def book(self, **changes):
        status, body, _ = self.request('/api/resources/appointments', 'POST', self.appointment(**changes))
        self.assertEqual(status, 200, body)
        return body['id']

    def action(self, ids, action, **changes):
        return self.request('/api/appointments/actions', 'POST', dict(ids=ids, action=action, **changes))

    def test_filters_combine_cairo_today_activity_category_and_workflow(self):
        today = appointments.business_today()
        tomorrow = (dt.date.fromisoformat(today)+dt.timedelta(days=1)).isoformat()
        with erp.transaction(self.db):
            self.db.execute("UPDATE products SET service_category='مكافحة حشرات' WHERE id=?", (self.service,))
        a = self.book(date=today,service_status='معاينة')
        self.book(date=tomorrow,service_status='متابعة')
        code, data, _ = self.request('/api/appointments?day=today&status=pending')
        self.assertEqual(code,200)
        self.assertEqual([r['id'] for r in data['items']], [a])
        self.assertEqual(data['summary']['today_inspection_count'],1)
        self.assertEqual(self.action([a],'complete')[0],200)
        self.assertEqual(len(self.request('/api/appointments?status=done')[1]['items']),1)
        self.assertEqual(len(self.request('/api/appointments?status=pending')[1]['items']),1)
        self.assertEqual(len(self.request('/api/appointments?service_status=%D9%85%D8%B9%D8%A7%D9%8A%D9%86%D8%A9')[1]['items']),1)
        for query in ('day=bad','status=bad','employee_id=-1','start_date=2026-10-30&end_date=2026-10-01'):
            self.assertEqual(self.request('/api/appointments?'+query)[0],400)

    def test_bulk_assignment_validates_all_rows_and_preserves_private_employee_data(self):
        a,b=self.book(),self.book()
        with erp.transaction(self.db):
            eid=erp.save_resource(self.db,'employees',dict(name='فني الموعد',code='ASSIGN',branch_id=self.branch,hire_date='2026-01-01',salary=1200,status='نشط'),self.users['admin']['id'])
        code,boot,_=self.request('/api/bootstrap',role='technician')
        self.assertEqual(set(boot['refs']['appointment_employees'][0]),{'id','name'})
        self.assertNotIn('employees',boot['refs'])
        self.assertEqual(self.action([a,b],'assign',employee_id=eid)[0],200)
        self.assertTrue(all(r['assigned_employee_id']==eid for r in self.request('/api/appointments')[1]['items']))
        self.assertEqual(self.action([a,99999],'complete')[0],400)
        self.assertEqual(appointments.get_appointment(self.db,a)['status'],'assigned')
        self.assertEqual(self.request('/api/appointments/actions','POST',dict(ids=[a],action='complete'),role='viewer')[0],403)
        self.assertEqual(self.request('/api/appointments',role='hr')[0],403)

    def test_generic_booking_fields_cannot_forge_workflow_and_product_is_not_a_service(self):
        a=self.book(status='quoted',quotation_id=123,invoice_id=123,assigned_employee_id=123)
        row=appointments.get_appointment(self.db,a)
        self.assertEqual(row['status'],'scheduled')
        self.assertIsNone(row['quotation_id'])
        self.assertEqual(self.request('/api/resources/appointments','POST',self.appointment(service_id=self.product))[0],400)
        self.assertEqual(self.request('/api/resources/appointments','POST',self.appointment(service_status='bad'))[0],400)

    def test_quotation_is_separate_per_booking_and_duplicate_conversion_is_idempotent(self):
        a,b=self.book(),self.book(phone='01000000002')
        payload=self.quote(customer_id=None,post=True)
        first=self.request(f'/api/appointments/{a}/quotation','POST',payload)
        self.assertEqual(first[0],200,first[1])
        duplicate=self.request(f'/api/appointments/{a}/quotation','POST',payload)[1]
        self.assertTrue(duplicate['existing'])
        self.assertEqual(duplicate['id'],first[1]['id'])
        second=self.request(f'/api/appointments/{b}/quotation','POST',payload)[1]
        self.assertNotEqual(first[1]['id'],second['id'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0],0)
        self.assertEqual(self.request(f'/api/resources/appointments/{a}','DELETE')[0],400)
        self.assertEqual(self.request(f'/api/resources/appointments/{a}','PUT',self.appointment())[0],400)

    def test_failed_technician_quote_rolls_back_new_customer_and_booking_state(self):
        a=self.book(phone='01000000009')
        count=self.db.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
        for changes in ({'discount':1},{'lines':[{'product_id':self.service,'quantity':1,'price':1}]},{'tax_rate':0}):
            code,_,_=self.request(f'/api/appointments/{a}/quotation','POST',self.quote(customer_id=None,**changes),role='technician')
            self.assertEqual(code,403)
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM customers').fetchone()[0],count)
            self.assertEqual(appointments.get_appointment(self.db,a)['status'],'scheduled')
        self.assertEqual(self.request(f'/api/appointments/{a}/invoice','POST',self.quote(kind='sale'),role='technician')[0],403)

    def test_direct_invoices_post_to_separate_activity_ledgers_and_report_each_activity(self):
        for activity in ('تنفيذ','معاينة','متابعة','إعادة العمل'):
            a=self.book(service_status=activity)
            code,body,_=self.request(f'/api/appointments/{a}/invoice','POST',self.quote(post=True,paid=100))
            self.assertEqual(code,200,body)
            self.assertEqual(self.request(f'/api/appointments/{a}/invoice','POST',self.quote(post=True))[1]['id'],body['id'])
            self.assertEqual(appointments.get_appointment(self.db,a)['status'],'invoiced')
        accounts=self.db.execute('SELECT activity,account_id FROM service_activity_accounts').fetchall()
        self.assertEqual(len(accounts),4)
        self.assertEqual(len({r['account_id'] for r in accounts}),4)
        self.assertEqual(self.db.execute('SELECT SUM(debit-credit) FROM journal_lines').fetchone()[0],0)
        rows=self.request('/api/reports/appointment_services')[1]
        self.assertEqual(len(rows),4)
        for row in rows:
            self.assertEqual((row['invoiced'],row['net_revenue'],row['tax'],row['total'],row['paid'],row['balance']),(1,500,70,570,100,470))
        self.assertEqual(self.request('/api/reports/appointment_services',role='technician')[0],403)
        csv=self.request('/api/reports/appointment_services?format=csv&lang=en')[1].decode('utf-8-sig')
        self.assertIn('Net revenue before tax',csv)
        self.assertIn('Rework',csv)

    def test_draft_invoice_and_status_changes_have_no_financial_effect_until_posted(self):
        a=self.book(service_status='متابعة')
        self.assertEqual(self.action([a],'complete')[0],200)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0],0)
        code,data,_=self.request(f'/api/appointments/{a}/invoice','POST',self.quote(post=False))
        self.assertEqual(code,200,data)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0],0)
        row=next(r for r in appointments.service_report(self.db,{}) if r['service_status']=='متابعة')
        self.assertEqual(row['total'],0)
        self.assertEqual(self.request(f"/api/documents/{data['id']}/post",'POST',{})[0],200)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM service_activity_accounts').fetchone()[0],1)

    def test_quote_invoice_conversion_outside_booking_is_detected_and_returns_keep_activity(self):
        a=self.book(service_status='إعادة العمل')
        q=self.request(f'/api/appointments/{a}/quotation','POST',self.quote(post=True))[1]['id']
        s=self.request('/api/documents','POST',self.quote(kind='sale',source_id=q,post=True))[1]['id']
        repeat=self.request(f'/api/appointments/{a}/invoice','POST',self.quote(post=True))[1]
        self.assertEqual(repeat['id'],s)
        self.assertTrue(repeat['existing'])
        r=self.request('/api/documents','POST',self.quote(kind='sale_return',source_id=s,post=True))[1]['id']
        self.assertEqual(erp.document_detail(self.db,r)['service_activity'],'إعادة العمل')
        row=next(r for r in appointments.service_report(self.db,{}) if r['service_status']=='إعادة العمل')
        self.assertEqual(row['total'],0)
        self.assertEqual(self.db.execute('SELECT SUM(debit-credit) FROM journal_lines').fetchone()[0],0)

    def test_today_reminder_is_new_once_and_completion_retires_it(self):
        a=self.book(date='2026-10-23')
        user=self.users['sales']
        with patch.object(appointments,'business_today',return_value='2026-10-22'):
            with erp.transaction(self.db):
                notifications.mark_read(self.db,user)
        with patch.object(appointments,'business_today',return_value='2026-10-23'):
            with erp.transaction(self.db):
                state=notifications.get_notifications(self.db,user)
            alerts=[r for r in state['items'] if r['kind']=='appointment']
            self.assertEqual(len(alerts),1)
            self.assertFalse(alerts[0]['is_read'])
            self.assertEqual(alerts[0]['title'],'موعد اليوم')
            self.assertEqual(alerts[0]['link'],'#/appointments?day=today')
            with erp.transaction(self.db):
                again=notifications.get_notifications(self.db,user)
            self.assertEqual(again['unread_count'],state['unread_count'])
            self.assertEqual(self.action([a],'complete')[0],200)
            with erp.transaction(self.db):
                after=notifications.get_notifications(self.db,user)
            self.assertFalse(any(r['kind']=='appointment' for r in after['items']))

    def test_revenue_account_creation_preserves_custom_accounts_and_snapshot_cannot_be_forged(self):
        with erp.transaction(self.db):
            custom=erp.save_resource(self.db,'accounts',dict(code='4111',name='Custom user account',type='إيرادات'),self.users['admin']['id'])
        a=self.book(service_status='تنفيذ')
        code,body,_=self.request(f'/api/appointments/{a}/invoice','POST',self.quote(post=True))
        self.assertEqual(code,200,body)
        self.assertEqual(self.db.execute('SELECT name FROM accounts WHERE id=?',(custom,)).fetchone()[0],'Custom user account')
        account=self.db.execute("SELECT account_id FROM service_activity_accounts WHERE activity='تنفيذ'").fetchone()[0]
        self.assertNotEqual(account,custom)
        self.assertEqual(self.db.execute('SELECT code FROM accounts WHERE id=?',(account,)).fetchone()[0],'4111-1')
        code,body,_=self.request('/api/documents','POST',self.quote(kind='sale',post=True,service_activity='معاينة'))
        self.assertEqual(code,200,body)
        self.assertEqual(erp.document_detail(self.db,body['id'])['service_activity'],'')

    def test_cancelled_booking_requires_reopen_and_batch_is_atomic(self):
        a,b=self.book(),self.book()
        self.assertEqual(self.action([b],'cancel')[0],200)
        self.assertEqual(self.action([a,b],'complete')[0],400)
        self.assertEqual(appointments.get_appointment(self.db,a)['status'],'scheduled')
        self.assertEqual(self.request(f'/api/appointments/{b}/quotation','POST',self.quote())[0],400)
        self.assertEqual(self.action([b],'reopen')[0],200)
        self.assertEqual(self.action([b],'not_executed')[0],200)
        self.assertEqual(appointments.get_appointment(self.db,b)['status'],'not_executed')


class AppointmentMigrationCase(unittest.TestCase):
    def test_legacy_booking_purpose_and_identifiers_survive_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'legacy.sqlite3'
            db=erp.connect(path)
            db.execute('CREATE TABLE appointments(id INTEGER PRIMARY KEY,customer_name TEXT,date TEXT,time TEXT,address TEXT,phone TEXT,service_type TEXT,site_type TEXT,created_at TEXT)')
            db.execute("INSERT INTO appointments VALUES(77,'Legacy','2026-10-22','13:00','Address','01012345678','إعادة عمل','فيلا','old')")
            db.commit();db.close()
            erp.initialize(path)
            db=erp.connect(path)
            try:
                row=appointments.get_appointment(db,77)
                self.assertEqual((row['id'],row['service_status'],row['status']),(77,'إعادة العمل','scheduled'))
                self.assertIsNone(row['service_id'])
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
                db.execute("UPDATE appointments SET service_status='تنفيذ' WHERE id=77");db.commit()
                erp.initialize(path)
                self.assertEqual(db.execute('SELECT service_status FROM appointments WHERE id=77').fetchone()[0],'تنفيذ')
            finally: db.close()
