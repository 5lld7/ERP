"""Durable notification isolation, recurrence, permissions and sound polling."""
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import erp
import notifications
from database import Connection


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = '''
CREATE TABLE users(id INTEGER PRIMARY KEY);
CREATE TABLE products(id INTEGER PRIMARY KEY,name TEXT,min_stock REAL,expiry_date TEXT,item_type TEXT);
CREATE TABLE stock(product_id INTEGER,quantity REAL);
CREATE TABLE stock_moves(id INTEGER PRIMARY KEY,product_id INTEGER);
CREATE TABLE employees(id INTEGER PRIMARY KEY,name TEXT,status TEXT,residency_expiry TEXT,passport_expiry TEXT,driving_license_expiry TEXT);
CREATE TABLE leaves(id INTEGER PRIMARY KEY,employee_id INTEGER,start_date TEXT,end_date TEXT,status TEXT);
CREATE TABLE appointments(id INTEGER PRIMARY KEY,customer_name TEXT,date TEXT,time TEXT);
CREATE TABLE customers(id INTEGER PRIMARY KEY,name TEXT);
CREATE TABLE documents(id INTEGER PRIMARY KEY,number TEXT,kind TEXT,date TEXT,customer_id INTEGER,progress TEXT,status TEXT,source_id INTEGER);
INSERT INTO users VALUES(1),(2),(3),(4),(5),(6);
INSERT INTO products VALUES(1,'المخزون',5,'2026-11-01','product'),(2,'خدمة غير مخزنية',100,'2026-11-01','service'),(3,'رصيد كاف',0,NULL,'product');
INSERT INTO stock VALUES(1,2),(3,10);
INSERT INTO stock_moves VALUES(1,1);
INSERT INTO employees VALUES(1,'بيانات موظف خاصة','نشط','2026-10-01','2026-11-10','2027-01-01'),(2,'موظف موقوف','موقوف','2026-10-01','2026-10-01','2026-10-01');
INSERT INTO leaves VALUES(1,1,'2026-10-23','2026-10-24','قيد المراجعة');
INSERT INTO appointments VALUES(1,'عميل موعد','2026-10-23','10:30'),(2,'موعد قديم','2026-10-01','10:30');
INSERT INTO customers VALUES(1,'عميل معاينة');
INSERT INTO documents VALUES(1,'INS-1','inspection','2026-10-22',1,'جديدة','draft',NULL),(2,'INS-2','inspection','2026-10-22',1,'مرفوضة','posted',NULL),(3,'INS-3','inspection','2026-10-22',1,'محولة لفاتورة','posted',NULL),(4,'INS-4','inspection','2026-10-22',1,'مقبولة','posted',NULL),(5,'SAL-1','sale','2026-10-22',1,'جديدة','posted',4);
'''


class NotificationCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        if os.environ.get('ERP_DB_DRIVER') == 'libsql':
            self.db = Connection(Path(self.directory.name) / 'notifications.sqlite3')
        else:
            self.db = sqlite3.connect(':memory:')
            self.db.row_factory = sqlite3.Row
        self.db.executescript(FIXTURES + notifications.SCHEMA)
        self.today = patch.object(erp, 'today', return_value='2026-10-22')
        self.today.start()

    def tearDown(self):
        self.today.stop()
        self.db.close()
        self.directory.cleanup()

    def get(self, user=None):
        with erp.transaction(self.db):
            return notifications.get_notifications(self.db, user or {'id': 1, 'role': 'admin'})

    def read(self, ids=None, user=None):
        with erp.transaction(self.db):
            return notifications.mark_read(self.db, user or {'id': 1, 'role': 'admin'}, ids)

    def test_polling_is_idempotent_and_read_state_is_durable(self):
        first = self.get()
        self.assertEqual(first['unread_count'], 7)
        self.assertEqual(len(first['items']), 7)
        self.assertEqual(self.get(), first)
        self.assertNotIn('خدمة غير مخزنية', json.dumps(first, ensure_ascii=False))
        self.assertNotIn('موظف موقوف', json.dumps(first, ensure_ascii=False))
        partial = self.read([first['items'][0]['id']])
        self.assertEqual(partial['unread_count'], 6)
        self.assertTrue(next(item for item in partial['items'] if item['id'] == first['items'][0]['id'])['is_read'])
        self.assertEqual(self.get()['unread_count'], 6)
        self.assertEqual(self.read()['unread_count'], 0)
        self.assertEqual(self.get()['unread_count'], 0)

    def test_permissions_keep_hr_and_stock_details_out_of_sales(self):
        for role, identifier, count, kinds in (
            ('sales', 2, 2, {'appointment', 'inspection'}),
            ('hr', 3, 3, {'pending_leave', 'residency_expiry', 'passport_expiry'}),
            ('inventory', 4, 2, {'low_stock', 'product_expiry'}),
            ('technician', 5, 2, {'appointment', 'inspection'}),
        ):
            with self.subTest(role=role):
                snapshot = self.get({'id': identifier, 'role': role})
                self.assertEqual(snapshot['unread_count'], count)
                self.assertEqual({item['kind'] for item in snapshot['items']}, kinds)
                if role in ('sales', 'technician'):
                    self.assertNotIn('بيانات موظف خاصة', json.dumps(snapshot, ensure_ascii=False))
        self.assertEqual(self.get({'id': 6, 'role': 'unknown'}), {'items': [], 'unread_count': 0})

    def test_guessed_ids_cannot_mark_another_users_notifications(self):
        admin = self.get()
        sales = self.get({'id': 2, 'role': 'sales'})
        guessed = self.read([item['id'] for item in admin['items']], {'id': 2, 'role': 'sales'})
        self.assertEqual(guessed['unread_count'], sales['unread_count'])
        self.assertEqual(self.get()['unread_count'], admin['unread_count'])
        self.read(user={'id': 2, 'role': 'sales'})
        self.assertEqual(self.get()['unread_count'], 7)

    def test_resolved_alert_retires_and_recurrence_is_new_unread(self):
        with patch.object(notifications.time, 'time', return_value=1000):
            first = self.get()
        stock = next(item for item in first['items'] if item['kind'] == 'low_stock')
        self.read()
        self.db.execute('UPDATE stock SET quantity=9 WHERE product_id=1')
        self.db.commit()
        resolved = self.get()
        self.assertNotIn(stock['id'], [item['id'] for item in resolved['items']])
        self.assertEqual(resolved['unread_count'], 0)
        self.db.execute('UPDATE stock SET quantity=2 WHERE product_id=1')
        self.db.commit()
        with patch.object(notifications.time, 'time', return_value=1200):
            recurring = self.get()
        current = next(item for item in recurring['items'] if item['kind'] == 'low_stock')
        self.assertEqual(current['id'], stock['id'])
        self.assertEqual(current['created_at'], 1200)
        self.assertFalse(current['is_read'])
        self.assertEqual(recurring['unread_count'], 1)

    def test_new_stock_movement_generates_once_without_duplicate_active_alert(self):
        self.get()
        self.read()
        self.db.execute('INSERT INTO stock_moves VALUES(2,1)')
        self.db.commit()
        snapshot = self.get()
        self.assertEqual(snapshot['unread_count'], 1)
        self.assertEqual(len([item for item in snapshot['items'] if item['kind'] == 'low_stock']), 1)
        self.assertEqual(self.get()['unread_count'], 1)

    def test_rescheduled_appointment_replaces_old_actionable_alert(self):
        initial = self.get()
        previous = next(item['id'] for item in initial['items'] if item['kind'] == 'appointment')
        self.read()
        self.db.execute("UPDATE appointments SET date='2026-10-24',time='12:30' WHERE id=1")
        self.db.commit()
        snapshot = self.get()
        current = next(item for item in snapshot['items'] if item['kind'] == 'appointment')
        self.assertNotEqual(previous, current['id'])
        self.assertIn('2026-10-24 12:30', current['detail'])
        self.assertEqual(snapshot['unread_count'], 1)

    def test_role_change_hides_old_notifications_and_cannot_mark_hidden_rows(self):
        self.get()
        restricted = self.read(user={'id': 1, 'role': 'sales'})
        self.assertEqual(restricted['unread_count'], 0)
        self.assertEqual(len(restricted['items']), 2)
        self.assertEqual(self.get()['unread_count'], 5)

    def test_reconciliation_rolls_back_with_caller_transaction(self):
        with self.assertRaises(RuntimeError):
            with erp.transaction(self.db):
                notifications.get_notifications(self.db, {'id': 1, 'role': 'admin'})
                raise RuntimeError('abort the request')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0], 0)

    def test_invalid_read_ids_do_not_mark_notifications(self):
        self.get()
        for ids in ('all', [True], [-1], ['1'], list(range(1, 502))):
            with self.subTest(ids=type(ids).__name__), self.assertRaises(erp.BusinessError):
                self.read(ids)
        self.assertEqual(self.read([])['unread_count'], 7)

    def test_counter_and_mark_all_include_alerts_beyond_visible_page(self):
        additions = [(identifier, f'صنف {identifier}', 0, None, 'product') for identifier in range(100, 305)]
        for offset in range(0, len(additions), 100):
            batch = additions[offset:offset + 100]
            marks = ','.join('(?,?,?,?,?)' for _ in batch)
            self.db.execute('INSERT INTO products VALUES ' + marks, [value for row in batch for value in row])
        self.db.commit()
        snapshot = self.get()
        self.assertEqual(snapshot['unread_count'], 212)
        self.assertEqual(len(snapshot['items']), 200)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0], 212)
        self.assertEqual(self.read()['unread_count'], 0)
        self.assertEqual(self.get()['unread_count'], 0)


class NotificationControllerCase(unittest.TestCase):
    def test_opt_in_sound_deduplicates_polling_and_logout_discards_inflight_user_data(self):
        script = r'''
const assert = require('node:assert/strict');
const {createController} = require('./static/notifications.js');
let tones=0, intervals=0, payload={items:[{id:1,created_at:10,is_read:false}],unread_count:1};
const store=new Map();
class Audio {
 constructor(){this.state='suspended';this.currentTime=0;this.destination={};}
 resume(){this.state='running';return Promise.resolve();}
 close(){this.state='closed';return Promise.resolve();}
 createOscillator(){return {type:'',frequency:{setValueAtTime(){}},connect(){},start(){tones++;},stop(){}};}
 createGain(){return {gain:{setValueAtTime(){},linearRampToValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){}};}
}
const runtime={AudioContext:Audio,localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},
 document:{visibilityState:'visible',addEventListener(){},removeEventListener(){}},
 addEventListener(){},removeEventListener(){},setInterval(){intervals++;return intervals;},clearInterval(){intervals--;}};
const controller=createController(runtime);
(async()=>{
 const options={userId:1,fetchNotifications:async()=>payload,markRead:async()=>{
   payload={items:payload.items.map(x=>({...x,is_read:true})),unread_count:0};return payload;
 }};
 await controller.start(options);
 assert.equal(controller.getState().unread_count,1);assert.equal(tones,0);
 assert.equal(controller.getState().soundEnabled,false);
 await controller.toggleSound();assert.equal(tones,0,'enabling sound must not replay old alerts');
 await controller.refresh();assert.equal(tones,0,'same notification should not sound twice');
 payload={items:[{id:2,created_at:11,is_read:false},...payload.items],unread_count:2};
 await controller.refresh();assert.equal(tones,2,'one two-note sound for new notifications');
 await controller.refresh();assert.equal(tones,2);
 await controller.start(options);assert.equal(tones,2,'rerender must not reset sound baseline');
 assert.equal(intervals,1,'rerender cannot create duplicate polling intervals');
 await controller.markAllRead();assert.equal(controller.getState().unread_count,0);
 controller.stop();assert.equal(intervals,0);assert.deepEqual(controller.getState().items,[]);
 await controller.start({userId:2,fetchNotifications:async()=>({items:[{id:100,created_at:100,is_read:false}],unread_count:1})});
 assert.equal(controller.getState().soundEnabled,false,'sound preference cannot leak between users');
 assert.equal(tones,2);controller.stop();
 let release;
 const pending=controller.start({userId:3,fetchNotifications:()=>new Promise(resolve=>{release=resolve;})});
 await Promise.resolve();await Promise.resolve();
 controller.stop();release({items:[{id:999,detail:'private previous user'}],unread_count:1});
 await pending;assert.equal(controller.getState().unread_count,0);assert.deepEqual(controller.getState().items,[]);
 assert.equal(intervals,0);
 console.log('PASS notification controller sound, deduplication and user isolation');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS notification controller', result.stdout)
