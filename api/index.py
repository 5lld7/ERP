"""Vercel's supported BaseHTTPRequestHandler entrypoint."""
import os
import sqlite3
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import erp
from database import remote_settings
from server import Handler

os.umask(0o077)

_ready = False
_lock = threading.Lock()


def ensure_ready():
    global _ready
    if os.environ.get('VERCEL'):
        # /tmp is never a replacement for durable company data.
        if not remote_settings():
            raise sqlite3.OperationalError('Configure ERP_DATABASE_URL and ERP_DATABASE_TOKEN in Vercel')
        if os.environ.get('ERP_COOKIE_SECURE') != '1':
            raise sqlite3.OperationalError('Set ERP_COOKIE_SECURE=1 in Vercel')
    if not _ready:
        with _lock:
            if not _ready:
                db = erp.connect()
                try:
                    version = db.execute('PRAGMA user_version').fetchone()[0]
                finally:
                    db.close()
                if version > erp.SCHEMA_VERSION:
                    raise sqlite3.OperationalError('Database schema is newer than this application')
                if version != erp.SCHEMA_VERSION:
                    erp.initialize()
                _ready = True


class handler(Handler):
    def handle_request(self, method):
        url = urlsplit(self.path)
        params = parse_qs(url.query, keep_blank_values=True)
        route = params.pop('erp_path', [None])[0]
        if url.path in ('/api/index.py', '/api/index') and route is not None:
            self.path = urlunsplit(('', '', '/api/' + route.lstrip('/'),
                                    urlencode(params, doseq=True), ''))
        try:
            ensure_ready()
        except sqlite3.Error:
            return self.respond({'error': 'إعداد قاعدة البيانات الدائمة غير مكتمل أو الاتصال غير متاح. راجع متغيرات Vercel.'}, 503)
        return super().handle_request(method)
