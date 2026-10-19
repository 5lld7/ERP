"""Customer quotation PDFs and short-lived, immutable share snapshots.

The share token is a bearer credential. Only its digest is stored; request logs
must never include query strings. Sharing prepares a link and does not imply
that WhatsApp delivered it or that the customer accepted the quotation.
"""
import hashlib
import re
import secrets
import time
import unicodedata

import erp

SHARE_TTL = 7 * 24 * 60 * 60
_TOKEN = re.compile(r'[A-Za-z0-9_-]{43}\Z')
SHARE_UNAVAILABLE = 'رابط عرض السعر غير صالح أو انتهت صلاحيته'


def language(value):
    if value not in ('ar', 'en'):
        raise erp.BusinessError('اختر العربية أو الإنجليزية لعرض السعر')
    return value


def whatsapp_phone(value):
    """Return international digits, using Egypt only for local mobile numbers."""
    text = str(value or '').strip()
    if not text:
        raise erp.BusinessError('أضف رقم واتساب العميل في بيانات العملاء قبل المشاركة')
    # Accept the same phone number typed using Arabic or Western digits.
    text = ''.join(str(unicodedata.decimal(char)) if char.isdecimal() else char for char in text)
    text = re.sub(r'[\s().-]', '', text)
    if text.startswith('+'):
        text = text[1:]
    elif text.startswith('00'):
        text = text[2:]
    elif re.fullmatch(r'01\d{9}', text):
        text = '20' + text[1:]
    if not re.fullmatch(r'[1-9][0-9]{7,14}', text):
        raise erp.BusinessError('رقم واتساب العميل غير صحيح. استخدم رقمًا دوليًا أو رقم موبايل مصريًا')
    return text


def quotation_document(db, document_id):
    doc = erp.document_detail(db, document_id)
    if doc['kind'] != 'inspection':
        raise erp.BusinessError('عرض السعر PDF والمشاركة متاحان للمعاينات فقط')
    return doc


def render_document(db, document_id, selected_language='ar'):
    from quotation_pdf import render_quotation
    selected_language = language(selected_language)
    doc = quotation_document(db, document_id)
    return render_quotation(doc, erp.settings(db), selected_language), doc


def create_share(db, document_id, user, selected_language='ar'):
    """Create a frozen PDF in the caller's write transaction."""
    erp.require(user, 'sales', True)
    selected_language = language(selected_language)
    doc = quotation_document(db, document_id)
    customer = db.execute('SELECT name,phone FROM customers WHERE id=?', (doc['customer_id'],)).fetchone()
    if customer is None:
        raise erp.BusinessError('اختر العميل في المعاينة قبل مشاركة عرض السعر')
    phone = whatsapp_phone(customer['phone'])
    company = erp.settings(db)
    from quotation_pdf import render_quotation
    pdf = render_quotation(doc, company, selected_language)
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode('ascii')).hexdigest()
    now = int(time.time())
    expires_at = now + SHARE_TTL
    # Expired snapshots are never returned; remove them during a later share.
    db.execute('DELETE FROM document_shares WHERE expires_at<=?', (now,))
    db.execute('INSERT INTO document_shares(token_hash,document_id,pdf,language,currency,expires_at,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)',
               (digest, document_id, pdf, selected_language, str(company['currency']), expires_at, user['id'], now))
    erp.audit(db, user['id'], 'إنشاء رابط عرض سعر', 'documents', document_id)
    return {'url': '/api/quotations/shared?token=' + token, 'expires_at': expires_at,
            'customer_phone': customer['phone'], 'whatsapp_phone': phone,
            'customer_name': customer['name'], 'number': doc['number'], 'total': doc['total'],
            'currency': company['currency'], 'language': selected_language}


def shared_pdf(db, token):
    """Return just PDF bytes; missing, invalid and expired tokens look identical."""
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        return None
    digest = hashlib.sha256(token.encode('ascii')).hexdigest()
    row = db.execute('SELECT pdf FROM document_shares WHERE token_hash=? AND expires_at>?',
                     (digest, int(time.time()))).fetchone()
    return bytes(row['pdf']) if row else None
