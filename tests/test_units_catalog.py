"""Unit seeding preserves references and company-provided translations."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database import Connection
from units_catalog import BUILTIN_UNITS, seed_units


class UnitsCatalogCase(unittest.TestCase):
    def databases(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        sqlite = sqlite3.connect(':memory:')
        self.addCleanup(sqlite.close)
        native = Connection(Path(directory.name) / 'units.sqlite3')
        self.addCleanup(native.close)
        return (('sqlite', sqlite), ('libsql', native))

    def initialize(self, db):
        db.execute('CREATE TABLE units(id INTEGER PRIMARY KEY,name TEXT,code TEXT,name_en TEXT)')
        db.execute("CREATE UNIQUE INDEX unit_code ON units(code) WHERE code IS NOT NULL AND code<>''")

    def test_bilingual_catalog_is_complete_and_idempotent_for_both_drivers(self):
        self.assertGreaterEqual(len(BUILTIN_UNITS), 50)
        self.assertEqual(len({unit['code'] for unit in BUILTIN_UNITS}), len(BUILTIN_UNITS))
        self.assertTrue(all(unit['name'] and unit['name_en'] for unit in BUILTIN_UNITS))
        required = {'piece', 'square_meter', 'cubic_meter', 'kilogram', 'liter', 'milliliter',
                    'visit', 'session', 'trap', 'bait_station', 'room', 'floor', 'feddan'}
        self.assertTrue(required <= {unit['code'] for unit in BUILTIN_UNITS})
        for driver, db in self.databases():
            with self.subTest(driver=driver):
                self.initialize(db)
                seed_units(db)
                before = [tuple(row) if not isinstance(row, dict) else tuple(row.values())
                          for row in db.execute('SELECT id,name,code,name_en FROM units ORDER BY id')]
                seed_units(db)
                after = [tuple(row) if not isinstance(row, dict) else tuple(row.values())
                         for row in db.execute('SELECT id,name,code,name_en FROM units ORDER BY id')]
                self.assertEqual(before, after)
                self.assertEqual(len(after), len(BUILTIN_UNITS))

    def test_migrating_existing_piece_preserves_its_id_and_custom_units(self):
        for driver, db in self.databases():
            with self.subTest(driver=driver):
                self.initialize(db)
                db.execute("INSERT INTO units(id,name) VALUES(71,'قطعة')")
                db.execute("INSERT INTO units(id,name,name_en) VALUES(98,'وحدة خاصة بالشركة','Custom company unit')")
                seed_units(db)
                piece = db.execute("SELECT id,code,name_en FROM units WHERE code='piece'").fetchone()
                self.assertEqual(tuple(piece.values()) if isinstance(piece, dict) else tuple(piece),
                                 (71, 'piece', 'Piece'))
                custom = db.execute('SELECT name,name_en,code FROM units WHERE id=98').fetchone()
                self.assertEqual(tuple(custom.values()) if isinstance(custom, dict) else tuple(custom),
                                 ('وحدة خاصة بالشركة', 'Custom company unit', None))

    def test_custom_english_and_renamed_builtins_are_never_overwritten(self):
        for driver, db in self.databases():
            with self.subTest(driver=driver):
                self.initialize(db)
                db.execute("INSERT INTO units(id,name,name_en) VALUES(3,'قطعة','Single custom part')")
                db.execute("INSERT INTO units(id,name,code,name_en) VALUES(4,'تسمية معدلة','liter','Company liquid unit')")
                db.execute("INSERT INTO units(id,name,code,name_en) VALUES(5,'زيارة خاصة','visit',NULL)")
                seed_units(db)
                seed_units(db)
                self.assertEqual(db.execute('SELECT name_en FROM units WHERE id=3').fetchone()[0], 'Single custom part')
                self.assertEqual(db.execute('SELECT name FROM units WHERE id=4').fetchone()[0], 'تسمية معدلة')
                self.assertEqual(db.execute('SELECT name_en FROM units WHERE id=4').fetchone()[0], 'Company liquid unit')
                self.assertIsNone(db.execute('SELECT name_en FROM units WHERE id=5').fetchone()[0])

    def test_seeding_respects_callers_transaction_and_can_roll_back(self):
        for driver, db in self.databases():
            with self.subTest(driver=driver):
                self.initialize(db)
                db.commit()
                db.execute('BEGIN IMMEDIATE')
                seed_units(db)
                db.rollback()
                self.assertEqual(db.execute('SELECT COUNT(*) FROM units').fetchone()[0], 0)
