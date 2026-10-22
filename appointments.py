"""Inspection appointments, assignment and atomic conversion to quotations.

Workflow state belongs to the server. Run mutations inside the caller's
transaction so customer, quotation, assignment and audit changes stay together.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import erp


STATUSES = {
    'scheduled': 'لم تتم المعاينة',
    'assigned': 'مسندة لموظف',
    'completed': 'تمت المعاينة',
    'quoted': 'محولة لعرض سعر',
    'invoiced': 'محولة لفاتورة مبيعات',
    'not_executed': 'تمت المعاينة ولم يتم التنفيذ',
    'cancelled': 'ملغاة',
}
PENDING = ('scheduled', 'assigned')
COMPLETED = ('completed', 'quoted', 'invoiced', 'not_executed')
SELECT = '''SELECT a.*,e.name assigned_employee_name,d.number quotation_number,
p.name service_name,p.service_category,
COALESCE(a.invoice_id,(SELECT s.id FROM documents s WHERE s.source_id=a.quotation_id AND s.kind='sale' ORDER BY s.id DESC LIMIT 1)) linked_invoice_id,
(SELECT s.number FROM documents s WHERE s.id=a.invoice_id OR (s.source_id=a.quotation_id AND s.kind='sale') ORDER BY s.id DESC LIMIT 1) invoice_number
FROM appointments a LEFT JOIN employees e ON e.id=a.assigned_employee_id
LEFT JOIN documents d ON d.id=a.quotation_id LEFT JOIN products p ON p.id=a.service_id'''


def business_today():
    """Calendar day used by appointment filters and reminders, in Cairo."""
    return dt.datetime.now(ZoneInfo('Africa/Cairo')).date().isoformat()


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def _positive_id(value, label='اختر معاينة صحيحة'):
    if isinstance(value, bool):
        raise erp.BusinessError(label)
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        raise erp.BusinessError(label) from None
    if result <= 0 or str(result) != str(value):
        raise erp.BusinessError(label)
    return result


def get_appointment(db, appointment_id):
    appointment_id = _positive_id(appointment_id)
    row = db.execute(SELECT + ' WHERE a.id=?', (appointment_id,)).fetchone()
    if row is None:
        raise erp.BusinessError('المعاينة غير موجودة')
    return dict(row)


def _selected(db, ids):
    marks=','.join('?' for _ in ids)
    found={row['id']:dict(row) for row in db.execute(SELECT+f' WHERE a.id IN ({marks})',ids)}
    if len(found)!=len(ids):
        raise erp.BusinessError('المعاينة غير موجودة')
    return [found[value] for value in ids]


def list_appointments(db, params=None):
    """Filter by today, exact date/range, workflow and assigned employee."""
    params = params or {}
    conditions, values = [], []
    day = params.get('day', '')
    if day not in ('', 'all', 'today'):
        raise erp.BusinessError('اختر فلتر تاريخ صحيحًا للمعاينات')
    if day == 'today':
        conditions.append('a.date=?')
        values.append(business_today())
    exact = params.get('date')
    if exact:
        conditions.append('a.date=?')
        values.append(erp.valid_date(exact))
    start, end = params.get('start') or params.get('start_date'), params.get('end') or params.get('end_date')
    if start:
        start = erp.valid_date(start)
        conditions.append('a.date>=?')
        values.append(start)
    if end:
        end = erp.valid_date(end)
        conditions.append('a.date<=?')
        values.append(end)
    if start and end and start > end:
        raise erp.BusinessError('راجع نطاق مواعيد المعاينات')
    state = params.get('status', '')
    if state and state != 'all':
        states = PENDING if state == 'pending' else COMPLETED if state == 'done' else (state,)
        if any(item not in STATUSES for item in states):
            raise erp.BusinessError('اختر حالة صحيحة للمعاينة')
        conditions.append('a.status IN (' + ','.join('?' for _ in states) + ')')
        values.extend(states)
    for key, allowed in (('service_status', ('تنفيذ','معاينة','متابعة','إعادة العمل')), ('service_category', ('مكافحة حشرات','تنظيف'))):
        if params.get(key):
            if params[key] not in allowed:
                raise erp.BusinessError('اختر حالة أو نوع خدمة صحيحًا')
            conditions.append(('p.' if key == 'service_category' else 'a.') + key + '=?')
            values.append(params[key])
    if params.get('employee_id'):
        employee_id = _positive_id(params['employee_id'], 'اختر موظف معاينات صحيحًا')
        conditions.append('a.assigned_employee_id=?')
        values.append(employee_id)
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    return [dict(row) for row in db.execute(SELECT + where + ' ORDER BY a.date,a.time,a.id', values)]


def appointment_summary(db):
    today = business_today()
    counts = {key: 0 for key in STATUSES}
    for row in db.execute('SELECT status,COUNT(*) count FROM appointments GROUP BY status'):
        if row['status'] in counts:
            counts[row['status']] = row['count']
    today_rows = db.execute('SELECT status,COUNT(*) count FROM appointments WHERE date=? GROUP BY status', (today,))
    today_counts = {row['status']: row['count'] for row in today_rows}
    return {
        'today': today,
        'today_count': sum(value for key, value in today_counts.items() if key != 'cancelled'),
        'today_pending_count': sum(today_counts.get(key, 0) for key in PENDING),
        'today_inspection_count': db.execute("SELECT COUNT(*) FROM appointments WHERE date=? AND service_status='معاينة' AND status IN ('scheduled','assigned')",(today,)).fetchone()[0],
        'counts': counts,
    }


def batch_action(db, ids, action, employee_id, user):
    erp.require(user, 'sales', True)
    if not isinstance(ids, list) or not ids or len(ids) > 500 or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in ids):
        raise erp.BusinessError('حدد معاينة واحدة على الأقل بحد أقصى 500 معاينة')
    ids = list(dict.fromkeys(ids))
    if action not in ('assign', 'complete', 'not_executed', 'cancel', 'reopen'):
        raise erp.BusinessError('اختر إجراءً صحيحًا للمعاينات')
    employee = None
    if action == 'assign':
        employee_id = _positive_id(employee_id, 'اختر موظف معاينات صحيحًا')
        employee = db.execute("SELECT id,name FROM employees WHERE id=? AND status='نشط'", (employee_id,)).fetchone()
        if employee is None:
            raise erp.BusinessError('اختر موظف معاينات نشطًا')
    rows = _selected(db, ids)
    changes, now = [], _now()
    # Validate every selected row before the first write. The caller also wraps
    # this operation in one transaction; a stale selection cannot partially act.
    for row in rows:
        status = row['status']
        target, assigned, completed = status, row['assigned_employee_id'], row['completed_at']
        if action == 'assign':
            if status not in (*PENDING, 'completed') or row['quotation_id'] or row['linked_invoice_id']:
                raise erp.BusinessError('لا يمكن إسناد معاينة مغلقة؛ أعد فتحها أولًا')
            assigned = employee_id
            target = 'assigned' if status in PENDING else status
        elif action == 'complete':
            if status not in (*PENDING, 'completed') or row['quotation_id'] or row['linked_invoice_id']:
                raise erp.BusinessError('لا يمكن تطبيق حالة المعاينة المحددة')
            target, completed = 'completed', completed or now
        elif action == 'not_executed':
            if status == 'cancelled' or row['linked_invoice_id']:
                raise erp.BusinessError('لا يمكن تطبيق حالة المعاينة المحددة')
            target, completed = 'not_executed', completed or now
        elif action == 'cancel':
            if row['linked_invoice_id']:
                raise erp.BusinessError('الموعد مرتبط بفاتورة مبيعات؛ لا يمكن إلغاؤه من المواعيد')
            if row['quotation_id']:
                raise erp.BusinessError('المعاينة مرتبطة بعرض سعر؛ استخدم حالة عدم التنفيذ')
            target = 'cancelled'
        else:
            if row['quotation_id'] or row['linked_invoice_id']:
                raise erp.BusinessError('لا يمكن إعادة فتح معاينة مرتبطة بعرض سعر')
            target, completed = ('assigned' if assigned else 'scheduled'), None
        changes.append((row, target, assigned, completed))
    groups, audit_rows = {}, []
    for row, target, assigned, completed in changes:
        if (target, assigned, completed) == (row['status'], row['assigned_employee_id'], row['completed_at']):
            continue
        groups.setdefault((target,assigned,completed),[]).append(row['id'])
        detail = STATUSES[target] + (' — ' + employee['name'] if employee else '')
        audit_rows.append((user['id'],'تحديث المعاينة','appointments',row['id'],detail))
    for (target,assigned,completed), values in groups.items():
        marks=','.join('?' for _ in values)
        db.execute(f'UPDATE appointments SET status=?,assigned_employee_id=?,completed_at=?,updated_at=? WHERE id IN ({marks})',
                   (target,assigned,completed,now,*values))
    for offset in range(0,len(audit_rows),100):
        batch=audit_rows[offset:offset+100]
        marks=','.join('(?,?,?,?,?)' for _ in batch)
        db.execute('INSERT INTO audit(user_id,action,entity,entity_id,detail) VALUES '+marks,[value for row in batch for value in row])
    return _selected(db, ids)


def prepare_quotation(db, appointment_id, user):
    erp.require(user, 'sales', True)
    row = get_appointment(db, appointment_id)
    matches = db.execute("SELECT id FROM customers WHERE phone=? AND phone IS NOT NULL AND phone<>'' ORDER BY id", (row['phone'],)).fetchall()
    row['suggested_customer_id'] = matches[0]['id'] if len(matches) == 1 else None
    row['customer_ambiguous'] = len(matches) > 1
    return row


def create_quotation(db, appointment_id, data, user):
    return create_document(db, appointment_id, data, user, 'inspection')


def create_document(db, appointment_id, data, user, kind):
    erp.require(user, 'sales', True)
    if kind not in ('inspection', 'sale') or not erp.document_allowed(user, kind, True):
        raise PermissionError('ليس لديك صلاحية لتنفيذ هذه العملية')
    row = prepare_quotation(db, appointment_id, user)
    existing = row['quotation_id'] if kind == 'inspection' else row['linked_invoice_id']
    if existing:
        return {'id': existing, 'appointment_id': row['id'], 'existing': True}
    if kind == 'inspection' and row['linked_invoice_id']:
        raise erp.BusinessError('الموعد مرتبط بفاتورة مبيعات بالفعل')
    if row['status'] in ('cancelled', 'not_executed'):
        raise erp.BusinessError('أعد فتح المعاينة قبل تحويلها إلى عرض سعر')
    payload = dict(data)
    source = db.execute('SELECT * FROM documents WHERE id=?', (row['quotation_id'],)).fetchone() if kind=='sale' and row['quotation_id'] else None
    if source and source['status']=='draft':
        raise erp.BusinessError('رحّل عرض السعر قبل تحويل الموعد إلى فاتورة')
    if source:
        payload['customer_id'] = source['customer_id']
    customer_id = payload.get('customer_id') or row['suggested_customer_id']
    if customer_id:
        customer_id = _positive_id(customer_id, 'اختر عميلًا صحيحًا لعرض السعر')
        if not db.execute('SELECT 1 FROM customers WHERE id=?', (customer_id,)).fetchone():
            raise erp.BusinessError('العميل غير موجود')
    elif row['customer_ambiguous']:
        raise erp.BusinessError('يوجد أكثر من عميل بنفس رقم الهاتف؛ اختر العميل لعرض السعر')
    else:
        customer_id = erp.save_resource(db, 'customers', {
            'name': row['customer_name'], 'phone': row['phone'], 'address': row['address'],
            'classification': 'عادي',
        }, user['id'])
    payload.update(kind=kind, customer_id=customer_id, supplier_id=None, source_id=source['id'] if source else None,
                   appointment_date=row['date'], location=row['address'])
    payload.setdefault('date', business_today())
    post = payload.get('post', True)
    payload['post'] = False
    quotation_id = erp.save_document(db, payload, user)
    db.execute('UPDATE documents SET service_activity=? WHERE id=?',(row['service_status'],quotation_id))
    if post:
        erp.post_document(db,quotation_id,user)
    now = _now()
    column, status = ('quotation_id', 'quoted') if kind=='inspection' else ('invoice_id', 'invoiced')
    db.execute(f'UPDATE appointments SET status=?,{column}=?,completed_at=COALESCE(completed_at,?),updated_at=? WHERE id=?', (status, quotation_id, now, now, row['id']))
    erp.audit(db, user['id'], 'تحويل إلى عرض سعر' if kind=='inspection' else 'تحويل إلى فاتورة مبيعات', 'appointments', row['id'], str(quotation_id))
    return {'id': quotation_id, 'appointment_id': row['id'], 'existing': False}


def ensure_deletable(db, appointment_id):
    row = get_appointment(db, appointment_id)
    if row['quotation_id'] or row['linked_invoice_id']:
        raise erp.BusinessError('لا يمكن حذف موعد مرتبط بعرض سعر أو فاتورة')


def service_report(db, params):
    """Count bookings by visit purpose; money comes only from posted invoices."""
    filters = {'start': params.get('from'), 'end': params.get('to'),
               'service_status': params.get('service_status'), 'service_category': params.get('service_category')}
    rows = list_appointments(db, filters)
    result = {name: dict(service_status=name, appointments=0, completed=0, quotations=0,
                         invoiced=0, net_revenue=0, tax=0, total=0, paid=0, balance=0)
              for name in ('تنفيذ','معاينة','متابعة','إعادة العمل')}
    branch = int(params.get('branch_id') or 0)
    invoice_ids=list({row['linked_invoice_id'] for row in rows if row['linked_invoice_id']})
    invoices, refunds = {}, {}
    for offset in range(0,len(invoice_ids),500):
        batch=invoice_ids[offset:offset+500]
        marks=','.join('?' for _ in batch)
        for invoice in db.execute(f'SELECT d.* FROM documents d JOIN warehouses w ON w.id=d.warehouse_id WHERE d.id IN ({marks}) AND (?=0 OR w.branch_id=?)',(*batch,branch,branch)):
            invoices[invoice['id']]=invoice
        for refund in db.execute(f"SELECT source_id,COALESCE(SUM(subtotal-discount),0) net,COALESCE(SUM(tax),0) tax,COALESCE(SUM(total),0) total,COALESCE(SUM(paid),0) paid FROM documents WHERE source_id IN ({marks}) AND kind='sale_return' AND status='posted' GROUP BY source_id",batch):
            refunds[refund['source_id']]=refund
    for row in rows:
        item = result.setdefault(row['service_status'], dict(service_status=row['service_status'], appointments=0, completed=0, quotations=0, invoiced=0, net_revenue=0, tax=0, total=0, paid=0, balance=0))
        invoice = invoices.get(row['linked_invoice_id'])
        if branch and invoice is None:
            continue
        item['appointments'] += 1
        item['completed'] += row['status'] in COMPLETED
        item['quotations'] += bool(row['quotation_id'])
        if invoice and invoice['status']=='posted':
            item['invoiced'] += 1
            # Returns reduce the original booking's financial figures.
            returns = refunds.get(invoice['id'],dict(net=0,tax=0,total=0,paid=0))
            item['net_revenue'] += invoice['subtotal']-invoice['discount']-returns['net']
            item['tax'] += invoice['tax']-returns['tax']
            item['total'] += invoice['total']-returns['total']
            item['paid'] += invoice['paid']-returns['paid']
    for item in result.values():
        item['balance'] = item['total']-item['paid']
        for key in ('net_revenue','tax','total','paid','balance'):
            item[key] = erp.amount(item[key])
    return list(result.values())


def activity_account(db, activity):
    """A distinct revenue ledger per service activity, without reusing custom codes."""
    definitions = {'تنفيذ':('4111','إيرادات تنفيذ الخدمات'), 'معاينة':('4112','إيرادات المعاينات'),
                   'متابعة':('4113','إيرادات المتابعة'), 'إعادة العمل':('4114','إيرادات إعادة العمل')}
    if activity not in definitions:
        raise erp.BusinessError('اختر حالة أو نوع خدمة صحيحًا')
    existing=db.execute('SELECT account_id FROM service_activity_accounts WHERE activity=?',(activity,)).fetchone()
    if existing:
        return existing['account_id']
    base,name=definitions[activity]
    code,suffix=base,0
    while db.execute('SELECT 1 FROM accounts WHERE code=?',(code,)).fetchone():
        suffix+=1
        code=f'{base}-{suffix}'
    aid=db.execute("INSERT INTO accounts(code,name,type,parent_id) VALUES(?,?,'إيرادات',?)",(code,name,erp.account_id(db,'4100'))).lastrowid
    db.execute('INSERT INTO service_activity_accounts(activity,account_id) VALUES(?,?)',(activity,aid))
    return aid
