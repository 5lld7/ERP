"""Vercel's supported BaseHTTPRequestHandler entrypoint."""
import os
import logging
import sqlite3
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import erp
from database import DatabaseUnavailable, remote_settings, safe_database_detail
from server import Handler

os.umask(0o077)

_ready = False
_lock = threading.Lock()
LOG = logging.getLogger('erp.startup')


def startup_step(stage, operation):
    try:
        return operation()
    except sqlite3.Error as exc:
        code = exc.code if isinstance(exc, DatabaseUnavailable) else {
            'connect': 'DATABASE_CONNECTION', 'read_version': 'DATABASE_SCHEMA',
            'initialize_schema': 'DATABASE_INITIALIZE',
        }[stage]
        detail = exc.diagnostic if isinstance(exc, DatabaseUnavailable) else safe_database_detail(exc)
        LOG.error('ERP startup failed: stage=%s code=%s detail=%s', stage, code, detail)
        raise

STARTUP_ERRORS = {
    'DATABASE_URL_MISSING': 'متغير ERP_DATABASE_URL غير موجود في هذا النشر. أضفه إلى Production ثم أعد النشر.',
    'DATABASE_TOKEN_MISSING': 'متغير ERP_DATABASE_TOKEN غير موجود في هذا النشر. أضف توكن Turso ثم أعد النشر.',
    'DATABASE_URL_INVALID': 'صيغة ERP_DATABASE_URL غير صحيحة. انسخ Database URL من Turso ثم أعد النشر.',
    'COOKIE_SECURE': 'اجعل قيمة ERP_COOKIE_SECURE تساوي 1 ثم أعد النشر.',
    'DATABASE_AUTH': 'Turso رفض توكن الاتصال. راجع ERP_DATABASE_TOKEN وصلاحيته لهذه القاعدة ثم أعد النشر.',
    'DATABASE_PERMISSION': 'Turso رفض صلاحية العملية. تأكد أن توكن القاعدة يسمح بالقراءة والكتابة.',
    'DATABASE_CONNECTION': 'تعذر الاتصال بقاعدة Turso. راجع رابط القاعدة وحالة الخدمة.',
    'DATABASE_SCHEMA': 'تعذرت قراءة إصدار قاعدة البيانات.',
    'DATABASE_INITIALIZE': 'تعذر إنشاء جداول النظام في Turso. تحقق من صلاحية القراءة والكتابة.',
    'DATABASE_VERSION': 'إصدار قاعدة البيانات أحدث من إصدار التطبيق المنشور.',
}


def ensure_ready():
    global _ready
    if os.environ.get('VERCEL'):
        # /tmp is never a replacement for durable company data.
        if not os.environ.get('ERP_DATABASE_URL', '').strip():
            raise DatabaseUnavailable('DATABASE_URL_MISSING')
        if not os.environ.get('ERP_DATABASE_TOKEN', '').strip():
            raise DatabaseUnavailable('DATABASE_TOKEN_MISSING')
        try:
            remote_settings()
        except (sqlite3.Error, ValueError):
            raise DatabaseUnavailable('DATABASE_URL_INVALID') from None
        if os.environ.get('ERP_COOKIE_SECURE') != '1':
            raise DatabaseUnavailable('COOKIE_SECURE')
    if not _ready:
        with _lock:
            if not _ready:
                try:
                    db = startup_step('connect', erp.connect)
                except DatabaseUnavailable:
                    raise
                except sqlite3.Error:
                    raise DatabaseUnavailable('DATABASE_CONNECTION') from None
                try:
                    version = startup_step('read_version', lambda: db.execute('PRAGMA user_version').fetchone()[0])
                except DatabaseUnavailable:
                    raise
                except sqlite3.Error:
                    raise DatabaseUnavailable('DATABASE_SCHEMA') from None
                finally:
                    db.close()
                if version > erp.SCHEMA_VERSION:
                    raise DatabaseUnavailable('DATABASE_VERSION')
                if version != erp.SCHEMA_VERSION:
                    try:
                        startup_step('initialize_schema', erp.initialize)
                    except DatabaseUnavailable:
                        raise
                    except sqlite3.Error:
                        raise DatabaseUnavailable('DATABASE_INITIALIZE') from None
                _ready = True


class handler(Handler):
    def dispatch_request(self, method):
        url = urlsplit(self.path)
        params = parse_qs(url.query, keep_blank_values=True)
        route = params.pop('erp_path', [None])[0]
        if url.path in ('/api/index.py', '/api/index') and route is not None:
            self.path = urlunsplit(('', '', '/api/' + route.lstrip('/'),
                                    urlencode(params, doseq=True), ''))
        try:
            ensure_ready()
        except DatabaseUnavailable as exc:
            code = exc.code if exc.code in STARTUP_ERRORS else 'DATABASE_CONNECTION'
            return self.respond({'error': STARTUP_ERRORS[code] + ' [' + code + ']', 'code': code}, 503)
        except sqlite3.Error:
            return self.respond({'error': 'إعداد قاعدة البيانات الدائمة غير مكتمل أو الاتصال غير متاح. راجع متغيرات Vercel.'}, 503)
        return super().dispatch_request(method)
