"""Optional, explicit demonstration data. Never run automatically."""
import datetime as dt
import erp


def seed_demo(db,user):
    if db.execute('SELECT 1 FROM documents LIMIT 1').fetchone() or db.execute('SELECT 1 FROM products LIMIT 1').fetchone() or db.execute('SELECT 1 FROM employees LIMIT 1').fetchone():
        raise erp.BusinessError('البيانات التجريبية متاحة فقط قبل إضافة أصناف أو موظفين أو مستندات')
    uid=user['id']
    branch=db.execute('SELECT id FROM branches ORDER BY id LIMIT 1').fetchone()[0]
    warehouse=db.execute('SELECT id FROM warehouses WHERE branch_id=? LIMIT 1',(branch,)).fetchone()[0]
    branch2=erp.save_resource(db,'branches',dict(name='فرع مدينة نصر',address='القاهرة — مدينة نصر'),uid)
    warehouse2=erp.save_resource(db,'warehouses',dict(name='مخزن مدينة نصر',branch_id=branch2),uid)
    unit=db.execute('SELECT id FROM units LIMIT 1').fetchone()[0]
    cat=erp.save_resource(db,'categories',dict(name='أثاث وتجهيزات'),uid)
    products=[]
    for index,(name,cost,price) in enumerate([('كرسي مكتبي مريح',1250,1850),('مكتب خشبي 160 سم',2800,4200),('وحدة أدراج متحركة',950,1450),('طاولة اجتماعات',4600,6900),('خزانة ملفات معدنية',1700,2600),('حامل شاشة قابل للتعديل',380,650)]):
        products.append(erp.save_resource(db,'products',dict(name=name,sku=f'PRD-{index+1:03}',barcode=f'622100000{index+1:04}',category_id=cat,unit_id=unit,cost=cost,price=price,min_stock=5),uid))
    clients=[]
    for name,cls in [('شركة الأفق للتجارة','مميز'),('مؤسسة النور','مؤسسة'),('شركة بداية للحلول','عادي'),('مبيعات نقدية','عادي')]:
        clients.append(erp.save_resource(db,'customers',dict(name=name,classification=cls,credit_limit=200000,payment_terms=30),uid))
    supplier=erp.save_resource(db,'suppliers',dict(name='الشركة المتحدة للتوريدات',payment_terms=30),uid)
    department=erp.save_resource(db,'departments',dict(name='الإدارة والمبيعات'),uid)
    job=erp.save_resource(db,'jobs',dict(name='مسؤول مبيعات'),uid)
    employees=[]
    for i,(name,salary) in enumerate([('أحمد محمد',9500),('سارة محمود',11000),('محمد علي',8500),('نور أحمد',10000)]):
        employees.append(erp.save_resource(db,'employees',dict(name=name,code=f'EMP-{i+1:03}',department_id=department,job_id=job,branch_id=branch,hire_date='2025-01-01',salary=salary,allowance=1000,overtime_rate=75,leave_balance=21,status='نشط'),uid))
    now=dt.date.today()
    for offset in range(5,-1,-1):
        index=now.year*12+now.month-1-offset
        date=f'{index//12:04}-{index%12+1:02}-02'
        erp.save_document(db,dict(kind='purchase',date=date,supplier_id=supplier,warehouse_id=warehouse,tax_rate=14,paid=10000,lines=[dict(product_id=pid,quantity=10+offset,price=[1250,2800,950,4600,1700,380][i]) for i,pid in enumerate(products)]),user)
        for j in range(3):
            date=f'{index//12:04}-{index%12+1:02}-{min(now.day,5+j*4):02}'
            erp.save_document(db,dict(kind='sale',date=date,customer_id=clients[j],warehouse_id=warehouse,tax_rate=14,paid=2000,lines=[dict(product_id=products[j],quantity=2+(5-offset),price=[1850,4200,1450][j])]),user)
    erp.save_document(db,dict(kind='transfer',date=erp.today(),warehouse_id=warehouse,target_warehouse_id=warehouse2,lines=[dict(product_id=products[0],quantity=8,price=1250)]),user)
    for j in range(3):
        erp.save_document(db,dict(kind='inspection',date=erp.today(),warehouse_id=warehouse,customer_id=clients[j],tax_rate=14,note=['تجهيز مقر الشركة الجديد','معاينة وتجهيز مكاتب الإدارة','توريد أثاث فرع جديد'][j],lines=[dict(product_id=products[j],quantity=4,price=[1850,4200,1450][j])]),user)
    for eid in employees:
        erp.save_resource(db,'attendance',dict(employee_id=eid,date=erp.today(),check_in='09:00',check_out='17:00',status='حاضر',overtime_hours=1),uid)
    erp.save_resource(db,'leaves',dict(employee_id=employees[0],start_date=(now+dt.timedelta(days=3)).isoformat(),end_date=(now+dt.timedelta(days=4)).isoformat(),type='سنوية',status='قيد المراجعة',reason='إجازة شخصية'),uid)
    erp.save_resource(db,'assets',dict(name='حاسب الإدارة',code='AST-001',purchase_date='2025-01-01',cost=36000,salvage=6000,life_months=36,branch_id=branch),uid)
    erp.audit(db,uid,'تحميل بيانات تجريبية','demo')
