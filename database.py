"""Compatibility layer for the official libSQL SDK, retaining SQLite semantics.

Remote connections go to Turso directly; no writable deployment filesystem or
embedded replica is used. Explicit transactions remain on a single connection.
"""
import os
import json
import re
import sqlite3
from urllib.parse import quote, urlsplit


def safe_database_detail(message):
    """Redact credentials and endpoints before a startup diagnostic is logged."""
    message = str(message)
    for name, value in os.environ.items():
        if value and (name == 'ERP_DATABASE_URL' or name.endswith(('_TOKEN', '_SECRET', '_PASSWORD', '_KEY'))):
            for form in (value, json.dumps(value)[1:-1], quote(value, safe='')):
                message = message.replace(form, '[redacted]')
    message = re.sub(r'(?:https?|libsql)://[^\s`\"<>]+', '[endpoint]', message, flags=re.I)
    message = re.sub(r'\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[token]', message)
    message = re.sub(r'Bearer\s+[^\s`\"<>]+', 'Bearer [token]', message, flags=re.I)
    return ' '.join(message.split())[:600]


class DatabaseUnavailable(sqlite3.OperationalError):
    """A public fixed code and a redacted, server-only startup diagnostic."""
    def __init__(self, code, diagnostic=''):
        self.code = code
        self.diagnostic = safe_database_detail(diagnostic)
        super().__init__(code)


class Record(dict):
    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def read_schema_version(db):
    """Read application metadata, accepting databases from the PRAGMA era."""
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='erp_metadata'").fetchone():
        row = db.execute("SELECT value FROM erp_metadata WHERE key='schema_version'").fetchone()
        if row is not None:
            return int(row[0])
    # Turso permits reading this PRAGMA but forbids assigning it. Old local
    # databases and their backups used the SQLite header to store the version.
    return int(db.execute('PRAGMA user_version').fetchone()[0])


def write_schema_version(db, version):
    """Persist within the caller's transaction using SQL supported by Turso."""
    db.execute('CREATE TABLE IF NOT EXISTS erp_metadata (key TEXT PRIMARY KEY,value INTEGER NOT NULL)')
    db.execute("INSERT INTO erp_metadata(key,value) VALUES('schema_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (int(version),))


def checked(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except ValueError as exc:
        # SDK errors can contain credentials. Only retain a redacted diagnostic;
        # the API exposes fixed codes, never the SDK text.
        message = str(exc).lower()
        if any(marker in message for marker in (
            'unique constraint', 'foreign key constraint', 'check constraint',
            'not null constraint', 'constraint failed',
        )):
            raise sqlite3.IntegrityError('Database constraint failed') from None
        if any(marker in message for marker in ('401', 'unauthorized', 'unauthenticated', 'invalid token', 'token expired', 'jwt expired', 'jwt_invalid', 'jwt_expired', 'authentication failed')):
            raise DatabaseUnavailable('DATABASE_AUTH', str(exc)) from None
        if any(marker in message for marker in ('403', 'forbidden', 'read-only', 'readonly')):
            raise DatabaseUnavailable('DATABASE_PERMISSION', str(exc)) from None
        raise DatabaseUnavailable('DATABASE_CONNECTION', str(exc)) from None


class Cursor:
    def __init__(self, cursor):
        self.description = checked(lambda: cursor.description)
        self.lastrowid = checked(lambda: cursor.lastrowid)
        self.rowcount = checked(lambda: cursor.rowcount)
        columns = [col[0] for col in (self.description or [])]
        rows = checked(cursor.fetchall) or []
        self._rows = iter(Record(zip(columns, row)) for row in rows)
        checked(cursor.close)

    def fetchone(self):
        return next(self._rows, None)

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return self._rows


class Connection:
    def __init__(self, database, token=None):
        import libsql
        self._db = checked(libsql.connect, str(database), timeout=20,
                           auth_token=token or '')

    def execute(self, sql, parameters=()):
        return Cursor(checked(self._db.execute, sql, tuple(parameters)))

    def executescript(self, script):
        # Use cursor.executescript: SDK 0.1.11's connection-level method can
        # swallow errors. Cursor-level calls propagate them correctly.
        cursor = checked(self._db.cursor)
        try:
            checked(cursor.executescript, script)
        finally:
            checked(cursor.close)

    def commit(self):
        checked(self._db.commit)

    def rollback(self):
        checked(self._db.rollback)

    def close(self):
        checked(self._db.close)

    @property
    def in_transaction(self):
        return checked(lambda: self._db.in_transaction)

    def backup(self, target):
        """Create a consistent portable SQLite snapshot inside a read transaction.

        Target must be a new database. All tables, IDs, BLOBs and indexes are
        preserved. Source transactions are never committed by this operation.
        """
        if target.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
            raise sqlite3.OperationalError('Backup target must be empty')
        owned = not self.in_transaction
        if owned:
            self.execute('BEGIN')
        try:
            schema = self.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','index','trigger','view') AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END,name").fetchall()
            target.execute('BEGIN')
            for obj in schema:
                if obj['type'] == 'table':
                    target.execute(obj['sql'])
            for obj in schema:
                if obj['type'] != 'table':
                    continue
                name = '"' + obj['name'].replace('"','""') + '"'
                cursor = self.execute(f'SELECT * FROM {name}')
                columns = len(cursor.description or [])
                rows = [tuple(row.values()) for row in cursor]
                if rows:
                    target.executemany(f'INSERT INTO {name} VALUES({",".join("?" for _ in range(columns))})', rows)
            for obj in schema:
                if obj['type'] != 'table':
                    target.execute(obj['sql'])
            write_schema_version(target, read_schema_version(self))
            if target.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or target.execute('PRAGMA foreign_key_check').fetchone():
                raise sqlite3.OperationalError('Backup integrity check failed')
            target.commit()
        except Exception:
            target.rollback()
            raise
        finally:
            if owned:
                self.rollback()


def remote_settings():
    url = os.environ.get('ERP_DATABASE_URL', '').strip()
    token = os.environ.get('ERP_DATABASE_TOKEN', '')
    if not url:
        return None
    parsed = urlsplit(url)
    if (parsed.scheme not in ('libsql','https') or not parsed.hostname
            or parsed.username or parsed.password or parsed.query
            or parsed.fragment or parsed.path not in ('','/')):
        raise sqlite3.OperationalError('ERP_DATABASE_URL must be a secure libsql or HTTPS database URL')
    if not token:
        raise sqlite3.OperationalError('ERP_DATABASE_TOKEN is required')
    return url, token
