"""Request-scoped presentation translations; stored ERP data stays unchanged.

JSON success payloads retain the original API contract. Only explicit error
messages and CSV display labels use these translations. Never translate an
arbitrary user-provided name or note by matching it against a UI dictionary.
"""
import re
from urllib.parse import parse_qs, urlsplit


def request_language(headers, path=''):
    """An explicit export lang wins; otherwise honor weighted ar/en headers."""
    explicit = parse_qs(urlsplit(path).query).get('lang', [''])[0]
    if explicit in ('ar', 'en'):
        return explicit
    preferred = []
    for order, item in enumerate(headers.get('Accept-Language', '').split(',')):
        parts = item.strip().lower().split(';')
        language = parts[0].split('-')[0]
        if language not in ('ar', 'en'):
            continue
        quality = 1.0
        try:
            for part in parts[1:]:
                if part.strip().startswith('q='):
                    quality = float(part.strip()[2:])
        except ValueError:
            continue
        if 0 < quality <= 1:
            preferred.append((quality, -order, language))
    return max(preferred)[2] if preferred else 'ar'


ERRORS = {
    'رابط عرض السعر غير صالح أو انتهت صلاحيته': 'The quotation link is invalid or has expired.',
    'اختر العربية أو الإنجليزية لعرض السعر': 'Choose Arabic or English for the quotation.',
    'أضف رقم واتساب العميل في بيانات العملاء قبل المشاركة': 'Add the customer WhatsApp number in the customer details before sharing.',
    'رقم واتساب العميل غير صحيح. استخدم رقمًا دوليًا أو رقم موبايل مصريًا': 'The customer WhatsApp number is invalid. Use an international number or an Egyptian mobile number.',
    'عرض السعر PDF والمشاركة متاحان للمعاينات فقط': 'Quotation PDFs and sharing are available for inspections only.',
    'اختر العميل في المعاينة قبل مشاركة عرض السعر': 'Select the inspection customer before sharing the quotation.',
    'العملة المحددة غير مدعومة': 'The selected currency is not supported.',
    'لا يمكن تغيير العملة الأساسية بعد ترحيل عمليات مالية': 'The base currency cannot be changed after posting financial transactions.',
    'كلمة المرور يجب أن تكون بين 10 و256 حرفًا': 'Password must contain between 10 and 256 characters.',
    'ليس لديك صلاحية لتنفيذ هذه العملية': 'You do not have permission to perform this action.',
    'راجع عمر الأصل وقيمته التخريدية': 'Check the asset useful life and salvage value.',
    'تاريخ النهاية يجب أن يلي تاريخ البداية': 'The end date must be on or after the start date.',
    'وقت الانصراف يجب أن يلي الحضور': 'Check-out time must be after check-in time.',
    'القيد غير متوازن: يجب تساوي المدين والدائن': 'The journal entry is unbalanced: debit and credit totals must match.',
    'كل سطر قيد يقبل مدين أو دائن موجبًا فقط': 'Each journal line must contain one positive debit or credit amount.',
    'نوع المستند غير صحيح': 'Invalid document type.',
    'اختر المخزن': 'Select a warehouse.',
    'اختر مخزن وجهة مختلفًا للتحويل': 'Select a different destination warehouse for the transfer.',
    'اختر العميل، ويمكن إنشاء عميل للمبيعات النقدية': 'Select a customer. You can create a customer for cash sales.',
    'اختر المورد': 'Select a supplier.',
    'العميل غير موجود': 'Customer not found.',
    'المورد غير موجود': 'Supplier not found.',
    'أضف أصناف المستند (بحد أقصى 500 سطر)': 'Add document items (up to 500 lines).',
    'راجع قيمة الخصم ونسبة الضريبة': 'Check the discount amount and tax rate.',
    'الخصم يتجاوز الحد المسموح في إعدادات المبيعات': 'The discount exceeds the limit in sales settings.',
    'المدفوع يجب أن يكون بين صفر وإجمالي المستند': 'The paid amount must be between zero and the document total.',
    'هذا النوع لا يقبل سدادًا نقديًا': 'This document type does not accept cash payment.',
    'طريقة الدفع غير صحيحة': 'Invalid payment method.',
    'تاريخ الاستحقاق لا يسبق تاريخ المستند': 'The due date cannot be before the document date.',
    'المستند غير موجود أو تم ترحيله بالفعل': 'The document was not found or has already been posted.',
    'تم تحويل المستند المصدر بالفعل': 'The source document has already been converted.',
    'حدد قبض أو صرف': 'Select receipt or payment.',
    'المبلغ يجب أن يكون أكبر من صفر': 'The amount must be greater than zero.',
    'طريقة دفع غير صحيحة': 'Invalid payment method.',
    'لا يوجد موظفون نشطون لهذا الشهر والفرع': 'No active employees were found for this month and branch.',
    'المكافأة لا تقبل السالب': 'The bonus cannot be negative.',
    'راجع مبلغ السلفة والقسط': 'Check the loan amount and installment.',
    'لا توجد أصول قابلة للإهلاك أو تم إهلاك هذا الشهر بالفعل': 'There are no depreciable assets, or depreciation has already been posted for this month.',
    'المستند غير موجود': 'Document not found.',
    'راجع نطاق التقرير': 'Check the report date range.',
    'القيمة المالية خارج النطاق المسموح': 'The monetary amount is outside the allowed range.',
    'أدخل قيمة مالية صحيحة': 'Enter a valid monetary amount.',
    'أدخل تاريخًا صحيحًا': 'Enter a valid date.',
    'أدخل كمية أو رقمًا صحيحًا ضمن النطاق المسموح': 'Enter a valid quantity or number within the allowed range.',
    'رموز وأنواع حسابات النظام ثابتة لحماية الترحيل': 'System account codes and types cannot be changed because they are required for posting.',
    'توجد إجازة معتمدة تتداخل مع هذه الفترة': 'An approved leave request overlaps this period.',
    'السجل غير موجود': 'Record not found.',
    'تم ترحيل راتب هذا الشهر بالفعل': 'Payroll has already been posted for this month.',
    'الصنف غير موجود أو مكرر؛ اجمع الكمية في سطر واحد': 'The item was not found or appears more than once. Combine its quantity into one line.',
    'كمية الجرد لا تقبل السالب': 'The stock count cannot be negative.',
    'السعر لا يقبل السالب': 'The price cannot be negative.',
    'لا يمكن بيع صنف منتهي الصلاحية': 'Expired items cannot be sold.',
    'المستند المصدر غير صحيح أو غير مرحّل': 'The source document is invalid or has not been posted.',
    'طرف المستند لا يطابق المستند المصدر': 'The customer or supplier does not match the source document.',
    'اختر الفاتورة الأصلية للمرتجع': 'Select the original invoice for the return.',
    'الفاتورة تتجاوز حد ائتمان العميل': 'The invoice exceeds the customer credit limit.',
    'تاريخ المستند لا يسبق المستند المصدر': 'The document date cannot be before the source document date.',
    'إجمالي المرتجعات يتجاوز قيمة الفاتورة الأصلية': 'Total returns exceed the original invoice value.',
    'اختر فاتورة مرحّلة': 'Select a posted invoice.',
    'اتجاه السداد غير صحيح أو المبلغ يتجاوز المتبقي': 'The payment direction is invalid or the amount exceeds the remaining balance.',
    'اختر شهر الرواتب': 'Select the payroll month.',
    'اختر شهر الإهلاك': 'Select the depreciation month.',
    'القيم المالية لا تقبل السالب': 'Monetary amounts cannot be negative.',
    'لا يمكن تكوين حلقة في شجرة الحسابات': 'The account hierarchy cannot contain a cycle.',
    'رصيد الإجازات السنوية غير كافٍ': 'The annual leave balance is insufficient.',
    'مبلغ السداد يتجاوز إجمالي المرتجع بعد تطبيق خصم الفاتورة الأصلية': 'The refund exceeds the return total after applying the original invoice discount.',
    'تم تحويل هذا المستند إلى فاتورة بالفعل': 'This document has already been converted to an invoice.',
    'المرتجع يتجاوز الكمية المتبقية من الفاتورة الأصلية': 'The return exceeds the remaining quantity on the original invoice.',
    'اختر عميلًا أو موردًا واحدًا': 'Select either one customer or one supplier.',
    'اختر حسابًا تفصيليًا للمصروف أو الإيراد': 'Select a detail expense or income account.',
    'القيمة لا تقبل السالب': 'The value cannot be negative.',
    'حضور هذا الشهر مستخدم في مسير رواتب مرحّل': 'Attendance for this month is included in posted payroll.',
    'المرتجع يتجاوز الكمية الأصلية أو يختلف عن سعر الفاتورة': 'The return exceeds the original quantity or uses a different invoice price.',
    'العنصر المرتبط غير موجود': 'The linked record was not found.',
    'وقت غير صحيح': 'Invalid time.',
    'التقرير غير موجود': 'Report not found.',
    'الطلب يجب أن يكون بصيغة JSON': 'The request must use JSON format.',
    'حجم الطلب غير مسموح': 'The request size is not allowed.',
    'محتوى الطلب يجب أن يكون كائنًا': 'The request body must be an object.',
    'محتوى الطلب غير صحيح': 'Invalid request body.',
    'رمز حماية الطلب مفقود': 'The request protection header is missing.',
    'مصدر الطلب غير مسموح': 'The request origin is not allowed.',
    'غير مسموح': 'Not allowed.',
    'الموظف غير موجود': 'Employee not found.',
    'الملف غير موجود': 'File not found.',
    'الصنف غير موجود': 'Item not found.',
    'القيد غير موجود': 'Journal entry not found.',
    'الدور غير صحيح': 'Invalid role.',
    'لا يمكنك إلغاء صلاحية حسابك الحالي': 'You cannot remove access from your current account.',
    'كلمة المرور الحالية غير صحيحة': 'The current password is incorrect.',
    'النسخة تتجاوز حد تنزيل Vercel. استخدم أدوات تصدير ونسخ Turso للبيانات الكبيرة': 'The backup exceeds the Vercel download limit. Use Turso export and backup tools for larger databases.',
    'حجم الملف يجب ألا يتجاوز 2 ميجابايت': 'The file must not exceed 2 MB.',
    'الأنواع المتاحة: PDF وPNG وJPEG فقط': 'Only PDF, PNG and JPEG files are supported.',
    'لا يمكن تطبيق حالة المعاينة المحددة': 'The selected inspection status cannot be applied.',
    'لا يمكن حذف مستند مرحّل. استخدم المرتجع أو قيد التصحيح': 'Posted documents cannot be deleted. Use a return or an adjusting journal entry.',
    'أسطر القيد غير صحيحة': 'Invalid journal entry lines.',
    'وصف القيد مطلوب': 'A journal entry description is required.',
    'أكمل بيانات المستخدم والدور': 'Complete the user details and select a role.',
    'تم إعداد النظام بالفعل': 'The system has already been set up.',
    'أضف ERP_SETUP_TOKEN في إعدادات Vercel لحماية إنشاء المدير الأول': 'Add ERP_SETUP_TOKEN in Vercel settings to protect the first administrator setup.',
    'رمز إعداد المدير الأول غير صحيح': 'The first administrator setup token is incorrect.',
    'اسم المسؤول والمستخدم والشركة مطلوبة': 'Administrator name, username and company name are required.',
    'ملف غير صحيح': 'Invalid file.',
    'حساب العملاء أو الموردين يتطلب تحديد الطرف لكل سطر': 'Customer and supplier accounts require a customer or supplier on each journal line.',
    'لا يمكن حذف حسابات النظام الأساسية': 'Core system accounts cannot be deleted.',
    'لا يمكن حذف حضور مستخدم في مسير مرحّل': 'Attendance included in posted payroll cannot be deleted.',
    'راجع الإعدادات الرقمية': 'Check the numeric settings.',
    'اسم الشركة والعملة مطلوبان': 'Company name and currency are required.',
    'البيانات التجريبية متاحة فقط قبل إضافة أصناف أو موظفين أو مستندات': 'Demo data is available only before adding items, employees or documents.',
    'الصفحة غير موجودة': 'Page not found.',
    'محاولات كثيرة. حاول بعد 15 دقيقة': 'Too many attempts. Try again in 15 minutes.',
    'اسم المستخدم أو كلمة المرور غير صحيحة': 'The username or password is incorrect.',
    'يرجى تسجيل الدخول': 'Please sign in.',
    'القسم غير موجود': 'Section not found.',
    'عملية غير مسموحة': 'This operation is not allowed.',
    'المسار غير موجود': 'Route not found.',
    'السجل مكرر أو مرتبط بعمليات أخرى. راجع الكود والروابط والتواريخ': 'The record is duplicated or linked to other transactions. Check its code, references and dates.',
    'بيانات الطلب غير صحيحة': 'Invalid request data.',
    'حدث خطأ داخلي. راجع سجل الخادم': 'An internal error occurred. Check the server logs.',
    'إعداد قاعدة البيانات الدائمة غير مكتمل أو الاتصال غير متاح. راجع متغيرات Vercel.': 'Persistent database setup is incomplete or the connection is unavailable. Check the Vercel environment variables.',
    'متغير ERP_DATABASE_URL غير موجود في هذا النشر. أضفه إلى Production ثم أعد النشر.': 'ERP_DATABASE_URL is missing from this deployment. Add it to Production and redeploy.',
    'متغير ERP_DATABASE_TOKEN غير موجود في هذا النشر. أضف توكن Turso ثم أعد النشر.': 'ERP_DATABASE_TOKEN is missing from this deployment. Add the Turso token and redeploy.',
    'صيغة ERP_DATABASE_URL غير صحيحة. انسخ Database URL من Turso ثم أعد النشر.': 'ERP_DATABASE_URL has an invalid format. Copy the Database URL from Turso and redeploy.',
    'اجعل قيمة ERP_COOKIE_SECURE تساوي 1 ثم أعد النشر.': 'Set ERP_COOKIE_SECURE to 1 and redeploy.',
    'Turso رفض توكن الاتصال. راجع ERP_DATABASE_TOKEN وصلاحيته لهذه القاعدة ثم أعد النشر.': 'Turso rejected the connection token. Check ERP_DATABASE_TOKEN and its access to this database, then redeploy.',
    'Turso رفض صلاحية العملية. تأكد أن توكن القاعدة يسمح بالقراءة والكتابة.': 'Turso denied this operation. Ensure the database token allows reads and writes.',
    'تعذر الاتصال بقاعدة Turso. راجع رابط القاعدة وحالة الخدمة.': 'Could not connect to Turso. Check the database URL and service status.',
    'تعذرت قراءة إصدار قاعدة البيانات.': 'Could not read the database schema version.',
    'تعذر إنشاء جداول النظام في Turso. تحقق من صلاحية القراءة والكتابة.': 'Could not create the system tables in Turso. Check read and write permissions.',
    'إصدار قاعدة البيانات أحدث من إصدار التطبيق المنشور.': 'The database schema is newer than the deployed application.',
}

FIELD_LABELS = {
    'اسم الفرع': 'Branch name', 'اسم المخزن': 'Warehouse name', 'العنوان': 'Address', 'الهاتف': 'Phone',
    'الفرع': 'Branch', 'اسم التصنيف': 'Category name', 'الوحدة': 'Unit', 'اسم الصنف': 'Item name',
    'كود الصنف': 'SKU', 'الباركود': 'Barcode', 'التصنيف': 'Category', 'تكلفة الشراء': 'Purchase cost',
    'سعر البيع': 'Sale price', 'حد إعادة الطلب': 'Reorder level', 'تاريخ الصلاحية': 'Expiry date',
    'اسم العميل': 'Customer name', 'البريد الإلكتروني': 'Email', 'الرقم الضريبي': 'Tax number',
    'حد الائتمان (صفر = بدون حد)': 'Credit limit (zero = unlimited)', 'شروط الدفع بالأيام': 'Payment terms in days',
    'اسم المورد': 'Supplier name', 'اسم الإدارة': 'Department name', 'المسمى الوظيفي': 'Job title',
    'اسم الموظف': 'Employee name', 'الكود الوظيفي': 'Employee code', 'الرقم القومي': 'National ID',
    'الإدارة': 'Department', 'الوظيفة': 'Job', 'تاريخ التعيين': 'Hire date', 'نهاية العقد': 'Contract end',
    'الراتب الأساسي': 'Basic salary', 'البدلات الشهرية': 'Monthly allowances', 'أجر الساعة الإضافية': 'Overtime hourly rate',
    'رصيد الإجازات السنوي': 'Annual leave balance', 'حالة الموظف': 'Employee status', 'الموظف': 'Employee',
    'التاريخ': 'Date', 'وقت الحضور': 'Check-in time', 'وقت الانصراف': 'Check-out time', 'الحالة': 'Status',
    'ساعات إضافية': 'Overtime hours', 'خصم': 'Deduction', 'ملاحظات': 'Notes', 'نوع التسوية': 'Adjustment type',
    'المبلغ': 'Amount', 'البيان': 'Description', 'من تاريخ': 'Start date', 'إلى تاريخ': 'End date',
    'نوع الإجازة': 'Leave type', 'السبب': 'Reason', 'اسم القائمة أو العرض': 'Price list or offer name',
    'الصنف': 'Item', 'عميل محدد (اختياري)': 'Specific customer (optional)', 'السعر': 'Price',
    'بداية العرض': 'Offer start', 'نهاية العرض': 'Offer end', 'اسم الأصل': 'Asset name', 'كود الأصل': 'Asset code',
    'تاريخ الشراء': 'Purchase date', 'التكلفة': 'Cost', 'القيمة التخريدية': 'Salvage value',
    'العمر الإنتاجي بالشهور': 'Useful life in months', 'رقم الحساب': 'Account code', 'اسم الحساب': 'Account name',
    'نوع الحساب': 'Account type', 'الحساب الأب': 'Parent account',
}


def translate_error(message, language):
    if language != 'en':
        return message
    # Startup diagnostics retain stable machine-readable codes.
    found = re.fullmatch(r'(.*?)( \[[A-Z_]+\])?', message, re.S)
    text, suffix = found.group(1), found.group(2) or ''
    if text in ERRORS:
        return ERRORS[text] + suffix
    for pattern, template in (
        (r'حقل (.+) مطلوب', '{} is required.'),
        (r'اختر قيمة صحيحة لحقل (.+)', 'Select a valid value for {}.'),
        (r'حساب النظام (.+) غير موجود', 'System account {} was not found.'),
        (r'رصيد غير كافٍ للصنف «(.+)». المتاح: (.+)', 'Insufficient stock for “{}”. Available: {}'),
        (r'تم احتساب راتب (.+) لهذا الشهر بالفعل', 'Payroll for {} has already been calculated for this month.'),
        (r'خصومات الموظف (.+) تتجاوز مستحقاته', 'Deductions for {} exceed the employee earnings.'),
    ):
        match = re.fullmatch(pattern, text, re.S)
        if match:
            values = match.groups()
            if pattern.startswith(('حقل ', 'اختر قيمة ')):
                values = tuple(FIELD_LABELS.get(value, value) for value in values)
            return template.format(*values) + suffix
    return ('The request could not be completed.' if re.search(r'[\u0600-\u06ff]', text) else text) + suffix


# Column keys remain identical in JSON. CSV headers are presentation only.
COLUMNS = {
    'id': ('الرقم', 'ID'), 'sku': ('كود الصنف', 'SKU'), 'name': ('الاسم', 'Name'),
    'barcode': ('الباركود', 'Barcode'), 'warehouse': ('المخزن', 'Warehouse'), 'branch': ('الفرع', 'Branch'),
    'quantity': ('الكمية', 'Quantity'), 'cost': ('التكلفة', 'Cost'), 'value': ('القيمة', 'Value'),
    'min_stock': ('حد إعادة الطلب', 'Reorder level'), 'expiry_date': ('تاريخ الصلاحية', 'Expiry date'),
    'date': ('التاريخ', 'Date'), 'product': ('الصنف', 'Item'), 'reason': ('السبب', 'Reason'),
    'document': ('المستند', 'Document'), 'code': ('الكود', 'Code'), 'type': ('النوع', 'Type'),
    'debit': ('مدين', 'Debit'), 'credit': ('دائن', 'Credit'), 'balance': ('الرصيد', 'Balance'),
    'number': ('رقم المستند', 'Document number'), 'kind': ('نوع المستند', 'Document type'),
    'taxable': ('القيمة الخاضعة للضريبة', 'Taxable amount'), 'tax_rate': ('نسبة الضريبة', 'Tax rate'),
    'tax': ('الضريبة', 'Tax'), 'total': ('الإجمالي', 'Total'), 'party': ('الطرف', 'Customer / supplier'),
    'status': ('الحالة', 'Status'), 'paid': ('المدفوع', 'Paid'), 'remaining': ('المتبقي', 'Remaining'),
    'due_date': ('تاريخ الاستحقاق', 'Due date'), 'revenue': ('الإيرادات', 'Revenue'), 'profit': ('الربح', 'Profit'),
    'invoices': ('عدد الفواتير', 'Invoices'), 'period': ('الفترة', 'Period'), 'phone': ('الهاتف', 'Phone'),
    'description': ('البيان', 'Description'), 'direction': ('الاتجاه', 'Direction'),
    'method': ('طريقة الدفع', 'Payment method'), 'account': ('الحساب', 'Account'), 'amount': ('المبلغ', 'Amount'),
    'note': ('ملاحظات', 'Notes'), 'month': ('الشهر', 'Month'), 'basic': ('الراتب الأساسي', 'Basic salary'),
    'allowance': ('البدلات', 'Allowances'), 'overtime': ('الأجر الإضافي', 'Overtime pay'),
    'bonus': ('المكافآت', 'Bonuses'), 'deduction': ('الخصومات', 'Deductions'), 'absence': ('خصم الغياب', 'Absence deduction'),
    'loan': ('قسط السلفة', 'Loan installment'), 'net': ('صافي الراتب', 'Net salary'),
    'department': ('الإدارة', 'Department'), 'check_in': ('وقت الحضور', 'Check-in'),
    'check_out': ('وقت الانصراف', 'Check-out'), 'overtime_hours': ('ساعات إضافية', 'Overtime hours'),
    'purchase_date': ('تاريخ الشراء', 'Purchase date'), 'salvage': ('القيمة التخريدية', 'Salvage value'),
    'life_months': ('العمر الإنتاجي بالشهور', 'Useful life in months'),
    'depreciation': ('مجمع الإهلاك', 'Accumulated depreciation'), 'book_value': ('القيمة الدفترية', 'Book value'),
    'message': ('الرسالة', 'Message'),
}
KINDS = {
    'purchase': ('فاتورة مشتريات', 'Purchase invoice'), 'purchase_return': ('مرتجع مشتريات', 'Purchase return'),
    'purchase_order': ('أمر شراء', 'Purchase order'), 'receipt': ('استلام أصناف / رصيد افتتاحي', 'Goods receipt / opening stock'),
    'sale': ('فاتورة مبيعات', 'Sales invoice'), 'sale_return': ('مرتجع مبيعات', 'Sales return'),
    'inspection': ('معاينة وعرض سعر', 'Inspection / quotation'), 'transfer': ('تحويل بين المخازن', 'Warehouse transfer'),
    'issue': ('صرف / تالف', 'Stock issue / damage'), 'adjustment': ('جرد وتسوية مخزون', 'Stock count / adjustment'),
}
FIXED_VALUES = {
    'draft': ('مسودة', 'Draft'), 'posted': ('مرحّل', 'Posted'), 'أصول': ('أصول', 'Assets'),
    'التزامات': ('التزامات', 'Liabilities'), 'حقوق ملكية': ('حقوق ملكية', 'Equity'),
    'إيرادات': ('إيرادات', 'Income'), 'مصروفات': ('مصروفات', 'Expenses'),
    'حاضر': ('حاضر', 'Present'), 'غائب': ('غائب', 'Absent'), 'إجازة': ('إجازة', 'On leave'),
    'قبض': ('قبض', 'Receipt'), 'صرف': ('صرف', 'Payment'), 'نقدي': ('نقدي', 'Cash'),
    'تحويل بنكي': ('تحويل بنكي', 'Bank transfer'), 'بطاقة': ('بطاقة', 'Card'),
    'تحويل صادر': ('تحويل صادر', 'Transfer out'), 'تحويل وارد': ('تحويل وارد', 'Transfer in'),
    'تسوية جرد': ('تسوية جرد', 'Stock adjustment'),
}
CHART_NAMES = {
    '1000': ('الأصول', 'Assets'), '1100': ('الصندوق', 'Cash'), '1110': ('البنك', 'Bank'),
    '1200': ('العملاء', 'Accounts receivable'), '1300': ('المخزون', 'Inventory'),
    '1400': ('ضريبة مدخلات', 'Input tax'), '1500': ('سلف الموظفين', 'Employee loans'),
    '1600': ('الأصول الثابتة', 'Fixed assets'), '2000': ('الالتزامات', 'Liabilities'),
    '2100': ('الموردون', 'Accounts payable'), '2200': ('ضريبة مخرجات', 'Output tax'),
    '2300': ('الرواتب المستحقة', 'Salaries payable'), '2400': ('مجمع الإهلاك', 'Accumulated depreciation'),
    '3000': ('حقوق الملكية', 'Equity'), '3100': ('رأس المال والأرصدة الافتتاحية', 'Capital and opening balances'),
    '3999': ('نتيجة الأعمال المرحلة', 'Retained earnings'), '4000': ('الإيرادات', 'Income'),
    '4100': ('إيرادات المبيعات', 'Sales revenue'), '4200': ('إيرادات أخرى', 'Other income'),
    '5000': ('المصروفات', 'Expenses'), '5100': ('تكلفة البضاعة المباعة', 'Cost of goods sold'),
    '5200': ('الرواتب والأجور', 'Salaries and wages'), '5300': ('مصروفات تشغيلية', 'Operating expenses'),
    '5400': ('مصروف الإهلاك', 'Depreciation expense'), '5500': ('فروق الجرد والتالف', 'Stock differences and damage'),
}


def csv_headers(report, keys, language):
    index = 1 if language == 'en' else 0
    return [COLUMNS.get(key, (key, key))[index] for key in keys]


def csv_row_values(report, row, language, row_index=0):
    """Translate only fields whose report contract guarantees fixed values."""
    translated = dict(row)
    index = 1 if language == 'en' else 0
    enum_fields = {
        'tax': ('kind',), 'sales': ('kind', 'status'), 'purchases': ('kind', 'status'),
        'inspections': ('kind', 'status'), 'attendance': ('status',),
        'trial_balance': ('type',), 'income': ('type',), 'balance_sheet': ('type',),
        'cashflow': ('direction', 'method'), 'moves': ('reason',),
    }.get(report, ())
    for key in enum_fields:
        value = translated.get(key)
        table = KINDS if key == 'kind' else FIXED_VALUES
        if key == 'reason':
            # Stock move reasons are system-generated kind labels, not notes.
            table = FIXED_VALUES | KINDS | {labels[0]: labels for labels in KINDS.values()}
        if value in table:
            translated[key] = table[value][index]
    if language == 'en' and report in ('trial_balance', 'income', 'balance_sheet'):
        builtin = CHART_NAMES.get(str(row.get('code')))
        if builtin and row.get('name') == builtin[0]:
            translated['name'] = builtin[1]
    if language == 'en' and report == 'statement' and row_index == 0 and row.get('description') == 'الرصيد الافتتاحي':
        translated['description'] = 'Opening balance'
    return list(translated.values())
