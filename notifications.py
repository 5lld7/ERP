"""Permission-scoped, durable notifications and their read state.

Call get_notifications/mark_read inside the caller's transaction. Reconciliation
is idempotent: a polling request does not manufacture another unread event.
Resolved conditions retire their alerts; a later recurrence becomes unread again.
"""
import datetime as dt
import time

import erp
import appointments


SCHEMA = '''
CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),event_key TEXT NOT NULL,kind TEXT NOT NULL,title TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',link TEXT NOT NULL,created_at INTEGER NOT NULL,read_at INTEGER,active INTEGER NOT NULL DEFAULT 1,UNIQUE(user_id,event_key));
CREATE INDEX IF NOT EXISTS notifications_user_unread ON notifications(user_id,read_at,id);
'''

KINDS = {
    'low_stock': 'inventory', 'product_expiry': 'inventory',
    'pending_leave': 'hr', 'residency_expiry': 'hr', 'passport_expiry': 'hr',
    'driving_license_expiry': 'hr', 'appointment': 'sales', 'inspection': 'sales',
}


def _allowed_kinds(user):
    return tuple(kind for kind, module in KINDS.items() if erp.can(user, module))


def _event(key, kind, title, detail, link):
    return dict(event_key=key, kind=kind, title=title, detail=detail, link=link)


def _events(db, user):
    today = erp.today()
    soon = (dt.date.fromisoformat(today) + dt.timedelta(days=30)).isoformat()
    events = []
    if erp.can(user, 'inventory'):
        rows = db.execute("SELECT p.id,p.name,p.min_stock,COALESCE(SUM(s.quantity),0) quantity,COALESCE((SELECT MAX(m.id) FROM stock_moves m WHERE m.product_id=p.id),0) movement FROM products p LEFT JOIN stock s ON s.product_id=p.id WHERE COALESCE(p.item_type,'product')='product' GROUP BY p.id HAVING COALESCE(SUM(s.quantity),0)<=p.min_stock")
        for row in rows:
            # A subsequent stock movement under the threshold is a new event,
            # while simply polling the same stock state is not.
            events.append(_event(f"stock:{row['id']}:{row['movement']}:{row['min_stock']}", 'low_stock',
                                 'تنبيه انخفاض المخزون', f"{row['name']} — {row['quantity']:g} / {row['min_stock']:g}", '#/products'))
        for row in db.execute("SELECT id,name,expiry_date FROM products WHERE COALESCE(item_type,'product')='product' AND expiry_date IS NOT NULL AND expiry_date<>'' AND expiry_date<=?", (soon,)):
            events.append(_event(f"expiry:{row['id']}:{row['expiry_date']}", 'product_expiry',
                                 'تنبيه انتهاء صلاحية صنف', f"{row['name']} — {row['expiry_date']}", '#/products'))
    if erp.can(user, 'hr'):
        for row in db.execute("SELECT l.id,l.start_date,l.end_date,e.name FROM leaves l JOIN employees e ON e.id=l.employee_id WHERE l.status='قيد المراجعة'"):
            events.append(_event(f"leave:{row['id']}:{row['start_date']}:{row['end_date']}", 'pending_leave',
                                 'طلب إجازة بانتظار المراجعة', f"{row['name']} — {row['start_date']} / {row['end_date']}", '#/leaves'))
        for column, kind, title in (
            ('residency_expiry', 'residency_expiry', 'انتهاء صلاحية الإقامة'),
            ('passport_expiry', 'passport_expiry', 'انتهاء صلاحية جواز السفر'),
            ('driving_license_expiry', 'driving_license_expiry', 'انتهاء صلاحية رخصة القيادة'),
        ):
            # Columns are a fixed allowlist, never request input.
            for row in db.execute(f"SELECT id,name,{column} expiry FROM employees WHERE status='نشط' AND {column} IS NOT NULL AND {column}<>'' AND {column}<=?", (soon,)):
                events.append(_event(f"employee:{kind}:{row['id']}:{row['expiry']}", kind, title,
                                     f"{row['name']} — {row['expiry']}", '#/employees'))
    if erp.can(user, 'sales'):
        booking_today = appointments.business_today()
        for row in db.execute("SELECT id,customer_name,date,time FROM appointments WHERE date>=? AND status IN ('scheduled','assigned')", (booking_today,)):
            due = row['date']==booking_today
            events.append(_event(f"appointment:{row['id']}:{row['date']}:{row['time']}:{'today' if due else 'upcoming'}", 'appointment',
                                 'موعد اليوم' if due else 'موعد قادم', f"{row['customer_name']} — {row['date']} {row['time']}", '#/appointments?day=today' if due else '#/appointments'))
        rows = db.execute("SELECT d.id,d.number,d.date,COALESCE(c.name,'') customer FROM documents d LEFT JOIN customers c ON c.id=d.customer_id WHERE d.kind='inspection' AND d.progress NOT IN ('مرفوضة','محولة لفاتورة') AND NOT EXISTS(SELECT 1 FROM documents s WHERE s.source_id=d.id AND s.kind='sale' AND s.status='posted')")
        for row in rows:
            events.append(_event(f"inspection:{row['id']}", 'inspection', 'عرض سعر بانتظار المتابعة',
                                 f"{row['customer']} — {row['number']} — {row['date']}", '#/doc_inspection'))
    return events


def _snapshot(db, user, kinds):
    if not kinds:
        return {'items': [], 'unread_count': 0}
    marks = ','.join('?' for _ in kinds)
    parameters = (user['id'], *kinds)
    condition = f'user_id=? AND active=1 AND kind IN ({marks})'
    count = db.execute(f'SELECT COUNT(*) FROM notifications WHERE {condition} AND read_at IS NULL', parameters).fetchone()[0]
    rows = db.execute(f'SELECT id,kind,title,detail,link,created_at,read_at,active FROM notifications WHERE {condition} ORDER BY (read_at IS NULL) DESC,created_at DESC,id DESC LIMIT 200', parameters)
    items = []
    for row in rows:
        item = dict(row)
        item['is_read'] = item['read_at'] is not None
        item['is_active'] = bool(item.pop('active'))
        items.append(item)
    return {'items': items, 'unread_count': int(count)}


def get_notifications(db, user):
    """Reconcile permitted live conditions, preserving per-user read state."""
    kinds = _allowed_kinds(user)
    if not kinds:
        return {'items': [], 'unread_count': 0}
    now = int(time.time())
    marks = ','.join('?' for _ in kinds)
    rows = db.execute(f'SELECT id,event_key,kind,title,detail,link,active FROM notifications WHERE user_id=? AND kind IN ({marks})', (user['id'], *kinds))
    previous = {row['event_key']: dict(row) for row in rows}
    current = {event['event_key']: event for event in _events(db, user)}
    additions = []
    for key, event in current.items():
        old = previous.get(key)
        if old is None:
            additions.append((user['id'], key, event['kind'], event['title'], event['detail'], event['link'], now))
        elif not old['active']:
            db.execute('UPDATE notifications SET active=1,read_at=NULL,created_at=?,title=?,detail=?,link=? WHERE id=? AND user_id=?',
                       (now, event['title'], event['detail'], event['link'], old['id'], user['id']))
        elif any(old[field] != event[field] for field in ('title', 'detail', 'link')):
            db.execute('UPDATE notifications SET title=?,detail=?,link=? WHERE id=? AND user_id=?',
                       (event['title'], event['detail'], event['link'], old['id'], user['id']))
    # A new installation can have hundreds of alerts. Keep parameter counts
    # SQLite-compatible while avoiding one remote Turso request per new row.
    for offset in range(0, len(additions), 100):
        batch = additions[offset:offset + 100]
        values = ','.join('(?,?,?,?,?,?,?)' for _ in batch)
        db.execute('INSERT OR IGNORE INTO notifications(user_id,event_key,kind,title,detail,link,created_at) VALUES ' + values,
                   [value for row in batch for value in row])
    retired = [old['id'] for key, old in previous.items() if old['active'] and key not in current]
    for offset in range(0, len(retired), 500):
        batch = retired[offset:offset + 500]
        ids = ','.join('?' for _ in batch)
        db.execute(f'UPDATE notifications SET active=0,read_at=COALESCE(read_at,?) WHERE user_id=? AND id IN ({ids})',
                   [now, user['id'], *batch])
    return _snapshot(db, user, kinds)


def mark_read(db, user, ids=None):
    """Mark only this user's permitted alerts, and return their fresh counter."""
    if ids is not None and (not isinstance(ids, list) or len(ids) > 500 or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in ids)):
        raise erp.BusinessError('اختر إشعارات صحيحة لتحديدها كمقروءة')
    get_notifications(db, user)
    kinds = _allowed_kinds(user)
    if not kinds or ids == []:
        return _snapshot(db, user, kinds)
    marks = ','.join('?' for _ in kinds)
    clause = f'user_id=? AND active=1 AND kind IN ({marks}) AND read_at IS NULL'
    parameters = [int(time.time()), user['id'], *kinds]
    if ids is not None:
        clause += ' AND id IN (' + ','.join('?' for _ in ids) + ')'
        parameters.extend(ids)
    db.execute('UPDATE notifications SET read_at=? WHERE ' + clause, parameters)
    return _snapshot(db, user, kinds)
