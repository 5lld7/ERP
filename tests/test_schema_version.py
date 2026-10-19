"""Regression checks for Turso's read-only PRAGMA user_version policy."""
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
import erp
from api import index


class TursoPolicyConnection:
    """Retain real SQL and transactions while reproducing the production policy."""

    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, parameters=()):
        if re.match(r'\s*PRAGMA\s+(?:main\.)?user_version\s*=', statement, re.I):
            raise sqlite3.OperationalError('SQL not allowed statement: PRAGMA user_version')
        return self.connection.execute(statement, parameters)

    def __getattr__(self, name):
        return getattr(self.connection, name)


class SchemaVersionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'company.sqlite3'
        self.old_ready = index._ready
        index._ready = False
        self.environment = patch.dict(os.environ, {
            'ERP_DATABASE_URL': '', 'ERP_DATABASE_TOKEN': '', 'VERCEL': '',
        })
        self.environment.start()

    def tearDown(self):
        index._ready = self.old_ready
        self.environment.stop()
        self.tmp.cleanup()

    def production_connection(self, path=None):
        # Explicit local paths prevent any use of real company credentials.
        return TursoPolicyConnection(self.real_connect(path or self.path))

    def production(self):
        self.real_connect = erp.connect
        return patch.object(erp, 'connect', side_effect=self.production_connection)

    def make_legacy(self, version=2):
        erp.initialize(self.path)
        db = sqlite3.connect(self.path)
        try:
            db.execute('DROP TABLE erp_metadata')
            db.execute(f'PRAGMA user_version={int(version)}')
            db.execute("INSERT INTO customers(id,name,classification) VALUES(700,'Existing customer','عادي')")
            db.commit()
        finally:
            db.close()

    def test_fresh_start_and_cold_restart_use_turso_compatible_version_storage(self):
        with self.production(), patch.dict(os.environ, {
            'VERCEL': '1', 'ERP_DATABASE_URL': 'libsql://test.invalid',
            'ERP_DATABASE_TOKEN': 'test-only', 'ERP_COOKIE_SECURE': '1',
        }):
            index.ensure_ready()
            db = erp.connect()
            try:
                self.assertEqual(database.read_schema_version(db), erp.SCHEMA_VERSION)
                db.execute("INSERT INTO customers(id,name) VALUES(700,'Preserved after restart')")
                db.commit()
            finally:
                db.close()
            index._ready = False
            with patch.object(erp, 'initialize', wraps=erp.initialize) as initialize:
                index.ensure_ready()
                initialize.assert_not_called()
            db = erp.connect()
            try:
                self.assertEqual(db.execute('SELECT name FROM customers WHERE id=700').fetchone()[0],
                                 'Preserved after restart')
            finally:
                db.close()

    def test_legacy_version_two_migrates_without_losing_company_data(self):
        self.make_legacy()
        with self.production():
            index.ensure_ready()
        db = self.real_connect(self.path)
        try:
            self.assertEqual(database.read_schema_version(db), erp.SCHEMA_VERSION)
            self.assertEqual(db.execute("SELECT value FROM erp_metadata WHERE key='schema_version'").fetchone()[0],
                             erp.SCHEMA_VERSION)
            self.assertEqual(db.execute('SELECT name FROM customers WHERE id=700').fetchone()[0],
                             'Existing customer')
        finally:
            db.close()

    def test_future_versions_are_refused_without_downgrading_or_changing_data(self):
        self.make_legacy(erp.SCHEMA_VERSION + 1)
        for metadata in (False, True):
            with self.subTest(metadata=metadata):
                if metadata:
                    db = erp.connect(self.path)
                    database.write_schema_version(db, erp.SCHEMA_VERSION + 2)
                    db.commit()
                    db.close()
                with self.production():
                    with self.assertRaises(database.DatabaseUnavailable) as caught:
                        index.ensure_ready()
                    self.assertEqual(caught.exception.code, 'DATABASE_VERSION')
                    with self.assertRaises(sqlite3.Error):
                        erp.initialize()
                db = self.real_connect(self.path)
                try:
                    self.assertEqual(database.read_schema_version(db), erp.SCHEMA_VERSION + (2 if metadata else 1))
                    self.assertEqual(db.execute('SELECT name FROM customers WHERE id=700').fetchone()[0],
                                     'Existing customer')
                    self.assertFalse(index._ready)
                finally:
                    db.close()

    def test_failed_version_persistence_rolls_back_initialization(self):
        write_version = database.write_schema_version

        def fail_after_write(db, version):
            write_version(db, version)
            raise sqlite3.OperationalError('Simulated transaction failure')

        with self.production(), patch.object(database, 'write_schema_version', side_effect=fail_after_write):
            with self.assertRaises(sqlite3.OperationalError):
                erp.initialize()
        db = sqlite3.connect(self.path)
        try:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])
        finally:
            db.close()

    def test_native_backup_and_restore_preserve_metadata_without_pragma_assignment(self):
        self.make_legacy()
        erp.initialize(self.path)
        backup_path = Path(self.tmp.name) / 'backup.sqlite3'
        source = TursoPolicyConnection(database.Connection(self.path))
        target = TursoPolicyConnection(sqlite3.connect(backup_path))
        try:
            # Call the adapter implementation with policy enforcement on both ends.
            database.Connection.backup(source, target)
            self.assertEqual(database.read_schema_version(target), erp.SCHEMA_VERSION)
        finally:
            target.close()
            source.close()
        erp.initialize(backup_path)
        restored = erp.connect(backup_path)
        try:
            self.assertEqual(database.read_schema_version(restored), erp.SCHEMA_VERSION)
            self.assertEqual(restored.execute('SELECT name FROM customers WHERE id=700').fetchone()[0],
                             'Existing customer')
        finally:
            restored.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
