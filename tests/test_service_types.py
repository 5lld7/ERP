"""User-managed service types with safe renames, deletion and v6 migration."""
import unittest
from urllib.parse import urlencode

import erp
from tests import test_industry_http as fixtures


class ServiceTypeCase(unittest.TestCase):
    setUpClass=classmethod(fixtures.IndustryHTTPCase.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.IndustryHTTPCase.tearDownClass.__func__)
    setUp=fixtures.IndustryHTTPCase.setUp
    tearDown=fixtures.IndustryHTTPCase.tearDown
    request=fixtures.IndustryHTTPCase.request
    appointment=fixtures.IndustryHTTPCase.appointment
    quote=fixtures.IndustryHTTPCase.quote

    def create_type(self,name='نوع خاص',name_en='Custom type'):
        code,data,_=self.request('/api/resources/service_types','POST',dict(name=name,name_en=name_en))
        self.assertEqual(code,200,data)
        return data['id']

    def service_data(self,category):
        return dict(name='Existing service',sku='HTTP-SERVICE',unit_id=self.unit,price=250,service_method='Original method',service_category=category)

    def test_create_read_update_and_bootstrap_choices_are_dynamic(self):
        tid=self.create_type()
        code,data,_=self.request('/api/resources/service_types')
        self.assertEqual(code,200)
        self.assertTrue(any(r['id']==tid and r['name_en']=='Custom type' for r in data))
        boot=self.request('/api/bootstrap')[1]
        choices=next(f['options'] for f in boot['resources']['services']['fields'] if f['key']=='service_category')
        self.assertIn('نوع خاص',choices)
        self.assertFalse(next(f['translateOptions'] for f in boot['resources']['services']['fields'] if f['key']=='service_category'))
        self.assertEqual(self.request(f'/api/resources/service_types/{tid}','PUT',dict(name='اسم جديد',name_en='New name'))[0],200)
        self.assertEqual(self.request(f'/api/resources/service_types/{tid}','DELETE')[0],200)

    def test_rename_updates_linked_services_bookings_and_report_filter_without_financial_changes(self):
        tid=self.create_type()
        self.assertEqual(self.request(f'/api/resources/services/{self.service}','PUT',self.service_data('نوع خاص'))[0],200)
        aid=self.request('/api/resources/appointments','POST',self.appointment())[1]['id']
        invoice=self.request(f'/api/appointments/{aid}/invoice','POST',self.quote(post=True))[1]['id']
        balance=erp.party_balance(self.db,'customer',self.customer)
        self.assertEqual(self.request(f'/api/resources/service_types/{tid}','PUT',dict(name='نوع محدث',name_en='Updated type'))[0],200)
        data=self.request('/api/appointments?'+urlencode({'service_category':'نوع محدث'}))[1]
        self.assertEqual([r['id'] for r in data['items']],[aid])
        self.assertEqual(data['items'][0]['service_category'],'نوع محدث')
        report=self.request('/api/reports/appointment_services?'+urlencode({'service_category':'نوع محدث'}))[1]
        self.assertEqual(sum(r['total'] for r in report),570)
        self.assertEqual(erp.party_balance(self.db,'customer',self.customer),balance)
        self.assertEqual(erp.document_detail(self.db,invoice)['lines'][0]['service_method'],'Original method')
        self.assertEqual(self.request('/api/appointments?'+urlencode({'service_category':'نوع خاص'}))[0],400)

    def test_used_type_requires_reassignment_before_delete_and_deleted_defaults_do_not_return(self):
        types=self.request('/api/resources/service_types')[1]
        cleaning=next(r for r in types if r['name']=='تنظيف')
        self.assertEqual(self.request(f'/api/resources/services/{self.service}','PUT',self.service_data('تنظيف'))[0],200)
        code,data,_=self.request(f"/api/resources/service_types/{cleaning['id']}",'DELETE')
        self.assertEqual(code,400)
        self.assertIn('in use',data['error'])
        self.assertEqual(self.request(f'/api/resources/services/{self.service}','PUT',self.service_data('مكافحة حشرات'))[0],200)
        self.assertEqual(self.request(f"/api/resources/service_types/{cleaning['id']}",'DELETE')[0],200)
        erp.initialize()
        self.assertFalse(any(r['name']=='تنظيف' for r in self.request('/api/resources/service_types')[1]))

    def test_permissions_and_validation(self):
        for role in ('sales','technician','hr','viewer'):
            self.assertEqual(self.request('/api/resources/service_types','POST',dict(name='Forbidden'),role=role)[0],403)
        self.assertTrue(self.request('/api/bootstrap',role='technician')[1]['refs']['service_types'])
        self.assertEqual(self.request('/api/resources/service_types','POST',dict(name='   '))[0],400)
        self.assertEqual(self.request('/api/resources/service_types','POST',dict(name='تنظيف'))[0],400)
        self.create_type('Cleaning Extra')
        self.assertEqual(self.request('/api/resources/service_types','POST',dict(name='  cleaning extra  '))[0],400)
        self.assertEqual(self.request(f'/api/resources/services/{self.service}','PUT',self.service_data('Unregistered'))[0],400)

    def test_migration_adopts_existing_type_values_and_preserves_service_ids(self):
        with erp.transaction(self.db):
            self.db.execute("UPDATE products SET service_category='Legacy special' WHERE id=?",(self.service,))
            self.db.execute('DROP TABLE service_types')
        erp.initialize()
        types=self.request('/api/resources/service_types')[1]
        self.assertIn('Legacy special',[r['name'] for r in types])
        self.assertEqual(self.db.execute('SELECT service_category FROM products WHERE id=?',(self.service,)).fetchone()[0],'Legacy special')
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])
