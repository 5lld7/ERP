#!/usr/bin/env python3
"""Dependency-free ERP HTTP server. Use a TLS reverse proxy for deployment."""
import base64
import binascii
import csv
import hashlib
import io
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, quote

import erp

LOG = logging.getLogger('erp')
STATIC = erp.ROOT / 'static'
REPORT_MODULES = {
    'stock':'inventory','moves':'inventory','trial_balance':'accounting','income':'accounting',
    'balance_sheet':'accounting','tax':'accounting','sales':'sales','purchases':'accounting',
    'inspections':'sales','best_products':'sales','best_customers':'sales','sales_summary':'sales','customer_balances':'accounting',
    'supplier_balances':'accounting','statement':'accounting','cashflow':'accounting',
    'payroll':'hr','attendance':'hr','assets':'accounting',
}


class Handler(BaseHTTPRequestHandler):
    server_version = 'ERP/1.0'

    def log_message(self, fmt, *args):
        # Do not log request bodies, cookies, usernames, or query strings.
        LOG.info('%s %s',self.command,urlsplit(self.path).path)

    def respond(self,data,status=200,headers=None,content_type='application/json; charset=utf-8'):
        body=json.dumps(data,ensure_ascii=False,allow_nan=False).encode() if isinstance(data,(dict,list)) else data
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        for key,value in (headers or {}).items():
            self.send_header(key,value)
        self.end_headers()
        self.wfile.write(body)

    def json_body(self):
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':
            raise erp.BusinessError('الطلب يجب أن يكون بصيغة JSON')
        length=int(self.headers.get('Content-Length','0'))
        if length<=0 or length>4_000_000:
            raise erp.BusinessError('حجم الطلب غير مسموح')
        try:
            result=json.loads(self.rfile.read(length))
        except (UnicodeDecodeError,json.JSONDecodeError):
            raise erp.BusinessError('محتوى الطلب غير صحيح') from None
        if not isinstance(result,dict):
            raise erp.BusinessError('محتوى الطلب يجب أن يكون كائنًا')
        return result

    def session(self,db):
        cookie=SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie',''))
            token=cookie['erp_session'].value if 'erp_session' in cookie else ''
        except Exception:
            token=''
        digest=hashlib.sha256(token.encode()).hexdigest()
        user=db.execute('SELECT u.id,u.name,u.username,u.role,u.active FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires_at>? AND u.active=1',(digest,int(time.time()))).fetchone()
        return dict(user) if user else None,digest

    def new_session(self,db,uid):
        token=secrets.token_urlsafe(40)
        db.execute('DELETE FROM sessions WHERE expires_at<?',(int(time.time()),))
        db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,int(time.time())+12*3600))
        secure='; Secure' if os.environ.get('ERP_COOKIE_SECURE')=='1' else ''
        return {'Set-Cookie':f'erp_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200{secure}'}

    def do_GET(self):
        self.dispatch_request('GET')

    def do_POST(self):
        self.dispatch_request('POST')

    def do_PUT(self):
        self.dispatch_request('PUT')

    def do_DELETE(self):
        self.dispatch_request('DELETE')

    def dispatch_request(self,method):
        # Vercel's runtime wrapper reserves handle_request() without arguments.
        db=None
        try:
            url=urlsplit(self.path)
            path=url.path
            if not path.startswith('/api/'):
                if method!='GET':
                    return self.respond({'error':'غير مسموح'},405)
                files={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8'),'/favicon.svg':('favicon.svg','image/svg+xml')}
                if path not in files:
                    return self.respond({'error':'الصفحة غير موجودة'},404)
                file,mime=files[path]
                return self.respond((STATIC/file).read_bytes(),content_type=mime)
            # All browser mutations use a non-simple header; CORS is not enabled.
            if method!='GET':
                if self.headers.get('X-ERP-Request')!='1':
                    raise PermissionError('رمز حماية الطلب مفقود')
                origin=self.headers.get('Origin')
                if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                    raise PermissionError('مصدر الطلب غير مسموح')
            db=erp.connect()
            params={k:v[0] for k,v in parse_qs(url.query).items()}
            user,digest=self.session(db)
            if path=='/api/auth' and method=='GET':
                return self.respond({'setup_required':not bool(db.execute('SELECT 1 FROM users LIMIT 1').fetchone()),'setup_token_required':bool(os.environ.get('ERP_SETUP_TOKEN')),'user':user})
            if path in ('/api/setup','/api/login') and method=='POST':
                data=self.json_body()
                username=str(data.get('username','')).strip().lower()[:80]
                attempt_key=hashlib.sha256(username.encode()).hexdigest()
                now=int(time.time())
                with erp.transaction(db):
                    db.execute('DELETE FROM auth_attempts WHERE started_at<?',(now-900,))
                    recent=db.execute('SELECT attempts FROM auth_attempts WHERE key=?',(attempt_key,)).fetchone()
                    if recent and recent['attempts']>=20:
                        return self.respond({'error':'محاولات كثيرة. حاول بعد 15 دقيقة'},429)
                    db.execute('INSERT INTO auth_attempts(key,attempts,started_at) VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET attempts=attempts+1',(attempt_key,now))
                with erp.transaction(db):
                    if path=='/api/setup':
                        if db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                            raise erp.BusinessError('تم إعداد النظام بالفعل')
                        setup_token=os.environ.get('ERP_SETUP_TOKEN','')
                        if os.environ.get('VERCEL') and not setup_token:
                            raise erp.BusinessError('أضف ERP_SETUP_TOKEN في إعدادات Vercel لحماية إنشاء المدير الأول')
                        if setup_token and not secrets.compare_digest(str(data.get('setup_token','')),setup_token):
                            raise PermissionError('رمز إعداد المدير الأول غير صحيح')
                        name=str(data.get('name','')).strip()[:120]
                        username=str(data.get('username','')).strip().lower()[:80]
                        company=str(data.get('company_name','')).strip()[:200]
                        if not name or not username or not company:
                            raise erp.BusinessError('اسم المسؤول والمستخدم والشركة مطلوبة')
                        uid=db.execute("INSERT INTO users(name,username,password,role) VALUES(?,?,?,'admin')",(name,username,erp.password_hash(data.get('password')))).lastrowid
                        db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(company,ensure_ascii=False),'company_name'))
                        erp.audit(db,uid,'تهيئة النظام','users',uid)
                    else:
                        candidate=db.execute('SELECT * FROM users WHERE username=? AND active=1',(str(data.get('username','')).strip().lower(),)).fetchone()
                        if not candidate or not erp.password_matches(str(data.get('password','')),candidate['password']):
                            return self.respond({'error':'اسم المستخدم أو كلمة المرور غير صحيحة'},401)
                        uid=candidate['id']
                        erp.audit(db,uid,'تسجيل دخول','users',uid)
                    headers=self.new_session(db,uid)
                with erp.transaction(db):
                    db.execute('DELETE FROM auth_attempts WHERE key=?',(attempt_key,))
                return self.respond({'ok':True},headers=headers)
            if not user:
                return self.respond({'error':'يرجى تسجيل الدخول'},401)
            if path=='/api/logout' and method=='POST':
                with erp.transaction(db):
                    db.execute('DELETE FROM sessions WHERE token=?',(digest,))
                return self.respond({'ok':True},headers={'Set-Cookie':'erp_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'})
            if path=='/api/bootstrap' and method=='GET':
                # Cross-module selectors expose only labels and IDs, not salaries,
                # employee files, supplier costs, or financial account balances.
                refs={}
                for name in RESOURCES_FOR_REFS:
                    cols='id,name'
                    refs[name]=[dict(r) for r in db.execute(f'SELECT {cols} FROM {name} ORDER BY name')]
                resources={name:spec for name,spec in erp.RESOURCES.items() if erp.can(user,spec['module'])}
                return self.respond({'user':user,'settings':erp.settings(db),'resources':resources,'refs':refs,'kinds':{k:v for k,v in erp.KINDS.items() if erp.can(user,v[1])},'roles':erp.ROLES,'reports':{k:v for k,v in REPORT_MODULES.items() if erp.can(user,v)},'serverless':bool(os.environ.get('VERCEL'))})
            if path=='/api/dashboard' and method=='GET':
                return self.respond(erp.dashboard(db,user))
            parts=path.strip('/').split('/')
            if len(parts)>=3 and parts[1]=='resources':
                name=parts[2]
                if name not in erp.RESOURCES:
                    return self.respond({'error':'القسم غير موجود'},404)
                spec=erp.RESOURCES[name]
                erp.require(user,spec['module'],method!='GET')
                eid=int(parts[3]) if len(parts)==4 else None
                if method=='GET':
                    return self.respond(erp.list_resource(db,name))
                with erp.transaction(db):
                    if method in ('POST','PUT'):
                        eid=erp.save_resource(db,name,self.json_body(),user['id'],eid)
                    elif method=='DELETE' and eid:
                        if name=='accounts':
                            account=db.execute('SELECT code FROM accounts WHERE id=?',(eid,)).fetchone()
                            if account and account['code'] in {c[0] for c in erp.CHART}:
                                raise erp.BusinessError('لا يمكن حذف حسابات النظام الأساسية')
                        if name in ('attendance','employee_adjustments'):
                            r=db.execute(f'SELECT * FROM {name} WHERE id=?',(eid,)).fetchone()
                            if r and db.execute('SELECT 1 FROM payroll_lines WHERE employee_id=? AND month=?',(r['employee_id'],r['date'][:7])).fetchone():
                                raise erp.BusinessError('لا يمكن حذف حضور مستخدم في مسير مرحّل')
                        db.execute(f'DELETE FROM {name} WHERE id=?',(eid,))
                        erp.audit(db,user['id'],'حذف',name,eid)
                    else:
                        return self.respond({'error':'عملية غير مسموحة'},405)
                return self.respond({'ok':True,'id':eid})
            if path=='/api/catalog' and method=='GET':
                if not any(erp.can(user,m) for m in ('sales','inventory','accounting')):
                    raise PermissionError('غير مسموح')
                products=erp.list_resource(db,'products')
                if not erp.can(user,'accounting') and not erp.can(user,'inventory'):
                    for p in products:
                        p.pop('cost',None)
                prices=erp.list_resource(db,'price_lists') if erp.can(user,'sales') else []
                stocks=[dict(r) for r in db.execute('SELECT warehouse_id,product_id,quantity FROM stock')]
                return self.respond({'products':products,'stocks':stocks,'prices':prices})
            if len(parts)==4 and parts[1]=='employees' and parts[3]=='files':
                erp.require(user,'hr',method!='GET')
                eid=int(parts[2])
                if not db.execute('SELECT 1 FROM employees WHERE id=?',(eid,)).fetchone():
                    raise erp.BusinessError('الموظف غير موجود')
                if method=='GET':
                    return self.respond([dict(r) for r in db.execute('SELECT id,name,mime,size,created_at FROM employee_files WHERE employee_id=? ORDER BY id DESC',(eid,))])
                if method=='POST':
                    data=self.json_body()
                    try:
                        content=base64.b64decode(str(data.get('content','')),validate=True)
                    except (binascii.Error,ValueError):
                        raise erp.BusinessError('ملف غير صحيح') from None
                    if not content or len(content)>2*1024*1024:
                        raise erp.BusinessError('حجم الملف يجب ألا يتجاوز 2 ميجابايت')
                    mime='application/pdf' if content.startswith(b'%PDF-') else 'image/png' if content.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if content.startswith(b'\xff\xd8\xff') else None
                    if not mime:
                        raise erp.BusinessError('الأنواع المتاحة: PDF وPNG وJPEG فقط')
                    name=Path(str(data.get('name','document')).replace('\\','/')).name[:150]
                    with erp.transaction(db):
                        fid=db.execute('INSERT INTO employee_files(employee_id,name,mime,size,content,uploaded_by) VALUES(?,?,?,?,?,?)',(eid,name,mime,len(content),content,user['id'])).lastrowid
                        erp.audit(db,user['id'],'رفع ملف موظف','employee_files',fid)
                    return self.respond({'ok':True,'id':fid})
            if len(parts)==3 and parts[1]=='files':
                erp.require(user,'hr',method!='GET')
                fid=int(parts[2])
                row=db.execute('SELECT * FROM employee_files WHERE id=?',(fid,)).fetchone()
                if not row:
                    raise erp.BusinessError('الملف غير موجود')
                if method=='GET':
                    return self.respond(row['content'],headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(row['name'],safe='')},content_type=row['mime'])
                if method=='DELETE':
                    with erp.transaction(db):
                        db.execute('DELETE FROM employee_files WHERE id=?',(fid,))
                        erp.audit(db,user['id'],'حذف ملف موظف','employee_files',fid)
                    return self.respond({'ok':True})
            if len(parts)==4 and parts[1]=='products' and parts[3]=='qr' and method=='GET':
                if not any(erp.can(user,m) for m in ('sales','inventory','accounting')):
                    raise PermissionError('غير مسموح')
                product=db.execute('SELECT sku,barcode FROM products WHERE id=?',(int(parts[2]),)).fetchone()
                if not product:
                    raise erp.BusinessError('الصنف غير موجود')
                import qrcode
                import qrcode.image.svg
                code=qrcode.make(product['barcode'] or product['sku'],image_factory=qrcode.image.svg.SvgPathImage,box_size=6,border=3)
                out=io.BytesIO()
                code.save(out)
                return self.respond({'svg':out.getvalue().decode('utf-8')})
            if path=='/api/documents' and method=='GET':
                kinds=[k for k,s in erp.KINDS.items() if erp.can(user,s[1])]
                if params.get('kind') in kinds:
                    kinds=[params['kind']]
                marks=','.join('?' for _ in kinds)
                rows=db.execute(f"SELECT d.id,d.number,d.kind,d.date,d.status,d.progress,d.appointment_date,d.total/100.0 total,d.paid/100.0 paid,d.source_id,COALESCE(c.name,s.name,'—') party,w.name warehouse FROM documents d LEFT JOIN customers c ON c.id=d.customer_id LEFT JOIN suppliers s ON s.id=d.supplier_id JOIN warehouses w ON w.id=d.warehouse_id WHERE d.kind IN ({marks}) ORDER BY d.id DESC",kinds).fetchall()
                return self.respond([dict(r) for r in rows])
            if path=='/api/documents' and method=='POST':
                data=self.json_body()
                with erp.transaction(db):
                    did=erp.save_document(db,data,user)
                return self.respond({'ok':True,'id':did})
            if len(parts)>=3 and parts[1]=='documents':
                did=int(parts[2])
                doc=erp.document_detail(db,did)
                erp.require(user,erp.KINDS[doc['kind']][1],method!='GET')
                if method=='GET':
                    if user['role']=='sales':
                        for line in doc['lines']:
                            line.pop('cost',None)
                    return self.respond(doc)
                if method=='POST' and len(parts)==4 and parts[3]=='post':
                    with erp.transaction(db):
                        erp.post_document(db,did,user)
                    return self.respond({'ok':True})
                if method=='PUT' and len(parts)==4 and parts[3]=='progress':
                    data=self.json_body()
                    progress=data.get('progress')
                    if doc['kind']!='inspection' or progress not in ('جديدة','مجدولة','تمت المعاينة','عرض مرسل','مقبولة','مرفوضة') or doc['progress']=='محولة لفاتورة':
                        raise erp.BusinessError('لا يمكن تطبيق حالة المعاينة المحددة')
                    with erp.transaction(db):
                        db.execute('UPDATE documents SET progress=? WHERE id=?',(progress,did))
                        erp.audit(db,user['id'],'تحديث حالة المعاينة','documents',did,progress)
                    return self.respond({'ok':True})
                if method=='DELETE':
                    if doc['status']!='draft':
                        raise erp.BusinessError('لا يمكن حذف مستند مرحّل. استخدم المرتجع أو قيد التصحيح')
                    with erp.transaction(db):
                        db.execute('DELETE FROM document_lines WHERE document_id=?',(did,))
                        db.execute('DELETE FROM documents WHERE id=?',(did,))
                        erp.audit(db,user['id'],'حذف مسودة','documents',did)
                    return self.respond({'ok':True})
            if path=='/api/payments':
                erp.require(user,'accounting',method!='GET')
                if method=='GET':
                    rows=db.execute("SELECT p.id,p.date,p.direction,p.method,p.amount/100.0 amount,p.note,d.number document,COALESCE(c.name,s.name,a.name,'—') party FROM payments p LEFT JOIN documents d ON d.id=p.document_id LEFT JOIN customers c ON c.id=p.customer_id LEFT JOIN suppliers s ON s.id=p.supplier_id LEFT JOIN accounts a ON a.id=p.account_id ORDER BY p.id DESC").fetchall()
                    return self.respond([dict(r) for r in rows])
                if method=='POST':
                    data=self.json_body()
                    with erp.transaction(db):
                        pid=erp.save_payment(db,data,user)
                    return self.respond({'ok':True,'id':pid})
            if path=='/api/journal':
                erp.require(user,'accounting',method!='GET')
                if method=='GET':
                    rows=[dict(r) for r in db.execute('SELECT j.*,COALESCE(SUM(l.debit),0)/100.0 total FROM journal j LEFT JOIN journal_lines l ON l.journal_id=j.id GROUP BY j.id ORDER BY j.id DESC')]
                    return self.respond(rows)
                if method=='POST':
                    data=self.json_body()
                    lines=data.get('lines',[])
                    if not isinstance(lines,list) or len(lines)>500:
                        raise erp.BusinessError('أسطر القيد غير صحيحة')
                    converted=[]
                    for line in lines:
                        aid=int(line.get('account_id') or 0)
                        code=db.execute('SELECT code FROM accounts WHERE id=?',(aid,)).fetchone()
                        if code and code[0] in ('1200','2100') and not line.get('customer_id' if code[0]=='1200' else 'supplier_id'):
                            raise erp.BusinessError('حساب العملاء أو الموردين يتطلب تحديد الطرف لكل سطر')
                        converted.append(dict(account_id=aid,debit=erp.money(line.get('debit')),credit=erp.money(line.get('credit')),customer_id=int(line.get('customer_id') or 0) or None,supplier_id=int(line.get('supplier_id') or 0) or None))
                    description=str(data.get('description','')).strip()[:2000]
                    if not description:
                        raise erp.BusinessError('وصف القيد مطلوب')
                    with erp.transaction(db):
                        jid=erp.journal(db,erp.valid_date(data.get('date')),description,converted,user['id'],'manual')
                        erp.audit(db,user['id'],'قيد يدوي','journal',jid)
                    return self.respond({'ok':True,'id':jid})
            if len(parts)==3 and parts[1]=='journal' and method=='GET':
                erp.require(user,'accounting')
                jid=int(parts[2])
                row=db.execute('SELECT * FROM journal WHERE id=?',(jid,)).fetchone()
                if not row:
                    raise erp.BusinessError('القيد غير موجود')
                lines=[dict(r) for r in db.execute("SELECT l.id,a.code,a.name,l.debit/100.0 debit,l.credit/100.0 credit,COALESCE(c.name,s.name,'—') party FROM journal_lines l JOIN accounts a ON a.id=l.account_id LEFT JOIN customers c ON c.id=l.customer_id LEFT JOIN suppliers s ON s.id=l.supplier_id WHERE journal_id=?",(jid,))]
                return self.respond({'journal':dict(row),'lines':lines})
            if path=='/api/loans':
                erp.require(user,'hr',method!='GET')
                if method=='GET':
                    return self.respond([dict(r) for r in db.execute('SELECT l.id,e.name employee,l.date,l.amount/100.0 amount,l.installment/100.0 installment,l.balance/100.0 balance,l.note FROM loans l JOIN employees e ON e.id=l.employee_id ORDER BY l.id DESC')])
                if method=='POST':
                    data=self.json_body()
                    with erp.transaction(db):
                        lid=erp.save_loan(db,data,user)
                    return self.respond({'ok':True,'id':lid})
            if path=='/api/payroll':
                erp.require(user,'hr',method!='GET')
                if method=='GET':
                    return self.respond([dict(r) for r in db.execute("SELECT p.id,p.month,p.status,p.total/100.0 total,COALESCE(b.name,'جميع الفروع') branch,COUNT(l.id) employees FROM payroll p LEFT JOIN branches b ON b.id=p.branch_id LEFT JOIN payroll_lines l ON l.payroll_id=p.id GROUP BY p.id ORDER BY p.id DESC")])
                if method=='POST':
                    data=self.json_body()
                    with erp.transaction(db):
                        pid=erp.run_payroll(db,data,user)
                    return self.respond({'ok':True,'id':pid})
            if path=='/api/depreciate' and method=='POST':
                data=self.json_body()
                with erp.transaction(db):
                    jid=erp.depreciate(db,data,user)
                return self.respond({'ok':True,'id':jid})
            if len(parts)==3 and parts[1]=='reports' and method=='GET':
                name=parts[2]
                if name not in REPORT_MODULES:
                    raise erp.BusinessError('التقرير غير موجود')
                erp.require(user,REPORT_MODULES[name])
                rows=erp.report(db,name,params)
                if params.get('format')=='csv':
                    out=io.StringIO(newline='')
                    writer=csv.DictWriter(out,fieldnames=list(rows[0]) if rows else ['message'])
                    writer.writeheader()
                    for row in rows:
                        # Spreadsheet formula injection protection.
                        writer.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v) for k,v in row.items()})
                    return self.respond(('\ufeff'+out.getvalue()).encode(),headers={'Content-Disposition':f'attachment; filename="{name}.csv"'},content_type='text/csv; charset=utf-8')
                return self.respond(rows)
            if path=='/api/settings':
                erp.require(user,'admin',method!='GET')
                if method=='GET':
                    return self.respond(erp.settings(db))
                if method=='PUT':
                    data=self.json_body()
                    with erp.transaction(db):
                        for key,old in erp.settings(db).items():
                            if key not in data:
                                continue
                            value=data[key]
                            if isinstance(old,(int,float)):
                                value=erp.number(value)
                                max_value=100 if key in ('tax_rate','discount_limit') else 366 if key=='leave_days' else 24
                                if not 0<=value<=max_value or (key=='work_hours' and value==0):
                                    raise erp.BusinessError('راجع الإعدادات الرقمية')
                            else:
                                value=str(value).strip()[:500]
                                if key in ('company_name','currency') and not value:
                                    raise erp.BusinessError('اسم الشركة والعملة مطلوبان')
                            db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(value,ensure_ascii=False),key))
                        erp.audit(db,user['id'],'تعديل إعدادات','settings')
                    return self.respond({'ok':True})
            if path=='/api/users':
                erp.require(user,'admin',method!='GET')
                if method=='GET':
                    return self.respond([dict(r) for r in db.execute('SELECT id,name,username,role,active,created_at FROM users ORDER BY id')])
                if method=='POST':
                    data=self.json_body()
                    name=str(data.get('name','')).strip()[:120]
                    username=str(data.get('username','')).strip().lower()[:80]
                    role=data.get('role')
                    if not name or not username or role not in erp.ROLES:
                        raise erp.BusinessError('أكمل بيانات المستخدم والدور')
                    with erp.transaction(db):
                        uid=db.execute('INSERT INTO users(name,username,password,role) VALUES(?,?,?,?)',(name,username,erp.password_hash(data.get('password')),role)).lastrowid
                        erp.audit(db,user['id'],'إضافة مستخدم','users',uid)
                    return self.respond({'ok':True,'id':uid})
            if len(parts)==3 and parts[1]=='users' and method=='PUT':
                erp.require(user,'admin',True)
                data=self.json_body()
                uid=int(parts[2])
                role=data.get('role')
                active=1 if data.get('active') else 0
                if role not in erp.ROLES:
                    raise erp.BusinessError('الدور غير صحيح')
                if uid==user['id'] and (not active or role!='admin'):
                    raise erp.BusinessError('لا يمكنك إلغاء صلاحية حسابك الحالي')
                with erp.transaction(db):
                    db.execute('UPDATE users SET role=?,active=? WHERE id=?',(role,active,uid))
                    if data.get('password'):
                        db.execute('UPDATE users SET password=? WHERE id=?',(erp.password_hash(data['password']),uid))
                    db.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
                    erp.audit(db,user['id'],'تحديث صلاحيات','users',uid)
                return self.respond({'ok':True})
            if path=='/api/password' and method=='POST':
                data=self.json_body()
                row=db.execute('SELECT password FROM users WHERE id=?',(user['id'],)).fetchone()
                if not erp.password_matches(str(data.get('current','')),row[0]):
                    raise erp.BusinessError('كلمة المرور الحالية غير صحيحة')
                with erp.transaction(db):
                    db.execute('UPDATE users SET password=? WHERE id=?',(erp.password_hash(data.get('password')),user['id']))
                    db.execute('DELETE FROM sessions WHERE user_id=? AND token<>?',(user['id'],digest))
                    erp.audit(db,user['id'],'تغيير كلمة المرور','users',user['id'])
                return self.respond({'ok':True})
            if path=='/api/audit' and method=='GET':
                erp.require(user,'admin')
                return self.respond([dict(r) for r in db.execute('SELECT a.id,a.created_at,u.name user,a.action,a.entity,a.entity_id,a.detail FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 1000')])
            if path=='/api/backup' and method=='GET':
                erp.require(user,'admin')
                # sqlite backup includes WAL and creates a consistent snapshot.
                directory=erp.DATA/'backups'
                directory.mkdir(parents=True,exist_ok=True)
                filename='erp-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3)+'.sqlite3'
                target=directory/filename
                backup=sqlite3.connect(target)
                try:
                    db.backup(backup)
                finally:
                    backup.close()
                with erp.transaction(db):
                    erp.audit(db,user['id'],'نسخ احتياطي','backup')
                if os.environ.get('VERCEL') and target.stat().st_size>4_000_000:
                    target.unlink(missing_ok=True)
                    raise erp.BusinessError('النسخة تتجاوز حد تنزيل Vercel. استخدم أدوات تصدير ونسخ Turso للبيانات الكبيرة')
                content=target.read_bytes()
                if os.environ.get('VERCEL'):
                    target.unlink(missing_ok=True)
                return self.respond(content,headers={'Content-Disposition':f'attachment; filename="{filename}"'},content_type='application/vnd.sqlite3')
            if path=='/api/demo' and method=='POST':
                erp.require(user,'admin',True)
                from seed import seed_demo
                with erp.transaction(db):
                    seed_demo(db,user)
                return self.respond({'ok':True})
            return self.respond({'error':'المسار غير موجود'},404)
        except PermissionError as exc:
            self.respond({'error':str(exc)},403)
        except erp.BusinessError as exc:
            self.respond({'error':str(exc)},400)
        except sqlite3.IntegrityError:
            self.respond({'error':'السجل مكرر أو مرتبط بعمليات أخرى. راجع الكود والروابط والتواريخ'},409)
        except (ValueError,TypeError,KeyError,OverflowError):
            self.respond({'error':'بيانات الطلب غير صحيحة'},400)
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception:
            LOG.exception('Request failed')
            self.respond({'error':'حدث خطأ داخلي. راجع سجل الخادم'},500)
        finally:
            if db:
                db.close()


RESOURCES_FOR_REFS=['branches','warehouses','categories','units','products','customers','suppliers','departments','jobs','employees','accounts']


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Arabic ERP development server')
    parser.add_argument('--host',default=os.environ.get('ERP_HOST','127.0.0.1'))
    parser.add_argument('--port',type=int,default=int(os.environ.get('ERP_PORT','8000')))
    parser.add_argument('--init-only',action='store_true')
    args=parser.parse_args()
    os.umask(0o077)
    erp.initialize()
    if args.init_only:
        print('Database initialized; create the first administrator in the application.')
        return
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    server.daemon_threads=True
    from backups import start_worker
    stop=threading.Event()
    worker=start_worker(stop)
    LOG.info('ERP listening on %s:%s',args.host,args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if worker:
            worker.join(timeout=5)
        server.server_close()


if __name__=='__main__':
    main()
