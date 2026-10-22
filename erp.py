"""Arabic ERP business layer. Money is stored in integer minor units (piastres)."""
from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('ERP_DATA_DIR', '/tmp/erp' if os.environ.get('VERCEL') else ROOT / '.local')).resolve()
DB_PATH = DATA / 'erp.sqlite3'
SCHEMA_VERSION = 7


class BusinessError(Exception):
    pass


def money(value):
    try:
        n = Decimal(str(value or 0))
        if not n.is_finite() or abs(n) > Decimal('1000000000'):
            raise BusinessError('القيمة المالية خارج النطاق المسموح')
        return int((n * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        raise BusinessError('أدخل قيمة مالية صحيحة') from None


def amount(n):
    return float(Decimal(n or 0) / 100)


def rounded(value):
    return int(Decimal(str(value)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))


def today():
    return dt.date.today().isoformat()


def valid_date(value):
    try:
        return dt.date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        raise BusinessError('أدخل تاريخًا صحيحًا') from None


def number(value, positive=False):
    try:
        n = Decimal(str(value))
        if not n.is_finite() or abs(n) > Decimal('1000000000') or (positive and n <= 0):
            raise ValueError
        result=float(n.quantize(Decimal('.001'), rounding=ROUND_HALF_UP))
        if positive and result<=0:
            raise ValueError
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise BusinessError('أدخل كمية أو رقمًا صحيحًا ضمن النطاق المسموح') from None


def field(key, label, kind='text', required=False, **kwargs):
    return dict(key=key, label=label, type=kind, required=required, **kwargs)


# These definitions are also the client-side form contract. SQL identifiers are
# drawn exclusively from this allowlist, never from request-supplied SQL.
RESOURCES = {
    'branches': dict(label='الفروع', module='inventory', fields=[field('name', 'اسم الفرع', required=True), field('address', 'العنوان'), field('phone', 'الهاتف')]),
    'warehouses': dict(label='المخازن', module='inventory', fields=[field('name', 'اسم المخزن', required=True), field('branch_id', 'الفرع', 'ref', True, ref='branches'), field('address', 'العنوان')]),
    'categories': dict(label='تصنيفات الأصناف', module='inventory', fields=[field('name', 'اسم التصنيف', required=True)]),
    'service_types': dict(label='أنواع الخدمات', module='inventory', fields=[field('name', 'اسم نوع الخدمة', required=True), field('name_en', 'اسم نوع الخدمة بالإنجليزية')]),
    'units': dict(label='وحدات القياس', module='inventory', fields=[field('name', 'الوحدة', required=True), field('name_en', 'اسم الوحدة بالإنجليزية')]),
    'products': dict(label='الأصناف', module='inventory', fields=[field('name', 'اسم الصنف', required=True), field('sku', 'كود الصنف', required=True), field('barcode', 'الباركود'), field('category_id', 'التصنيف', 'ref', ref='categories'), field('unit_id', 'الوحدة', 'ref', True, ref='units'), field('cost', 'تكلفة الشراء', 'money', True), field('price', 'سعر البيع', 'money', True), field('min_stock', 'حد إعادة الطلب', 'number'), field('expiry_date', 'تاريخ الصلاحية', 'date')]),
    'services': dict(label='الخدمات', module='inventory', fields=[field('name', 'اسم الخدمة', required=True), field('sku', 'كود الخدمة', required=True), field('service_category', 'نوع الخدمة', 'select', options=[]), field('unit_id', 'الوحدة', 'ref', True, ref='units'), field('price', 'سعر الخدمة', 'money', True), field('service_method', 'طريقة عمل الخدمة', 'textarea')]),
    'appointments': dict(label='حجز موعد', module='sales', fields=[field('customer_name', 'اسم العميل', required=True), field('date', 'تاريخ الموعد', 'date', True), field('time', 'وقت الموعد', 'time', True), field('address', 'العنوان', 'textarea', True), field('phone', 'رقم التليفون', required=True), field('service_status', 'حالة الخدمة', 'select', True, options=['تنفيذ', 'معاينة', 'متابعة', 'إعادة العمل']), field('service_id', 'الخدمة', 'ref', ref='services'), field('site_type', 'نوع الموقع', 'select', True, options=['شقة', 'فيلا', 'تاون فيلا', 'منزل', 'قطعة أرض', 'مبنى حكومي', 'مبنى تجاري'])]),
    'customers': dict(label='العملاء', module='sales', fields=[field('name', 'اسم العميل', required=True), field('phone', 'الهاتف'), field('email', 'البريد الإلكتروني', 'email'), field('address', 'العنوان'), field('tax_number', 'الرقم الضريبي'), field('classification', 'التصنيف', 'select', options=['عادي', 'مميز', 'مؤسسة']), field('credit_limit', 'حد الائتمان (صفر = بدون حد)', 'money'), field('payment_terms', 'شروط الدفع بالأيام', 'number')]),
    'suppliers': dict(label='الموردون', module='accounting', fields=[field('name', 'اسم المورد', required=True), field('phone', 'الهاتف'), field('email', 'البريد الإلكتروني', 'email'), field('address', 'العنوان'), field('tax_number', 'الرقم الضريبي'), field('payment_terms', 'شروط الدفع بالأيام', 'number')]),
    'departments': dict(label='الإدارات والأقسام', module='hr', fields=[field('name', 'اسم الإدارة', required=True)]),
    'jobs': dict(label='الوظائف', module='hr', fields=[field('name', 'المسمى الوظيفي', required=True)]),
    'employees': dict(label='الموظفون', module='hr', fields=[field('name', 'اسم الموظف', required=True), field('code', 'الكود الوظيفي', required=True), field('national_id', 'رقم البطاقة أو الإقامة'), field('nationality', 'الجنسية'), field('residency_expiry', 'تاريخ انتهاء الإقامة', 'date'), field('passport_expiry', 'تاريخ انتهاء جواز السفر', 'date'), field('driving_license_expiry', 'تاريخ انتهاء رخصة القيادة', 'date'), field('phone', 'الهاتف'), field('department_id', 'الإدارة', 'ref', ref='departments'), field('job_id', 'الوظيفة', 'ref', ref='jobs'), field('branch_id', 'الفرع', 'ref', True, ref='branches'), field('hire_date', 'تاريخ التعيين', 'date', True), field('contract_end', 'نهاية العقد', 'date'), field('salary', 'الراتب الأساسي', 'money', True), field('allowance', 'البدلات الشهرية', 'money'), field('overtime_rate', 'أجر الساعة الإضافية', 'money'), field('leave_balance', 'رصيد الإجازات السنوي', 'number'), field('status', 'حالة الموظف', 'select', True, options=['نشط', 'موقوف', 'منتهية'])]),
    'attendance': dict(label='الحضور والانصراف', module='hr', fields=[field('employee_id', 'الموظف', 'ref', True, ref='employees'), field('date', 'التاريخ', 'date', True), field('check_in', 'وقت الحضور', 'time'), field('check_out', 'وقت الانصراف', 'time'), field('status', 'الحالة', 'select', True, options=['حاضر', 'غائب', 'إجازة']), field('overtime_hours', 'ساعات إضافية', 'number'), field('deduction', 'خصم', 'money'), field('note', 'ملاحظات')]),
    'employee_adjustments': dict(label='المكافآت والخصومات', module='hr', fields=[field('employee_id', 'الموظف', 'ref', True, ref='employees'), field('date', 'التاريخ', 'date', True), field('type', 'نوع التسوية', 'select', True, options=['مكافأة', 'خصم']), field('amount', 'المبلغ', 'money', True), field('note', 'البيان')]),
    'leaves': dict(label='طلبات الإجازة', module='hr', fields=[field('employee_id', 'الموظف', 'ref', True, ref='employees'), field('start_date', 'من تاريخ', 'date', True), field('end_date', 'إلى تاريخ', 'date', True), field('type', 'نوع الإجازة', 'select', True, options=['سنوية', 'مرضية', 'بدون راتب']), field('reason', 'السبب'), field('status', 'الحالة', 'select', True, options=['قيد المراجعة', 'معتمدة', 'مرفوضة'])]),
    'price_lists': dict(label='قوائم الأسعار والعروض', module='sales', fields=[field('name', 'اسم القائمة أو العرض', required=True), field('product_id', 'الصنف', 'ref', True, ref='products'), field('customer_id', 'عميل محدد (اختياري)', 'ref', ref='customers'), field('price', 'السعر', 'money', True), field('start_date', 'بداية العرض', 'date', True), field('end_date', 'نهاية العرض', 'date', True)]),
    'assets': dict(label='الأصول الثابتة', module='accounting', fields=[field('name', 'اسم الأصل', required=True), field('code', 'كود الأصل', required=True), field('purchase_date', 'تاريخ الشراء', 'date', True), field('cost', 'التكلفة', 'money', True), field('salvage', 'القيمة التخريدية', 'money'), field('life_months', 'العمر الإنتاجي بالشهور', 'number', True), field('branch_id', 'الفرع', 'ref', True, ref='branches')]),
    'accounts': dict(label='شجرة الحسابات', module='accounting', fields=[field('code', 'رقم الحساب', required=True), field('name', 'اسم الحساب', required=True), field('type', 'نوع الحساب', 'select', True, options=['أصول', 'التزامات', 'حقوق ملكية', 'إيرادات', 'مصروفات']), field('parent_id', 'الحساب الأب', 'ref', ref='accounts')]),
}

SQL_TYPES = {'money': 'INTEGER NOT NULL DEFAULT 0', 'number': 'REAL NOT NULL DEFAULT 0', 'ref': 'INTEGER', 'text': 'TEXT', 'date': 'TEXT', 'email': 'TEXT', 'time': 'TEXT', 'select': 'TEXT', 'textarea': 'TEXT'}

SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), action TEXT NOT NULL, entity TEXT NOT NULL, entity_id INTEGER, detail TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY, number TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, date TEXT NOT NULL, due_date TEXT, customer_id INTEGER REFERENCES customers(id), supplier_id INTEGER REFERENCES suppliers(id), warehouse_id INTEGER REFERENCES warehouses(id), target_warehouse_id INTEGER REFERENCES warehouses(id), source_id INTEGER REFERENCES documents(id), status TEXT NOT NULL DEFAULT 'draft', subtotal INTEGER NOT NULL, discount INTEGER NOT NULL DEFAULT 0, tax_rate REAL NOT NULL DEFAULT 0, tax INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL, paid INTEGER NOT NULL DEFAULT 0, payment_method TEXT NOT NULL DEFAULT 'cash', note TEXT, created_by INTEGER REFERENCES users(id), created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS document_lines (id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id), product_id INTEGER NOT NULL REFERENCES products(id), quantity REAL NOT NULL, price INTEGER NOT NULL, total INTEGER NOT NULL, cost INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS stock (warehouse_id INTEGER NOT NULL REFERENCES warehouses(id), product_id INTEGER NOT NULL REFERENCES products(id), quantity REAL NOT NULL DEFAULT 0, avg_cost INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(warehouse_id,product_id));
CREATE TABLE IF NOT EXISTS stock_moves (id INTEGER PRIMARY KEY, document_id INTEGER REFERENCES documents(id), warehouse_id INTEGER NOT NULL REFERENCES warehouses(id), product_id INTEGER NOT NULL REFERENCES products(id), quantity REAL NOT NULL, cost INTEGER NOT NULL, date TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY, date TEXT NOT NULL, description TEXT NOT NULL, source_type TEXT, source_id INTEGER, created_by INTEGER REFERENCES users(id), created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS journal_lines (id INTEGER PRIMARY KEY, journal_id INTEGER NOT NULL REFERENCES journal(id), account_id INTEGER NOT NULL REFERENCES accounts(id), debit INTEGER NOT NULL DEFAULT 0 CHECK(debit>=0), credit INTEGER NOT NULL DEFAULT 0 CHECK(credit>=0), customer_id INTEGER REFERENCES customers(id), supplier_id INTEGER REFERENCES suppliers(id));
CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY, date TEXT NOT NULL, direction TEXT NOT NULL, document_id INTEGER REFERENCES documents(id), customer_id INTEGER REFERENCES customers(id), supplier_id INTEGER REFERENCES suppliers(id), account_id INTEGER REFERENCES accounts(id), amount INTEGER NOT NULL CHECK(amount>0), method TEXT NOT NULL, note TEXT, created_by INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS payroll (id INTEGER PRIMARY KEY, month TEXT NOT NULL, branch_id INTEGER REFERENCES branches(id), status TEXT NOT NULL, total INTEGER NOT NULL, created_by INTEGER REFERENCES users(id), created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS payroll_lines (id INTEGER PRIMARY KEY, payroll_id INTEGER NOT NULL REFERENCES payroll(id), employee_id INTEGER NOT NULL REFERENCES employees(id), month TEXT NOT NULL, basic INTEGER NOT NULL, allowance INTEGER NOT NULL, overtime INTEGER NOT NULL, bonus INTEGER NOT NULL, deduction INTEGER NOT NULL, absence INTEGER NOT NULL, loan INTEGER NOT NULL, net INTEGER NOT NULL, UNIQUE(employee_id,month));
CREATE TABLE IF NOT EXISTS loans (id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id), date TEXT NOT NULL, amount INTEGER NOT NULL, installment INTEGER NOT NULL, balance INTEGER NOT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS depreciation (id INTEGER PRIMARY KEY, asset_id INTEGER NOT NULL REFERENCES assets(id), month TEXT NOT NULL, amount INTEGER NOT NULL, UNIQUE(asset_id,month));
CREATE TABLE IF NOT EXISTS employee_files (id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id), name TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL, content BLOB NOT NULL, uploaded_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS auth_attempts (key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, started_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS document_shares (id INTEGER PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE, pdf BLOB NOT NULL, language TEXT NOT NULL, currency TEXT NOT NULL, expires_at INTEGER NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id), created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),event_key TEXT NOT NULL,kind TEXT NOT NULL,title TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',link TEXT NOT NULL,created_at INTEGER NOT NULL,read_at INTEGER,active INTEGER NOT NULL DEFAULT 1,UNIQUE(user_id,event_key));
CREATE INDEX IF NOT EXISTS notifications_user_unread ON notifications(user_id,read_at,id);
CREATE INDEX IF NOT EXISTS share_expiry ON document_shares(expires_at);
CREATE INDEX IF NOT EXISTS doc_kind_date ON documents(kind,date);
CREATE INDEX IF NOT EXISTS move_lookup ON stock_moves(warehouse_id,product_id,date);
CREATE INDEX IF NOT EXISTS journal_account ON journal_lines(account_id);
CREATE INDEX IF NOT EXISTS audit_time ON audit(created_at);
'''

CHART = [
    ('1000', 'الأصول', 'أصول', None), ('1100', 'الصندوق', 'أصول', '1000'), ('1110', 'البنك', 'أصول', '1000'), ('1200', 'العملاء', 'أصول', '1000'), ('1300', 'المخزون', 'أصول', '1000'), ('1400', 'ضريبة مدخلات', 'أصول', '1000'), ('1500', 'سلف الموظفين', 'أصول', '1000'), ('1600', 'الأصول الثابتة', 'أصول', '1000'),
    ('2000', 'الالتزامات', 'التزامات', None), ('2100', 'الموردون', 'التزامات', '2000'), ('2200', 'ضريبة مخرجات', 'التزامات', '2000'), ('2300', 'الرواتب المستحقة', 'التزامات', '2000'), ('2400', 'مجمع الإهلاك', 'أصول', '1000'),
    ('3000', 'حقوق الملكية', 'حقوق ملكية', None), ('3100', 'رأس المال والأرصدة الافتتاحية', 'حقوق ملكية', '3000'),
    ('4000', 'الإيرادات', 'إيرادات', None), ('4100', 'إيرادات المبيعات', 'إيرادات', '4000'), ('4200', 'إيرادات أخرى', 'إيرادات', '4000'),
    ('5000', 'المصروفات', 'مصروفات', None), ('5100', 'تكلفة البضاعة المباعة', 'مصروفات', '5000'), ('5200', 'الرواتب والأجور', 'مصروفات', '5000'), ('5300', 'مصروفات تشغيلية', 'مصروفات', '5000'), ('5400', 'مصروف الإهلاك', 'مصروفات', '5000'), ('5500', 'فروق الجرد والتالف', 'مصروفات', '5000'),
]
KINDS = {
    'purchase': ['فاتورة مشتريات', 'accounting', 'PUR'], 'purchase_return': ['مرتجع مشتريات', 'accounting', 'PRT'],
    'purchase_order': ['أمر شراء', 'inventory', 'PO'], 'receipt': ['استلام أصناف', 'inventory', 'REC'],
    'sale': ['فاتورة مبيعات', 'sales', 'SAL'], 'sale_return': ['مرتجع مبيعات', 'sales', 'SRT'],
    'inspection': ['عرض سعر', 'sales', 'INS'], 'transfer': ['تحويل بين المخازن', 'inventory', 'TRF'],
    'issue': ['صرف / تالف', 'inventory', 'ISS'], 'adjustment': ['جرد وتسوية مخزون', 'inventory', 'ADJ'],
}
ROLES = {'admin': 'مدير النظام', 'accounting': 'محاسب', 'inventory': 'مسؤول المخزن', 'sales': 'مسؤول المبيعات', 'hr': 'الموارد البشرية', 'viewer': 'مشاهدة عامة', 'technician': 'فني'}


def connect(path=None):
    from database import Connection, remote_settings
    remote = remote_settings() if path is None else None
    if remote:
        conn = Connection(remote[0], remote[1])
        conn.execute('PRAGMA foreign_keys=ON')
        return conn
    if path is None and os.environ.get('VERCEL'):
        raise sqlite3.OperationalError('Vercel requires a durable remote database')
    path = path or DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if os.environ.get('ERP_DB_DRIVER') == 'libsql':
        conn = Connection(path)
    else:
        conn = sqlite3.connect(str(path), timeout=20)
        conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=20000')
    return conn


def initialize(path=None):
    from database import read_schema_version, write_schema_version
    db = connect(path)
    try:
        db.execute('BEGIN IMMEDIATE')
        if read_schema_version(db) > SCHEMA_VERSION:
            raise sqlite3.OperationalError('Database schema is newer than this application')
        _initialize_schema(db)
        write_schema_version(db, SCHEMA_VERSION)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _initialize_schema(db):
    had_service_types = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='service_types'").fetchone()
    for name, spec in RESOURCES.items():
        if name == 'services':
            continue
        columns = ['id INTEGER PRIMARY KEY']
        for f in spec['fields']:
            col = f'{f["key"]} {SQL_TYPES[f["type"]]}'
            if f['type'] == 'ref':
                col += f' REFERENCES {resource_table(f["ref"])}(id)'
            columns.append(col)
        columns.append('created_at TEXT DEFAULT CURRENT_TIMESTAMP')
        db.execute(f'CREATE TABLE IF NOT EXISTS {name} ({",".join(columns)})')
        existing = {row['name'] for row in db.execute(f'PRAGMA table_info({name})')}
        for f in spec['fields']:
            if f['key'] not in existing:
                definition = SQL_TYPES[f['type']]
                if f['type'] == 'ref':
                    definition += f' REFERENCES {resource_table(f["ref"])}(id)'
                db.execute(f'ALTER TABLE {name} ADD COLUMN {f["key"]} {definition}')
    for statement in SCHEMA.split(';'):
        if statement.strip():
            db.execute(statement)
    for table, additions in {
        'products': [('item_type', "TEXT NOT NULL DEFAULT 'product'"), ('service_method', "TEXT NOT NULL DEFAULT ''"), ('service_category', "TEXT NOT NULL DEFAULT ''")],
        'units': [('code', 'TEXT')],
        'document_lines': [('service_method', "TEXT NOT NULL DEFAULT ''")],
        'documents': [('service_activity', "TEXT NOT NULL DEFAULT ''")],
        'appointments': [('status', "TEXT NOT NULL DEFAULT 'scheduled'"),
                         ('assigned_employee_id', 'INTEGER REFERENCES employees(id)'),
                         ('quotation_id', 'INTEGER REFERENCES documents(id)'),
                         ('invoice_id', 'INTEGER REFERENCES documents(id)'),
                         ('completed_at', 'TEXT'), ('updated_at', 'TEXT')],
    }.items():
        existing = {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}
        for column, definition in additions:
            if column not in existing:
                db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    # Seed once so deleted or renamed defaults never return on restart.
    if not had_service_types:
        db.execute("INSERT INTO service_types(name,name_en) VALUES('مكافحة حشرات','Pest control'),('تنظيف','Cleaning')")
        db.execute("INSERT INTO service_types(name,name_en) SELECT DISTINCT service_category,'' FROM products WHERE item_type='service' AND service_category IS NOT NULL AND TRIM(service_category)<>'' AND service_category NOT IN (SELECT name FROM service_types)")
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS service_type_name_unique ON service_types(LOWER(name))')
    # Preserve the original booking purpose without overwriting later edits.
    appointment_columns = {r['name'] for r in db.execute('PRAGMA table_info(appointments)')}
    if 'service_type' in appointment_columns:
        db.execute("UPDATE appointments SET service_status=CASE WHEN service_type='إعادة عمل' THEN 'إعادة العمل' ELSE service_type END WHERE (service_status IS NULL OR service_status='') AND service_type IN ('تنفيذ','معاينة','متابعة','إعادة عمل')")
    db.execute('CREATE INDEX IF NOT EXISTS appointments_day_status ON appointments(date,status,time)')
    db.execute('CREATE INDEX IF NOT EXISTS appointments_assignee ON appointments(assigned_employee_id,date)')
    db.execute('CREATE TABLE IF NOT EXISTS service_activity_accounts (activity TEXT PRIMARY KEY, account_id INTEGER NOT NULL UNIQUE REFERENCES accounts(id))')
    db.execute("UPDATE customers SET classification='مؤسسة' WHERE classification='جملة'")
    doc_columns={r['name'] for r in db.execute('PRAGMA table_info(documents)')}
    for column,definition in [('progress',"TEXT NOT NULL DEFAULT 'جديدة'"),('appointment_date','TEXT'),('location','TEXT')]:
        if column not in doc_columns:
            db.execute(f'ALTER TABLE documents ADD COLUMN {column} {definition}')
    for table, column in [('products','sku'), ('products','barcode'), ('employees','code'), ('accounts','code'), ('assets','code')]:
        db.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS unique_{table}_{column} ON {table}({column}) WHERE {column} IS NOT NULL AND {column}<>''")
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS attendance_daily ON attendance(employee_id,date)')
    for code, name, kind, parent in CHART:
        parent_id = db.execute('SELECT id FROM accounts WHERE code=?', (parent,)).fetchone() if parent else None
        db.execute('INSERT INTO accounts(code,name,type,parent_id) SELECT ?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM accounts WHERE code=?)', (code,name,kind,parent_id[0] if parent_id else None,code))
    db.execute("UPDATE accounts SET type='أصول',parent_id=(SELECT id FROM accounts WHERE code='1000') WHERE code='2400' AND name='مجمع الإهلاك' AND type='التزامات'")
    defaults = {'company_name': 'شركتي', 'currency': 'EGP', 'tax_rate': 14, 'company_address': '', 'company_phone': '', 'tax_number': '', 'leave_days': 21, 'work_hours': 8, 'discount_limit': 100}
    for key, value in defaults.items():
        db.execute('INSERT OR IGNORE INTO settings VALUES(?,?)', (key,json.dumps(value,ensure_ascii=False)))
    if not db.execute('SELECT 1 FROM branches LIMIT 1').fetchone():
        db.execute("INSERT INTO branches(name) VALUES('الفرع الرئيسي')")
        branch = db.execute('SELECT id FROM branches LIMIT 1').fetchone()[0]
        db.execute("INSERT INTO warehouses(name,branch_id) VALUES('المخزن الرئيسي',?)", (branch,))
    from units_catalog import seed_units
    seed_units(db)


@contextmanager
def transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise


def audit(db, uid, action, entity, eid=None, detail=''):
    db.execute('INSERT INTO audit(user_id,action,entity,entity_id,detail) VALUES(?,?,?,?,?)', (uid,action,entity,eid,detail))


def password_hash(password):
    if not isinstance(password, str) or len(password) < 10 or len(password) > 256:
        raise BusinessError('كلمة المرور يجب أن تكون بين 10 و256 حرفًا')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),600000).hex()
    return f'pbkdf2_sha256${salt}${digest}'


def password_matches(password, encoded):
    if not isinstance(password,str) or not 1<=len(password)<=256:
        return False
    try:
        _, salt, expected = encoded.split('$')
        actual = hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),600000).hex()
        return secrets.compare_digest(actual,expected)
    except (ValueError, AttributeError):
        return False


def settings(db):
    return {r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM settings')}


def can(user, module, write=False):
    return user['role'] == 'admin' or (module!='admin' and ((user['role'] == 'viewer' and not write) or user['role'] == module or (user['role']=='technician' and module=='sales')))


def document_allowed(user, kind, write=False):
    return kind in KINDS and (user['role']!='technician' or kind=='inspection') and can(user,KINDS[kind][1],write)


def require(user, module, write=False):
    if not can(user,module,write):
        raise PermissionError('ليس لديك صلاحية لتنفيذ هذه العملية')


def serialize_row(row, spec):
    result = dict(row)
    for f in spec['fields']:
        if f['type'] == 'money':
            result[f['key']] = amount(result[f['key']])
    return result


def resource_table(name):
    if name not in RESOURCES:
        raise BusinessError('القسم غير موجود')
    return 'products' if name=='services' else name


def resource_filter(name):
    resource_table(name)
    if name in ('products','services'):
        return "COALESCE(item_type,'product')='" + ('service' if name=='services' else 'product') + "'"
    return '1=1'


def list_resource(db, name):
    if name == 'appointments':
        from appointments import list_appointments
        return list_appointments(db)
    return [serialize_row(r,RESOURCES[name]) for r in db.execute(f'SELECT * FROM {resource_table(name)} WHERE {resource_filter(name)} ORDER BY id DESC')]


def save_resource(db, name, data, uid, eid=None):
    spec = RESOURCES[name]
    table, predicate = resource_table(name), resource_filter(name)
    if name == 'appointments':
        data = dict(data)
        if not data.get('service_status') and data.get('service_type') in ('تنفيذ','معاينة','متابعة','إعادة عمل'):
            data['service_status'] = 'إعادة العمل' if data['service_type']=='إعادة عمل' else data['service_type']
        if not data.get('service_id') and not data.get('service_type'):
            raise BusinessError('اختر الخدمة من كتالوج الخدمات')
    if name == 'appointments' and eid:
        from appointments import get_appointment
        old_appointment = get_appointment(db, eid)
        if old_appointment['quotation_id'] or old_appointment['invoice_id']:
            raise BusinessError('الموعد مرتبط بعرض سعر أو فاتورة؛ لا يمكن تعديل بياناته')
    values = {}
    for f in spec['fields']:
        key, kind = f['key'], f['type']
        value = data.get(key)
        if f['required'] and (value is None or value == ''):
            raise BusinessError(f'حقل {f["label"]} مطلوب')
        if kind == 'money':
            value = money(value)
            if value < 0:
                raise BusinessError('القيم المالية لا تقبل السالب')
        elif kind == 'number':
            value = number(value or 0)
            if value < 0:
                raise BusinessError('القيمة لا تقبل السالب')
        elif kind == 'ref':
            value = int(value) if value else None
            ref_table = resource_table(f['ref'])
            ref_filter = resource_filter('services') if f['ref']=='services' else '1=1'
            if value and not db.execute(f'SELECT 1 FROM {ref_table} WHERE id=? AND {ref_filter}',(value,)).fetchone():
                raise BusinessError('العنصر المرتبط غير موجود')
        elif kind == 'date':
            value = valid_date(value) if value else None
        else:
            value = str(value or '').strip()[:10000 if key=='service_method' else 2000]
            if f.get('options') and value not in f['options']:
                raise BusinessError(f'اختر قيمة صحيحة لحقل {f["label"]}')
            if kind == 'time' and value:
                try:
                    dt.time.fromisoformat(value)
                except ValueError:
                    raise BusinessError('وقت غير صحيح') from None
        values[key] = value
    if name == 'services' and values.get('service_category'):
        if not db.execute('SELECT 1 FROM service_types WHERE name=?',(values['service_category'],)).fetchone():
            raise BusinessError('اختر نوع خدمة مسجلًا من أنواع الخدمات')
    if name == 'service_types':
        if not values['name'] or len(values['name'])>120:
            raise BusinessError('اسم نوع الخدمة يجب أن يكون من 1 إلى 120 حرفًا')
        if db.execute('SELECT 1 FROM service_types WHERE LOWER(name)=LOWER(?) AND id<>?',(values['name'],eid or 0)).fetchone():
            raise BusinessError('نوع الخدمة موجود بالفعل')
    if name == 'assets' and (values['life_months'] < 1 or values['life_months'] != int(values['life_months']) or values['salvage'] > values['cost']):
        raise BusinessError('راجع عمر الأصل وقيمته التخريدية')
    if name == 'accounts' and eid and values.get('parent_id'):
        ancestor, visited = values['parent_id'], {eid}
        while ancestor:
            if ancestor in visited:
                raise BusinessError('لا يمكن تكوين حلقة في شجرة الحسابات')
            visited.add(ancestor)
            row = db.execute('SELECT parent_id FROM accounts WHERE id=?',(ancestor,)).fetchone()
            ancestor = row[0] if row else None
    if name == 'accounts' and eid:
        old = db.execute('SELECT code,type FROM accounts WHERE id=?',(eid,)).fetchone()
        if old and old['code'] in {c[0] for c in CHART} and (values['code'] != old['code'] or values['type'] != old['type']):
            raise BusinessError('رموز وأنواع حسابات النظام ثابتة لحماية الترحيل')
    if name in ('leaves','price_lists') and values['end_date'] < values['start_date']:
        raise BusinessError('تاريخ النهاية يجب أن يلي تاريخ البداية')
    if name == 'attendance' and values.get('check_in') and values.get('check_out') and values['check_out'] < values['check_in']:
        raise BusinessError('وقت الانصراف يجب أن يلي الحضور')
    if name == 'leaves' and values['status'] == 'معتمدة':
        overlap = db.execute("SELECT 1 FROM leaves WHERE employee_id=? AND status='معتمدة' AND start_date<=? AND end_date>=? AND id<>?",(values['employee_id'],values['end_date'],values['start_date'],eid or 0)).fetchone()
        if overlap:
            raise BusinessError('توجد إجازة معتمدة تتداخل مع هذه الفترة')
        if values['type'] == 'سنوية':
            emp = db.execute('SELECT leave_balance FROM employees WHERE id=?',(values['employee_id'],)).fetchone()
            year = values['start_date'][:4]
            used = db.execute("SELECT COALESCE(SUM(julianday(end_date)-julianday(start_date)+1),0) FROM leaves WHERE employee_id=? AND type='سنوية' AND status='معتمدة' AND substr(start_date,1,4)=? AND id<>?",(values['employee_id'],year,eid or 0)).fetchone()[0]
            days = (dt.date.fromisoformat(values['end_date'])-dt.date.fromisoformat(values['start_date'])).days+1
            if used+days > emp['leave_balance']:
                raise BusinessError('رصيد الإجازات السنوية غير كافٍ')
    if eid:
        if not db.execute(f'SELECT 1 FROM {table} WHERE id=? AND {predicate}',(eid,)).fetchone():
            raise BusinessError('السجل غير موجود')
        # Already processed payroll cannot silently change when attendance is edited.
        if name in ('attendance','employee_adjustments'):
            old = db.execute(f'SELECT * FROM {name} WHERE id=?',(eid,)).fetchone()
            for employee_id, date in [(old['employee_id'],old['date']),(values['employee_id'],values['date'])]:
                if db.execute('SELECT 1 FROM payroll_lines WHERE employee_id=? AND month=?',(employee_id,date[:7])).fetchone():
                    raise BusinessError('حضور هذا الشهر مستخدم في مسير رواتب مرحّل')
        if name == 'appointments':
            from appointments import _now
            values['updated_at'] = _now()
        if name == 'service_types':
            old_name=db.execute('SELECT name FROM service_types WHERE id=?',(eid,)).fetchone()[0]
            db.execute("UPDATE products SET service_category=? WHERE item_type='service' AND service_category=?",(values['name'],old_name))
        db.execute(f'UPDATE {table} SET '+','.join(f'{k}=?' for k in values)+f' WHERE id=? AND {predicate}',(*values.values(),eid))
    else:
        if name in ('attendance','employee_adjustments') and db.execute('SELECT 1 FROM payroll_lines WHERE employee_id=? AND month=?',(values['employee_id'],values['date'][:7])).fetchone():
            raise BusinessError('تم ترحيل راتب هذا الشهر بالفعل')
        if name in ('products','services'):
            values['item_type'] = 'service' if name=='services' else 'product'
        eid = db.execute(f'INSERT INTO {table} ({",".join(values)}) VALUES({",".join("?" for _ in values)})',tuple(values.values())).lastrowid
    audit(db,uid,'حفظ',name,eid)
    return eid


def account_id(db, code):
    row = db.execute('SELECT id FROM accounts WHERE code=?',(code,)).fetchone()
    if not row:
        raise BusinessError(f'حساب النظام {code} غير موجود')
    return row[0]


def journal(db, date, description, lines, uid, source_type=None, source_id=None):
    lines = [line for line in lines if line.get('debit',0) or line.get('credit',0)]
    if len(lines) < 2 or sum(l.get('debit',0) for l in lines) != sum(l.get('credit',0) for l in lines):
        raise BusinessError('القيد غير متوازن: يجب تساوي المدين والدائن')
    if any(l.get('debit',0)<0 or l.get('credit',0)<0 or (l.get('debit',0)>0 and l.get('credit',0)>0) for l in lines):
        raise BusinessError('كل سطر قيد يقبل مدين أو دائن موجبًا فقط')
    jid = db.execute('INSERT INTO journal(date,description,source_type,source_id,created_by) VALUES(?,?,?,?,?)',(date,description,source_type,source_id,uid)).lastrowid
    for line in lines:
        aid = line.get('account_id') or account_id(db,line['code'])
        db.execute('INSERT INTO journal_lines(journal_id,account_id,debit,credit,customer_id,supplier_id) VALUES(?,?,?,?,?,?)',(jid,aid,line.get('debit',0),line.get('credit',0),line.get('customer_id'),line.get('supplier_id')))
    return jid


def move_stock(db, wid, pid, qty, cost, date, reason, did=None):
    product = db.execute('SELECT item_type FROM products WHERE id=?',(pid,)).fetchone()
    if product and product['item_type']=='service':
        raise BusinessError('الخدمات لا تدخل في حركات المخزون')
    stock = db.execute('SELECT * FROM stock WHERE warehouse_id=? AND product_id=?',(wid,pid)).fetchone()
    old_qty, old_cost = (stock['quantity'],stock['avg_cost']) if stock else (0,0)
    new_qty = round(old_qty+qty,3)
    if new_qty < 0:
        name = db.execute('SELECT name FROM products WHERE id=?',(pid,)).fetchone()[0]
        raise BusinessError(f'رصيد غير كافٍ للصنف «{name}». المتاح: {old_qty}')
    new_cost = round((old_qty*old_cost+qty*cost)/new_qty,8) if qty>0 and new_qty else old_cost
    db.execute('INSERT INTO stock VALUES(?,?,?,?) ON CONFLICT(warehouse_id,product_id) DO UPDATE SET quantity=excluded.quantity,avg_cost=excluded.avg_cost',(wid,pid,new_qty,new_cost))
    db.execute('INSERT INTO stock_moves(document_id,warehouse_id,product_id,quantity,cost,date,reason) VALUES(?,?,?,?,?,?,?)',(did,wid,pid,qty,cost,date,reason))
    return old_cost if qty<0 else cost


def party_balance(db, kind, pid):
    col = 'customer_id' if kind=='customer' else 'supplier_id'
    code = '1200' if kind=='customer' else '2100'
    row = db.execute(f'SELECT COALESCE(SUM(debit-credit),0) FROM journal_lines WHERE {col}=? AND account_id=?',(pid,account_id(db,code))).fetchone()
    return row[0] * (1 if kind=='customer' else -1)


def effective_price(db, product_id, customer_id, date):
    """Return the stored minor-unit price, matching the catalogue offer order."""
    offer = db.execute('SELECT price FROM price_lists WHERE product_id=? AND (customer_id IS NULL OR customer_id=?) AND start_date<=? AND end_date>=? ORDER BY CASE WHEN customer_id IS NULL THEN 1 ELSE 0 END,id DESC LIMIT 1',
                       (product_id,customer_id,date,date)).fetchone()
    if offer is not None:
        return offer['price']
    row = db.execute('SELECT price FROM products WHERE id=?',(product_id,)).fetchone()
    return row['price'] if row else 0


def save_document(db, data, user):
    kind = data.get('kind')
    if kind not in KINDS:
        raise BusinessError('نوع المستند غير صحيح')
    if not document_allowed(user,kind,True):
        raise PermissionError('ليس لديك صلاحية لتنفيذ هذه العملية')
    date = valid_date(data.get('date',today()))
    wid = int(data.get('warehouse_id') or 0)
    if not db.execute('SELECT 1 FROM warehouses WHERE id=?',(wid,)).fetchone():
        raise BusinessError('اختر المخزن')
    target = int(data.get('target_warehouse_id') or 0) or None
    if kind=='transfer' and (not target or target==wid or not db.execute('SELECT 1 FROM warehouses WHERE id=?',(target,)).fetchone()):
        raise BusinessError('اختر مخزن وجهة مختلفًا للتحويل')
    cid = int(data.get('customer_id') or 0) or None
    sid = int(data.get('supplier_id') or 0) or None
    if kind in ('sale','sale_return','inspection') and not cid:
        raise BusinessError('اختر العميل، ويمكن إنشاء عميل للمبيعات النقدية')
    if kind in ('purchase','purchase_return','purchase_order') and not sid:
        raise BusinessError('اختر المورد')
    if cid and not db.execute('SELECT 1 FROM customers WHERE id=?',(cid,)).fetchone():
        raise BusinessError('العميل غير موجود')
    if sid and not db.execute('SELECT 1 FROM suppliers WHERE id=?',(sid,)).fetchone():
        raise BusinessError('المورد غير موجود')
    raw = data.get('lines',[])
    if not isinstance(raw,list) or not raw or len(raw)>500:
        raise BusinessError('أضف أصناف المستند (بحد أقصى 500 سطر)')
    locked_quote = kind=='inspection' and user['role']!='admin'
    company_settings = settings(db)
    lines, seen = [], set()
    for item in raw:
        pid = int(item.get('product_id') or 0)
        product = db.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()
        if not product or pid in seen:
            raise BusinessError('الصنف غير موجود أو مكرر؛ اجمع الكمية في سطر واحد')
        if product['item_type']=='service' and kind not in ('sale','sale_return','inspection'):
            raise BusinessError('الخدمات متاحة في المعاينات والمبيعات فقط')
        seen.add(pid)
        qty = number(item.get('quantity'),kind!='adjustment')
        if qty < 0:
            raise BusinessError('كمية الجرد لا تقبل السالب')
        expected_price = effective_price(db,pid,cid,date) if locked_quote else None
        price = money(item.get('price', amount(expected_price) if locked_quote else 0))
        if price<0:
            raise BusinessError('السعر لا يقبل السالب')
        if locked_quote and price!=expected_price:
            raise PermissionError('تعديل سعر عرض السعر متاح للمدير فقط')
        if kind == 'sale' and product['expiry_date'] and product['expiry_date'] < date:
            raise BusinessError('لا يمكن بيع صنف منتهي الصلاحية')
        lines.append(dict(product_id=pid,quantity=qty,price=price,total=rounded(Decimal(str(qty))*price),
                          service_method=product['service_method'] if product['item_type']=='service' else ''))
    subtotal = sum(l['total'] for l in lines)
    discount = money(data.get('discount'))
    tax_rate = number(data.get('tax_rate',company_settings['tax_rate'] if locked_quote else 0))
    if locked_quote and (discount or tax_rate!=company_settings['tax_rate']):
        raise PermissionError('تعديل الخصم والضريبة في عرض السعر متاح للمدير فقط')
    if discount<0 or discount>subtotal or not 0<=tax_rate<=100:
        raise BusinessError('راجع قيمة الخصم ونسبة الضريبة')
    if kind in ('sale','inspection') and subtotal and discount*100/subtotal > company_settings['discount_limit']:
        raise BusinessError('الخصم يتجاوز الحد المسموح في إعدادات المبيعات')
    tax = rounded(Decimal(subtotal-discount)*Decimal(str(tax_rate))/100)
    total = subtotal-discount+tax
    paid = money(data.get('paid'))
    if not 0<=paid<=total:
        raise BusinessError('المدفوع يجب أن يكون بين صفر وإجمالي المستند')
    if kind not in ('sale','purchase','sale_return','purchase_return') and paid:
        raise BusinessError('هذا النوع لا يقبل سدادًا نقديًا')
    method = data.get('payment_method','cash')
    if method not in ('cash','bank','card'):
        raise BusinessError('طريقة الدفع غير صحيحة')
    source = int(data.get('source_id') or 0) or None
    if source:
        src = db.execute('SELECT * FROM documents WHERE id=?',(source,)).fetchone()
        expected = {'sale':'inspection','purchase':'purchase_order','sale_return':'sale','purchase_return':'purchase'}.get(kind)
        if not src or src['kind']!=expected or src['status']=='draft':
            raise BusinessError('المستند المصدر غير صحيح أو غير مرحّل')
        if src['customer_id']!=cid or src['supplier_id']!=sid:
            raise BusinessError('طرف المستند لا يطابق المستند المصدر')
        if kind=='sale' and db.execute('SELECT 1 FROM appointments WHERE quotation_id=? AND invoice_id IS NOT NULL',(source,)).fetchone():
            raise BusinessError('الموعد مرتبط بفاتورة مبيعات بالفعل')
        if kind in ('sale_return','purchase_return'):
            for line in lines:
                original = db.execute('SELECT * FROM document_lines WHERE document_id=? AND product_id=?',(source,line['product_id'])).fetchone()
                returned = db.execute("SELECT COALESCE(SUM(l.quantity),0) FROM document_lines l JOIN documents d ON d.id=l.document_id WHERE d.source_id=? AND d.kind=? AND d.status='posted' AND l.product_id=?",(source,kind,line['product_id'])).fetchone()[0]
                if not original or line['quantity']+returned>original['quantity']+.00001 or line['price']!=original['price']:
                    raise BusinessError('المرتجع يتجاوز الكمية الأصلية أو يختلف عن سعر الفاتورة')
            tax_rate = src['tax_rate']
            discount = rounded(Decimal(subtotal)*src['discount']/src['subtotal']) if src['subtotal'] else 0
            tax = rounded(Decimal(subtotal-discount)*Decimal(str(tax_rate))/100)
            total = subtotal-discount+tax
            if paid>total:
                raise BusinessError('مبلغ السداد يتجاوز إجمالي المرتجع بعد تطبيق خصم الفاتورة الأصلية')
        elif db.execute("SELECT 1 FROM documents WHERE source_id=? AND kind=? AND status='posted'",(source,kind)).fetchone():
            raise BusinessError('تم تحويل هذا المستند إلى فاتورة بالفعل')
        for line in lines:
            original = db.execute('SELECT service_method FROM document_lines WHERE document_id=? AND product_id=?',(source,line['product_id'])).fetchone()
            if original is not None:
                line['service_method'] = original['service_method']
    elif kind in ('sale_return','purchase_return'):
        raise BusinessError('اختر الفاتورة الأصلية للمرتجع')
    due = valid_date(data['due_date']) if data.get('due_date') else date
    if due<date:
        raise BusinessError('تاريخ الاستحقاق لا يسبق تاريخ المستند')
    seq = db.execute('SELECT COALESCE(MAX(id),0)+1 FROM documents').fetchone()[0]
    docnum = f'{KINDS[kind][2]}-{date[:4]}-{seq:05}'
    did = db.execute('INSERT INTO documents(number,kind,date,due_date,customer_id,supplier_id,warehouse_id,target_warehouse_id,source_id,subtotal,discount,tax_rate,tax,total,paid,payment_method,note,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(docnum,kind,date,due,cid,sid,wid,target,source,subtotal,discount,tax_rate,tax,total,paid,method,str(data.get('note',''))[:4000],user['id'])).lastrowid
    if source:
        db.execute('UPDATE documents SET service_activity=? WHERE id=?',(src['service_activity'],did))
    if kind=='inspection':
        appointment=valid_date(data['appointment_date']) if data.get('appointment_date') else None
        db.execute('UPDATE documents SET appointment_date=?,location=? WHERE id=?',(appointment,str(data.get('location',''))[:1000],did))
    for l in lines:
        db.execute('INSERT INTO document_lines(document_id,product_id,quantity,price,total,service_method) VALUES(?,?,?,?,?,?)',(did,l['product_id'],l['quantity'],l['price'],l['total'],l['service_method']))
    if kind=='sale' and source:
        from appointments import _now
        now=_now()
        db.execute("UPDATE appointments SET invoice_id=?,status='invoiced',completed_at=COALESCE(completed_at,?),updated_at=? WHERE quotation_id=?",(did,now,now,source))
    audit(db,user['id'],'إنشاء مستند','documents',did,docnum)
    if data.get('post',True):
        post_document(db,did,user)
    return did


def post_document(db, did, user):
    doc = db.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
    if not doc or doc['status']!='draft':
        raise BusinessError('المستند غير موجود أو تم ترحيله بالفعل')
    kind, date = doc['kind'], doc['date']
    if not document_allowed(user,kind,True):
        raise PermissionError('ليس لديك صلاحية لتنفيذ هذه العملية')
    lines = db.execute('SELECT * FROM document_lines WHERE document_id=?',(did,)).fetchall()
    cid, sid, total, tax, paid = doc['customer_id'],doc['supplier_id'],doc['total'],doc['tax'],doc['paid']
    if kind == 'sale':
        limit = db.execute('SELECT credit_limit FROM customers WHERE id=?',(cid,)).fetchone()[0]
        if limit and party_balance(db,'customer',cid)+total-paid>limit:
            raise BusinessError('الفاتورة تتجاوز حد ائتمان العميل')
    if kind in ('sale','purchase') and doc['source_id'] and db.execute("SELECT 1 FROM documents WHERE source_id=? AND kind=? AND status='posted'",(doc['source_id'],kind)).fetchone():
        raise BusinessError('تم تحويل المستند المصدر بالفعل')
    if doc['source_id']:
        source = db.execute('SELECT * FROM documents WHERE id=?',(doc['source_id'],)).fetchone()
        if date<source['date']:
            raise BusinessError('تاريخ المستند لا يسبق المستند المصدر')
    if kind in ('sale_return','purchase_return'):
        for line in lines:
            original = db.execute('SELECT * FROM document_lines WHERE document_id=? AND product_id=?',(doc['source_id'],line['product_id'])).fetchone()
            returned = db.execute("SELECT COALESCE(SUM(l.quantity),0) FROM document_lines l JOIN documents d ON d.id=l.document_id WHERE d.source_id=? AND d.kind=? AND d.status='posted' AND l.product_id=?",(doc['source_id'],kind,line['product_id'])).fetchone()[0]
            if not original or line['quantity']+returned>original['quantity']+.00001:
                raise BusinessError('المرتجع يتجاوز الكمية المتبقية من الفاتورة الأصلية')
        returned_total = db.execute("SELECT COALESCE(SUM(total),0) FROM documents WHERE source_id=? AND kind=? AND status='posted'",(doc['source_id'],kind)).fetchone()[0]
        if total+returned_total>source['total']:
            raise BusinessError('إجمالي المرتجعات يتجاوز قيمة الفاتورة الأصلية')
    costs = 0
    inventory_value = 0
    allocated_purchase = 0
    for index,l in enumerate(lines):
        pid, qty = l['product_id'],l['quantity']
        product = db.execute('SELECT item_type FROM products WHERE id=?',(pid,)).fetchone()
        if product['item_type']=='service':
            if kind not in ('sale','sale_return','inspection'):
                raise BusinessError('الخدمات متاحة في المعاينات والمبيعات فقط')
            db.execute('UPDATE document_lines SET cost=0 WHERE id=?',(l['id'],))
            continue
        old = db.execute('SELECT * FROM stock WHERE warehouse_id=? AND product_id=?',(doc['warehouse_id'],pid)).fetchone()
        cost = old['avg_cost'] if old else db.execute('SELECT cost FROM products WHERE id=?',(pid,)).fetchone()[0]
        if kind=='purchase':
            # Allocate the invoice discount into inventory cost; VAT stays separate.
            allocation = rounded(Decimal(l['total'])*(1-Decimal(doc['discount'])/doc['subtotal'])) if doc['subtotal'] else 0
            if index==len(lines)-1:
                allocation=total-tax-allocated_purchase
            allocated_purchase+=allocation
            cost=allocation/qty
        if kind=='sale_return':
            cost = db.execute('SELECT cost FROM document_lines WHERE document_id=? AND product_id=?',(doc['source_id'],pid)).fetchone()[0]
        if kind in ('purchase','receipt','sale_return'):
            if kind=='receipt':
                cost = l['price']
            move_stock(db,doc['warehouse_id'],pid,qty,cost,date,KINDS[kind][0],did)
            inventory_value += rounded(Decimal(str(qty))*Decimal(str(cost)))
        elif kind in ('sale','purchase_return','issue'):
            if kind=='sale':
                expiry = db.execute('SELECT expiry_date FROM products WHERE id=?',(pid,)).fetchone()[0]
                if expiry and expiry<date:
                    raise BusinessError('لا يمكن بيع صنف منتهي الصلاحية')
            move_stock(db,doc['warehouse_id'],pid,-qty,cost,date,KINDS[kind][0],did)
            costs += rounded(Decimal(str(qty))*Decimal(str(cost)))
        elif kind=='transfer':
            move_stock(db,doc['warehouse_id'],pid,-qty,cost,date,'تحويل صادر',did)
            move_stock(db,doc['target_warehouse_id'],pid,qty,cost,date,'تحويل وارد',did)
        elif kind=='adjustment':
            delta = qty-(old['quantity'] if old else 0)
            if delta:
                move_stock(db,doc['warehouse_id'],pid,delta,cost,date,'تسوية جرد',did)
                inventory_value += rounded(Decimal(str(delta))*Decimal(str(cost)))
        db.execute('UPDATE document_lines SET cost=? WHERE id=?',(cost,l['id']))
    jl = []
    revenue_account = None
    if kind in ('sale','sale_return') and doc['service_activity']:
        from appointments import activity_account
        revenue_account = activity_account(db,doc['service_activity'])
    if kind=='sale':
        jl = [dict(code='1200',debit=total,customer_id=cid),dict(code='4100',credit=total-tax),dict(code='2200',credit=tax),dict(code='5100',debit=costs),dict(code='1300',credit=costs)]
    elif kind=='sale_return':
        jl = [dict(code='1200',credit=total,customer_id=cid),dict(code='4100',debit=total-tax),dict(code='2200',debit=tax),dict(code='5100',credit=inventory_value),dict(code='1300',debit=inventory_value)]
    elif kind=='purchase':
        jl = [dict(code='1300',debit=total-tax),dict(code='1400',debit=tax),dict(code='2100',credit=total,supplier_id=sid)]
    elif kind=='purchase_return':
        jl = [dict(code='1300',credit=costs),dict(code='1400',credit=tax),dict(code='2100',debit=total,supplier_id=sid)]
        variance = (total-tax)-costs
        if variance:
            jl.append(dict(code='5500',credit=max(0,variance),debit=max(0,-variance)))
    elif kind=='receipt':
        jl = [dict(code='1300',debit=inventory_value),dict(code='3100',credit=inventory_value)]
    elif kind=='issue':
        jl = [dict(code='5500',debit=costs),dict(code='1300',credit=costs)]
    elif kind=='adjustment' and inventory_value:
        jl = [dict(code='1300',debit=max(0,inventory_value),credit=max(0,-inventory_value)),dict(code='5500',credit=max(0,inventory_value),debit=max(0,-inventory_value))]
    if revenue_account:
        for line in jl:
            if line.get('code')=='4100':
                line['account_id']=revenue_account
    if any(l.get('debit',0) or l.get('credit',0) for l in jl):
        journal(db,date,f'{KINDS[kind][0]} {doc["number"]}',jl,user['id'],'document',did)
    db.execute("UPDATE documents SET status='posted',paid=0 WHERE id=?",(did,))
    if kind=='sale' and doc['source_id']:
        db.execute("UPDATE documents SET progress='محولة لفاتورة' WHERE id=?",(doc['source_id'],))
    if paid:
        direction = 'in' if kind in ('sale','purchase_return') else 'out'
        save_payment(db,dict(date=date,direction=direction,document_id=did,amount=amount(paid),method=doc['payment_method'],note='سداد عند إصدار المستند'),user,internal=True)
    audit(db,user['id'],'ترحيل','documents',did,doc['number'])


def save_payment(db, data, user, internal=False):
    if not internal:
        require(user,'accounting',True)
    direction = data.get('direction')
    if direction not in ('in','out'):
        raise BusinessError('حدد قبض أو صرف')
    date, value = valid_date(data.get('date',today())), money(data.get('amount'))
    if value<=0:
        raise BusinessError('المبلغ يجب أن يكون أكبر من صفر')
    method = data.get('method','cash')
    if method not in ('cash','bank','card'):
        raise BusinessError('طريقة دفع غير صحيحة')
    cashcode = '1100' if method=='cash' else '1110'
    did = int(data.get('document_id') or 0) or None
    cid = int(data.get('customer_id') or 0) or None
    sid = int(data.get('supplier_id') or 0) or None
    aid = int(data.get('account_id') or 0) or None
    if did:
        doc = db.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
        if not doc or doc['status']!='posted' or doc['kind'] not in ('sale','purchase','sale_return','purchase_return'):
            raise BusinessError('اختر فاتورة مرحّلة')
        expected = 'in' if doc['kind'] in ('sale','purchase_return') else 'out'
        if direction!=expected or value>doc['total']-doc['paid']:
            raise BusinessError('اتجاه السداد غير صحيح أو المبلغ يتجاوز المتبقي')
        cid, sid = doc['customer_id'],doc['supplier_id']
        aid = account_id(db,'1200' if doc['kind'] in ('sale','sale_return') else '2100')
        db.execute('UPDATE documents SET paid=paid+? WHERE id=?',(value,did))
    elif cid or sid:
        if cid and sid:
            raise BusinessError('اختر عميلًا أو موردًا واحدًا')
        aid = account_id(db,'1200' if cid else '2100')
    else:
        row = db.execute('SELECT * FROM accounts WHERE id=?',(aid,)).fetchone()
        if not row or row['code'] in ('1000','2000','3000','4000','5000','1100','1110','1200','2100'):
            raise BusinessError('اختر حسابًا تفصيليًا للمصروف أو الإيراد')
    pid = db.execute('INSERT INTO payments(date,direction,document_id,customer_id,supplier_id,account_id,amount,method,note,created_by) VALUES(?,?,?,?,?,?,?,?,?,?)',(date,direction,did,cid,sid,aid,value,method,str(data.get('note',''))[:2000],user['id'])).lastrowid
    debit,credit = (account_id(db,cashcode),aid) if direction=='in' else (aid,account_id(db,cashcode))
    journal(db,date,('سند قبض' if direction=='in' else 'سند صرف')+f' #{pid}',[dict(account_id=debit,debit=value,customer_id=cid if debit==aid else None,supplier_id=sid if debit==aid else None),dict(account_id=credit,credit=value,customer_id=cid if credit==aid else None,supplier_id=sid if credit==aid else None)],user['id'],'payment',pid)
    audit(db,user['id'],'سداد','payments',pid)
    return pid


def run_payroll(db,data,user):
    require(user,'hr',True)
    month = str(data.get('month',''))
    try:
        first = dt.date.fromisoformat(month+'-01')
    except ValueError:
        raise BusinessError('اختر شهر الرواتب') from None
    last = first.replace(day=calendar.monthrange(first.year,first.month)[1])
    branch = int(data.get('branch_id') or 0) or None
    employees = db.execute("SELECT * FROM employees WHERE status='نشط' AND hire_date<=? AND (contract_end IS NULL OR contract_end='' OR contract_end>=?) AND (? IS NULL OR branch_id=?)",(last.isoformat(),first.isoformat(),branch,branch)).fetchall()
    if not employees:
        raise BusinessError('لا يوجد موظفون نشطون لهذا الشهر والفرع')
    bonus = money(data.get('bonus'))
    if bonus<0:
        raise BusinessError('المكافأة لا تقبل السالب')
    payid = db.execute("INSERT INTO payroll(month,branch_id,status,total,created_by) VALUES(?,?,'posted',0,?)",(month,branch,user['id'])).lastrowid
    net_total = loan_total = gross_total = 0
    for emp in employees:
        if db.execute('SELECT 1 FROM payroll_lines WHERE employee_id=? AND month=?',(emp['id'],month)).fetchone():
            raise BusinessError(f'تم احتساب راتب {emp["name"]} لهذا الشهر بالفعل')
        attendance = db.execute("SELECT COALESCE(SUM(overtime_hours),0) overtime,COALESCE(SUM(deduction),0) deduction,COALESCE(SUM(CASE WHEN status='غائب' THEN 1 ELSE 0 END),0) absence FROM attendance WHERE employee_id=? AND substr(date,1,7)=?",(emp['id'],month)).fetchone()
        unpaid = 0
        for leave in db.execute("SELECT * FROM leaves WHERE employee_id=? AND status='معتمدة' AND type='بدون راتب' AND start_date<=? AND end_date>=?",(emp['id'],last.isoformat(),first.isoformat())):
            start=max(first,dt.date.fromisoformat(leave['start_date']))
            end=min(last,dt.date.fromisoformat(leave['end_date']))
            unpaid += (end-start).days+1
        # Prevent double-deducting approved unpaid leave recorded as absence.
        overlap = db.execute("SELECT COUNT(*) FROM attendance a WHERE a.employee_id=? AND substr(a.date,1,7)=? AND a.status='غائب' AND EXISTS(SELECT 1 FROM leaves l WHERE l.employee_id=a.employee_id AND l.type='بدون راتب' AND l.status='معتمدة' AND a.date BETWEEN l.start_date AND l.end_date)",(emp['id'],month)).fetchone()[0]
        absent_days = min(30,attendance['absence']+unpaid-overlap)
        # Prorate new hires and contracts ending within the selected month.
        employment_start=max(first,dt.date.fromisoformat(emp['hire_date']))
        employment_end=min(last,dt.date.fromisoformat(emp['contract_end'])) if emp['contract_end'] else last
        factor=Decimal((employment_end-employment_start).days+1)/Decimal(last.day)
        basic=rounded(Decimal(emp['salary'])*factor)
        allowance=rounded(Decimal(emp['allowance'])*factor)
        absence = min(basic+allowance,rounded(Decimal(emp['salary'])/30*absent_days))
        overtime = rounded(Decimal(str(attendance['overtime']))*emp['overtime_rate'])
        adj=db.execute("SELECT COALESCE(SUM(CASE WHEN type='مكافأة' THEN amount ELSE 0 END),0) bonus, COALESCE(SUM(CASE WHEN type='خصم' THEN amount ELSE 0 END),0) deduction FROM employee_adjustments WHERE employee_id=? AND substr(date,1,7)=?",(emp['id'],month)).fetchone()
        employee_bonus=bonus+adj['bonus']
        employee_deduction=attendance['deduction']+adj['deduction']
        gross = basic+allowance+overtime+employee_bonus-employee_deduction-absence
        if gross<0:
            raise BusinessError(f'خصومات الموظف {emp["name"]} تتجاوز مستحقاته')
        loan = 0
        for row in db.execute('SELECT * FROM loans WHERE employee_id=? AND balance>0 AND date<=? ORDER BY id',(emp['id'],last.isoformat())).fetchall():
            deduction = min(row['installment'],row['balance'],max(0,gross-loan))
            db.execute('UPDATE loans SET balance=balance-? WHERE id=?',(deduction,row['id']))
            loan+=deduction
        net = gross-loan
        db.execute('INSERT INTO payroll_lines(payroll_id,employee_id,month,basic,allowance,overtime,bonus,deduction,absence,loan,net) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(payid,emp['id'],month,basic,allowance,overtime,employee_bonus,employee_deduction,absence,loan,net))
        net_total+=net
        gross_total+=gross
        loan_total+=loan
    if gross_total:
        journal(db,last.isoformat(),f'مسير رواتب {month}',[dict(code='5200',debit=gross_total),dict(code='2300',credit=net_total),dict(code='1500',credit=loan_total)],user['id'],'payroll',payid)
    db.execute('UPDATE payroll SET total=? WHERE id=?',(net_total,payid))
    audit(db,user['id'],'ترحيل رواتب','payroll',payid,month)
    return payid


def save_loan(db,data,user):
    require(user,'hr',True)
    emp = int(data.get('employee_id') or 0)
    value,installment = money(data.get('amount')),money(data.get('installment'))
    if value<=0 or installment<=0 or installment>value:
        raise BusinessError('راجع مبلغ السلفة والقسط')
    date = valid_date(data.get('date',today()))
    lid=db.execute('INSERT INTO loans(employee_id,date,amount,installment,balance,note) VALUES(?,?,?,?,?,?)',(emp,date,value,installment,value,str(data.get('note',''))[:2000])).lastrowid
    journal(db,date,f'صرف سلفة موظف #{emp}',[dict(code='1500',debit=value),dict(code='1100',credit=value)],user['id'],'loan',lid)
    audit(db,user['id'],'صرف سلفة','loans',lid)
    return lid


def depreciate(db,data,user):
    require(user,'accounting',True)
    month=str(data.get('month',''))
    try:
        first=dt.date.fromisoformat(month+'-01')
    except ValueError:
        raise BusinessError('اختر شهر الإهلاك') from None
    end=first.replace(day=calendar.monthrange(first.year,first.month)[1]).isoformat()
    total=0
    for asset in db.execute('SELECT * FROM assets WHERE purchase_date<=?',(end,)).fetchall():
        if db.execute('SELECT 1 FROM depreciation WHERE asset_id=? AND month=?',(asset['id'],month)).fetchone():
            continue
        used=db.execute('SELECT COALESCE(SUM(amount),0) FROM depreciation WHERE asset_id=?',(asset['id'],)).fetchone()[0]
        remaining=asset['cost']-asset['salvage']-used
        value=min(remaining,rounded(Decimal(asset['cost']-asset['salvage'])/Decimal(str(asset['life_months']))))
        if value>0:
            db.execute('INSERT INTO depreciation(asset_id,month,amount) VALUES(?,?,?)',(asset['id'],month,value))
            total+=value
    if not total:
        raise BusinessError('لا توجد أصول قابلة للإهلاك أو تم إهلاك هذا الشهر بالفعل')
    jid=journal(db,end,f'إهلاك الأصول {month}',[dict(code='5400',debit=total),dict(code='2400',credit=total)],user['id'],'depreciation',None)
    audit(db,user['id'],'إهلاك','assets',None,month)
    return jid


def document_detail(db,did):
    row=db.execute('SELECT d.*,c.name customer,s.name supplier,w.name warehouse,t.name target_warehouse FROM documents d LEFT JOIN customers c ON c.id=d.customer_id LEFT JOIN suppliers s ON s.id=d.supplier_id LEFT JOIN warehouses w ON w.id=d.warehouse_id LEFT JOIN warehouses t ON t.id=d.target_warehouse_id WHERE d.id=?',(did,)).fetchone()
    if not row:
        raise BusinessError('المستند غير موجود')
    doc=dict(row)
    for k in ('subtotal','discount','tax','total','paid'):
        doc[k]=amount(doc[k])
    doc['lines']=[]
    for row in db.execute('SELECT l.*,p.name,p.sku,p.barcode,p.item_type,u.name unit,u.name_en unit_en,u.code unit_code FROM document_lines l JOIN products p ON p.id=l.product_id LEFT JOIN units u ON u.id=p.unit_id WHERE document_id=?',(did,)):
        line=dict(row)
        for k in ('price','total','cost'):
            line[k]=amount(line[k])
        doc['lines'].append(line)
    return doc


def report(db,name,params):
    start=valid_date(params.get('from') or '2000-01-01')
    end=valid_date(params.get('to') or '2099-12-31')
    branch=int(params.get('branch_id') or 0)
    if end<start:
        raise BusinessError('راجع نطاق التقرير')
    rows=[]
    if name=='appointment_services':
        from appointments import service_report
        return service_report(db, params)
    if name=='stock':
        rows=db.execute("SELECT p.id,p.sku,p.name,p.barcode,w.name warehouse,b.name branch,COALESCE(s.quantity,0) quantity,COALESCE(s.avg_cost,p.cost)/100.0 cost,ROUND(COALESCE(s.quantity*s.avg_cost,0)/100.0,2) value,p.min_stock,p.expiry_date FROM products p CROSS JOIN warehouses w JOIN branches b ON b.id=w.branch_id LEFT JOIN stock s ON s.product_id=p.id AND s.warehouse_id=w.id WHERE COALESCE(p.item_type,'product')!='service' AND (?=0 OR b.id=?) ORDER BY p.name,w.name",(branch,branch)).fetchall()
    elif name=='moves':
        rows=db.execute('SELECT m.date,p.name product,w.name warehouse,m.quantity,m.cost/100.0 cost,m.reason,d.number document FROM stock_moves m JOIN products p ON p.id=m.product_id JOIN warehouses w ON w.id=m.warehouse_id LEFT JOIN documents d ON d.id=m.document_id WHERE m.date BETWEEN ? AND ? AND (?=0 OR w.branch_id=?) ORDER BY m.id DESC',(start,end,branch,branch)).fetchall()
    elif name=='trial_balance':
        rows=db.execute('SELECT a.code,a.name,a.type,COALESCE(SUM(CASE WHEN j.date BETWEEN ? AND ? THEN l.debit ELSE 0 END),0)/100.0 debit,COALESCE(SUM(CASE WHEN j.date BETWEEN ? AND ? THEN l.credit ELSE 0 END),0)/100.0 credit,COALESCE(SUM(CASE WHEN j.date<=? THEN l.debit-l.credit ELSE 0 END),0)/100.0 balance FROM accounts a LEFT JOIN journal_lines l ON l.account_id=a.id LEFT JOIN journal j ON j.id=l.journal_id GROUP BY a.id ORDER BY a.code',(start,end,start,end,end)).fetchall()
    elif name=='income':
        rows=db.execute("SELECT a.code,a.name,a.type,ROUND(SUM(CASE WHEN a.type='إيرادات' THEN l.credit-l.debit ELSE l.debit-l.credit END)/100.0,2) value FROM journal_lines l JOIN accounts a ON a.id=l.account_id JOIN journal j ON j.id=l.journal_id WHERE j.date BETWEEN ? AND ? AND a.type IN ('إيرادات','مصروفات') GROUP BY a.id ORDER BY a.code",(start,end)).fetchall()
    elif name=='balance_sheet':
        rows=db.execute("SELECT a.code,a.name,a.type,ROUND(SUM(CASE WHEN a.type='أصول' THEN l.debit-l.credit ELSE l.credit-l.debit END)/100.0,2) value FROM accounts a JOIN journal_lines l ON l.account_id=a.id JOIN journal j ON j.id=l.journal_id WHERE j.date<=? AND a.type IN ('أصول','التزامات','حقوق ملكية') GROUP BY a.id UNION ALL SELECT '3999','نتيجة الأعمال المرحلة','حقوق ملكية',COALESCE(SUM(l.credit-l.debit),0)/100.0 FROM journal_lines l JOIN accounts a ON a.id=l.account_id JOIN journal j ON j.id=l.journal_id WHERE j.date<=? AND a.type IN ('إيرادات','مصروفات') ORDER BY code",(end,end)).fetchall()
    elif name=='tax':
        rows=db.execute("SELECT date,number,kind,ROUND((total-tax)/100.0,2) taxable,tax_rate,tax/100.0 tax,total/100.0 total FROM documents WHERE status='posted' AND kind IN ('sale','sale_return','purchase','purchase_return') AND date BETWEEN ? AND ? ORDER BY date,id",(start,end)).fetchall()
    elif name in ('sales','purchases','inspections'):
        kinds={'sales':('sale','sale_return'),'purchases':('purchase','purchase_return'),'inspections':('inspection','inspection')}[name]
        rows=db.execute('SELECT d.date,d.number,d.kind,COALESCE(c.name,s.name,\'—\') party,b.name branch,d.status,d.total/100.0 total,d.paid/100.0 paid,(d.total-d.paid)/100.0 remaining,d.due_date FROM documents d LEFT JOIN customers c ON c.id=d.customer_id LEFT JOIN suppliers s ON s.id=d.supplier_id JOIN warehouses w ON w.id=d.warehouse_id JOIN branches b ON b.id=w.branch_id WHERE d.kind IN (?,?) AND d.date BETWEEN ? AND ? AND (?=0 OR b.id=?) ORDER BY d.date DESC,d.id DESC',(*kinds,start,end,branch,branch)).fetchall()
    elif name=='best_products':
        rows=db.execute("SELECT p.name,p.sku,SUM(CASE WHEN d.kind='sale' THEN l.quantity ELSE -l.quantity END) quantity,ROUND(SUM(CASE WHEN d.kind='sale' THEN 1 ELSE -1 END)*0.0+SUM((CASE WHEN d.kind='sale' THEN 1 ELSE -1 END)*l.total*(1-CASE WHEN d.subtotal>0 THEN CAST(d.discount AS REAL)/d.subtotal ELSE 0 END))/100.0,2) revenue,ROUND(SUM((CASE WHEN d.kind='sale' THEN 1 ELSE -1 END)*(l.total*(1-CASE WHEN d.subtotal>0 THEN CAST(d.discount AS REAL)/d.subtotal ELSE 0 END)-l.quantity*l.cost))/100.0,2) profit FROM document_lines l JOIN documents d ON d.id=l.document_id JOIN products p ON p.id=l.product_id JOIN warehouses w ON w.id=d.warehouse_id WHERE d.status='posted' AND d.kind IN ('sale','sale_return') AND d.date BETWEEN ? AND ? AND (?=0 OR w.branch_id=?) GROUP BY p.id ORDER BY revenue DESC",(start,end,branch,branch)).fetchall()
    elif name=='best_customers':
        rows=db.execute("SELECT c.name,COUNT(CASE WHEN d.kind='sale' THEN 1 END) invoices,SUM(CASE WHEN d.kind='sale' THEN d.total ELSE -d.total END)/100.0 revenue,SUM(CASE WHEN d.kind='sale' THEN d.paid ELSE -d.paid END)/100.0 paid,SUM(CASE WHEN d.kind='sale' THEN d.total-d.paid ELSE -d.total+d.paid END)/100.0 remaining FROM documents d JOIN customers c ON c.id=d.customer_id JOIN warehouses w ON w.id=d.warehouse_id WHERE d.status='posted' AND d.kind IN ('sale','sale_return') AND d.date BETWEEN ? AND ? AND (?=0 OR w.branch_id=?) GROUP BY c.id ORDER BY revenue DESC",(start,end,branch,branch)).fetchall()
    elif name=='sales_summary':
        period="substr(d.date,1,7)" if params.get('group')=='month' else 'd.date'
        rows=db.execute(f"SELECT {period} period,b.name branch,COUNT(CASE WHEN d.kind='sale' THEN 1 END) invoices,SUM(CASE WHEN d.kind='sale' THEN d.total-d.tax ELSE -d.total+d.tax END)/100.0 revenue,SUM(CASE WHEN d.kind='sale' THEN d.tax ELSE -d.tax END)/100.0 tax,SUM(CASE WHEN d.kind='sale' THEN d.total ELSE -d.total END)/100.0 total FROM documents d JOIN warehouses w ON w.id=d.warehouse_id JOIN branches b ON b.id=w.branch_id WHERE d.status='posted' AND d.kind IN ('sale','sale_return') AND d.date BETWEEN ? AND ? AND (?=0 OR w.branch_id=?) GROUP BY {period},b.id ORDER BY period DESC",(start,end,branch,branch)).fetchall()
    elif name in ('customer_balances','supplier_balances'):
        customer=name=='customer_balances'
        table,col,code=('customers','customer_id','1200') if customer else ('suppliers','supplier_id','2100')
        sign=1 if customer else -1
        rows=db.execute(f'SELECT p.id,p.name,p.phone,COALESCE(SUM(CASE WHEN j.date<=? THEN (l.debit-l.credit)*? ELSE 0 END),0)/100.0 balance FROM {table} p LEFT JOIN journal_lines l ON l.{col}=p.id AND l.account_id=? LEFT JOIN journal j ON j.id=l.journal_id GROUP BY p.id ORDER BY p.name',(end,sign,account_id(db,code))).fetchall()
    elif name=='statement':
        customer=params.get('party_type','customer')=='customer'
        col='customer_id' if customer else 'supplier_id'
        pid=int(params.get('party_id') or 0)
        code='1200' if customer else '2100'
        opening=db.execute(f'SELECT COALESCE(SUM(l.debit-l.credit),0) FROM journal_lines l JOIN journal j ON j.id=l.journal_id WHERE l.{col}=? AND l.account_id=? AND j.date<?',(pid,account_id(db,code),start)).fetchone()[0]
        running=opening
        rows=[dict(date=start,description='الرصيد الافتتاحي',debit=0,credit=0,balance=amount(opening))]
        for row in db.execute(f'SELECT j.date,j.description,l.debit,l.credit FROM journal_lines l JOIN journal j ON j.id=l.journal_id WHERE l.{col}=? AND l.account_id=? AND j.date BETWEEN ? AND ? ORDER BY j.date,j.id,l.id',(pid,account_id(db,code),start,end)):
            running+=row['debit']-row['credit']
            rows.append(dict(date=row['date'],description=row['description'],debit=amount(row['debit']),credit=amount(row['credit']),balance=amount(running)))
    elif name=='cashflow':
        rows=db.execute("SELECT p.date,CASE WHEN p.direction='in' THEN 'قبض' ELSE 'صرف' END direction,CASE p.method WHEN 'cash' THEN 'نقدي' WHEN 'bank' THEN 'تحويل بنكي' ELSE 'بطاقة' END method,a.name account,p.amount/100.0 amount,p.note FROM payments p LEFT JOIN accounts a ON a.id=p.account_id WHERE p.date BETWEEN ? AND ? ORDER BY p.date DESC,p.id DESC",(start,end)).fetchall()
    elif name=='payroll':
        rows=db.execute('SELECT p.month,e.code,e.name,b.name branch,l.basic/100.0 basic,l.allowance/100.0 allowance,l.overtime/100.0 overtime,l.bonus/100.0 bonus,l.deduction/100.0 deduction,l.absence/100.0 absence,l.loan/100.0 loan,l.net/100.0 net FROM payroll_lines l JOIN payroll p ON p.id=l.payroll_id JOIN employees e ON e.id=l.employee_id JOIN branches b ON b.id=e.branch_id WHERE p.month BETWEEN substr(?,1,7) AND substr(?,1,7) AND (?=0 OR e.branch_id=?) ORDER BY p.month DESC,e.name',(start,end,branch,branch)).fetchall()
    elif name=='attendance':
        rows=db.execute('SELECT a.date,e.name,d.name department,a.check_in,a.check_out,a.status,a.overtime_hours,a.deduction/100.0 deduction FROM attendance a JOIN employees e ON e.id=a.employee_id LEFT JOIN departments d ON d.id=e.department_id WHERE a.date BETWEEN ? AND ? AND (?=0 OR e.branch_id=?) ORDER BY a.date DESC,e.name',(start,end,branch,branch)).fetchall()
    elif name=='assets':
        rows=db.execute('SELECT a.code,a.name,a.purchase_date,a.cost/100.0 cost,a.salvage/100.0 salvage,a.life_months,COALESCE(SUM(CASE WHEN d.month<=substr(?,1,7) THEN d.amount ELSE 0 END),0)/100.0 depreciation,(a.cost-COALESCE(SUM(CASE WHEN d.month<=substr(?,1,7) THEN d.amount ELSE 0 END),0))/100.0 book_value FROM assets a LEFT JOIN depreciation d ON d.asset_id=a.id WHERE (?=0 OR a.branch_id=?) GROUP BY a.id',(end,end,branch,branch)).fetchall()
    else:
        raise BusinessError('التقرير غير موجود')
    return [dict(r) for r in rows]


def dashboard(db,user):
    result={}
    if user['role']=='technician':
        result['customers']=db.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
        result['pending_inspections']=db.execute("SELECT COUNT(*) FROM documents d WHERE kind='inspection' AND NOT EXISTS(SELECT 1 FROM documents s WHERE s.source_id=d.id AND s.kind='sale' AND s.status='posted')").fetchone()[0]
        result['appointments']=db.execute('SELECT COUNT(*) FROM appointments WHERE date>=?',(today(),)).fetchone()[0]
    elif can(user,'sales'):
        result['sales']=amount(db.execute("SELECT COALESCE(SUM(CASE WHEN kind='sale' THEN total ELSE -total END),0) FROM documents WHERE status='posted' AND kind IN ('sale','sale_return') AND substr(date,1,7)=?",(today()[:7],)).fetchone()[0])
        result['customers']=db.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
        result['pending_inspections']=db.execute("SELECT COUNT(*) FROM documents d WHERE kind='inspection' AND NOT EXISTS(SELECT 1 FROM documents s WHERE s.source_id=d.id AND s.kind='sale' AND s.status='posted')").fetchone()[0]
        months=[]
        for offset in range(5,-1,-1):
            base=dt.date.today().replace(day=1)
            index=base.year*12+base.month-1-offset
            month=f'{index//12:04}-{index%12+1:02}'
            value=db.execute("SELECT COALESCE(SUM(CASE WHEN kind='sale' THEN total ELSE -total END),0)/100.0 FROM documents WHERE status='posted' AND kind IN ('sale','sale_return') AND substr(date,1,7)=?",(month,)).fetchone()[0]
            months.append(dict(month=month,value=value))
        result['chart']=months
    if can(user,'inventory'):
        result['stock_value']=amount(round(db.execute('SELECT COALESCE(SUM(quantity*avg_cost),0) FROM stock').fetchone()[0]))
        result['products']=db.execute("SELECT COUNT(*) FROM products WHERE COALESCE(item_type,'product')!='service'").fetchone()[0]
        result['low_stock']=[dict(r) for r in db.execute("SELECT p.id,p.name,p.min_stock,COALESCE(SUM(s.quantity),0) quantity FROM products p LEFT JOIN stock s ON s.product_id=p.id WHERE COALESCE(p.item_type,'product')!='service' GROUP BY p.id HAVING COALESCE(SUM(s.quantity),0)<=p.min_stock ORDER BY quantity LIMIT 6")]
        result['expiring']=[dict(r) for r in db.execute("SELECT id,name,expiry_date FROM products WHERE COALESCE(item_type,'product')!='service' AND expiry_date IS NOT NULL AND expiry_date<=date(?,'+30 days') ORDER BY expiry_date LIMIT 6",(today(),))]
    if can(user,'accounting'):
        result['receivables']=amount(db.execute('SELECT COALESCE(SUM(debit-credit),0) FROM journal_lines WHERE account_id=?',(account_id(db,'1200'),)).fetchone()[0])
        result['payables']=amount(db.execute('SELECT COALESCE(SUM(credit-debit),0) FROM journal_lines WHERE account_id=?',(account_id(db,'2100'),)).fetchone()[0])
        result['cash']=amount(db.execute('SELECT COALESCE(SUM(debit-credit),0) FROM journal_lines WHERE account_id IN (?,?)',(account_id(db,'1100'),account_id(db,'1110'))).fetchone()[0])
    if can(user,'hr'):
        result['employees']=db.execute("SELECT COUNT(*) FROM employees WHERE status='نشط'").fetchone()[0]
        result['pending_leaves']=db.execute("SELECT COUNT(*) FROM leaves WHERE status='قيد المراجعة'").fetchone()[0]
    allowed=[kind for kind in KINDS if document_allowed(user,kind)]
    marks=','.join('?' for _ in allowed)
    result['recent_documents']=[dict(r) for r in db.execute(f'SELECT d.id,d.number,d.date,d.kind,d.status,COALESCE(c.name,s.name,\'حركة مخزون\') party,d.total/100.0 total FROM documents d LEFT JOIN customers c ON c.id=d.customer_id LEFT JOIN suppliers s ON s.id=d.supplier_id WHERE d.kind IN ({marks}) ORDER BY d.id DESC LIMIT 6',allowed)]
    return result
