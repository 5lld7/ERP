"""Vercel entrypoint and libSQL adapter checks; never use remote credentials."""
import hashlib
import json
import os
import secrets
import sqlite3
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import erp
from api import index
from database import Connection, remote_settings


class RuntimeHandler(index.handler):
    """Match Vercel's wrapper, which owns handle_request() with no arguments.

    See vercel_runtime.vc_init: its handler dispatches to our do_* methods.
    """
    def handle_one_request(self):
        self.raw_requestline = self.rfile.readline(65537)
        if not self.raw_requestline:
            self.close_connection = True
            return
        if self.parse_request():
            self.handle_request()

    def handle_request(self):
        getattr(self, 'do_' + self.command)()
        self.wfile.flush()


class AdapterCase(unittest.TestCase):
    def test_settings_require_tls_and_no_embedded_credentials(self):
        for url in ('http://example.com','file:///tmp/unsafe','https://user:pass@example.com','libsql://db.turso.io?tls=0'):
            with self.subTest(url=url),patch.dict(os.environ,{'ERP_DATABASE_URL':url,'ERP_DATABASE_TOKEN':'test-value'}):
                with self.assertRaises(sqlite3.OperationalError):
                    remote_settings()
        with patch.dict(os.environ,{'ERP_DATABASE_URL':'libsql://db.turso.io','ERP_DATABASE_TOKEN':''}):
            with self.assertRaises(sqlite3.OperationalError):
                remote_settings()

    def test_failed_remote_does_not_fall_back_to_local_file(self):
        with patch.dict(os.environ,{'VERCEL':'1','ERP_DATABASE_URL':'','ERP_DATABASE_TOKEN':''}):
            with self.assertRaises(sqlite3.OperationalError):
                erp.connect()

    def test_integrity_errors_and_atomic_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Connection(Path(directory)/'adapter.sqlite3')
            try:
                db.execute('CREATE TABLE sample(id INTEGER PRIMARY KEY,name TEXT UNIQUE)')
                db.execute('BEGIN IMMEDIATE')
                db.execute('INSERT INTO sample(name) VALUES(?)',('unique',))
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute('INSERT INTO sample(name) VALUES(?)',('unique',))
                db.rollback()
                self.assertEqual(db.execute('SELECT COUNT(*) count FROM sample').fetchone()['count'],0)
            finally:
                db.close()


class VercelHandlerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.old=(erp.DATA,erp.DB_PATH,index._ready)
        erp.DATA=Path(cls.tmp.name)
        erp.DB_PATH=erp.DATA/'serverless.sqlite3'
        index._ready=False
        cls.setup_token=secrets.token_urlsafe(32)
        cls.environment=patch.dict(os.environ,{'ERP_DATABASE_URL':'','ERP_DATABASE_TOKEN':'','ERP_SETUP_TOKEN':cls.setup_token,'ERP_DB_DRIVER':'libsql','VERCEL':'','ERP_COOKIE_SECURE':'0'})
        cls.environment.start()
        cls.httpd=ThreadingHTTPServer(('127.0.0.1',0),RuntimeHandler)
        cls.thread=threading.Thread(target=cls.httpd.serve_forever,daemon=True)
        cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.httpd.server_address[1]}'
        cls.client=build_opener(HTTPCookieProcessor())

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()
        cls.environment.stop()
        erp.DATA,erp.DB_PATH,index._ready=cls.old
        cls.tmp.cleanup()

    def request(self,path,method='GET',data=None,client=None):
        request=Request(self.base+path,method=method,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','X-ERP-Request':'1'})
        try:
            response=(client or self.client).open(request)
        except HTTPError as exc:
            response=exc
        body=response.read()
        return response.status,json.loads(body) if response.headers.get('Content-Type','').startswith('application/json') else body,response.headers

    def test_01_rewrite_and_protected_first_administrator(self):
        code,data,_=self.request('/api/index.py?erp_path=auth')
        self.assertEqual(code,200,data)
        self.assertTrue(data['setup_token_required'])
        user=dict(name='المدير',company_name='شركة اختبار',username='admin',password=secrets.token_urlsafe(20))
        code,data,_=self.request('/api/index.py?erp_path=setup','POST',user)
        self.assertEqual(code,403,data)
        user['setup_token']=self.setup_token
        code,data,_=self.request('/api/index.py?erp_path=setup','POST',user)
        self.assertEqual(code,200,data)
        code,data,_=self.request('/api/index.py?erp_path=bootstrap')
        self.assertEqual(code,200,data)
        self.assertEqual(data['user']['role'],'admin')

    def test_02_cold_start_preserves_company_data_and_sessions(self):
        code,data,_=self.request('/api/index.py?erp_path=resources/customers','POST',dict(name='عميل محفوظ',classification='عادي'))
        self.assertEqual(code,200,data)
        index._ready=False
        code,data,_=self.request('/api/index.py?erp_path=resources/customers')
        self.assertEqual(code,200,data)
        self.assertIn('عميل محفوظ',[row['name'] for row in data])

    def test_03_no_ephemeral_database_when_vercel_config_missing(self):
        with patch.dict(os.environ,{'VERCEL':'1'}):
            code,data,_=self.request('/api/index.py?erp_path=auth')
        self.assertEqual(code,503,data)

    def test_04_rate_limit_survives_cold_start(self):
        key=hashlib.sha256(b'blocked-user').hexdigest()
        import time
        db=erp.connect()
        try:
            db.execute('INSERT INTO auth_attempts(key,attempts,started_at) VALUES(?,20,?)',(key,int(time.time())))
            db.commit()
        finally:
            db.close()
        index._ready=False
        code,data,_=self.request('/api/index.py?erp_path=login','POST',dict(username='blocked-user',password='incorrect-password'))
        self.assertEqual(code,429,data)

    def test_05_secure_cookie_flag(self):
        db=erp.connect()
        try:
            user=db.execute('SELECT id FROM users LIMIT 1').fetchone()[0]
            with patch.dict(os.environ,{'ERP_COOKIE_SECURE':'1'}):
                session=index.handler.new_session(None,db,user)
            db.commit()
            self.assertIn('; Secure',session['Set-Cookie'])
        finally:
            db.close()


if __name__=='__main__':
    unittest.main(verbosity=2)
