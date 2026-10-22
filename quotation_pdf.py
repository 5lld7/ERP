"""Customer-facing quotation PDFs with embedded fonts and Arabic text shaping.

Only the explicitly selected sales fields below enter the document. Internal
costs, notes, profit, user records and audit data must never enter this export.
No renderer state or customer PDF is kept on disk.
"""
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace


FONT_DIRECTORY = Path(__file__).resolve().parent / 'assets' / 'fonts'
NAVY = (20, 45, 78)
TEAL = (15, 118, 110)
LIGHT = (245, 247, 250)
INK = (47, 63, 82)

LABELS = {
    'ar': {
        'title': 'عرض سعر معاينة', 'customer': 'مقدم إلى', 'number': 'رقم العرض',
        'date': 'تاريخ العرض', 'appointment': 'موعد المعاينة', 'location': 'موقع المعاينة',
        'item': 'الصنف / الخدمة', 'quantity': 'الكمية', 'price': 'سعر الوحدة',
        'amount': 'الإجمالي', 'subtotal': 'المجموع قبل الخصم', 'discount': 'الخصم',
        'tax': 'الضريبة', 'total': 'الإجمالي المستحق', 'tax_number': 'الرقم الضريبي',
        'currency': 'العملة', 'page': 'صفحة', 'footer': 'عرض سعر معاينة — لا يمثل فاتورة ضريبية',
        'service_method': 'طريقة عمل الخدمة',
    },
    'en': {
        'title': 'Inspection quotation', 'customer': 'Prepared for', 'number': 'Quotation no.',
        'date': 'Quotation date', 'appointment': 'Inspection appointment', 'location': 'Inspection location',
        'item': 'Item / service', 'quantity': 'Qty', 'price': 'Unit price',
        'amount': 'Amount', 'subtotal': 'Subtotal', 'discount': 'Discount',
        'tax': 'Tax', 'total': 'Grand total', 'tax_number': 'Tax registration no.',
        'currency': 'Currency', 'page': 'Page', 'footer': 'Inspection quotation — this is not a tax invoice',
        'service_method': 'Service delivery method',
    },
}


def _text(value):
    """Allow multilingual content but remove invisible PDF control characters."""
    return ''.join(char for char in str(value or '') if char in '\n\t' or ord(char) >= 32).strip()


def _number(value, money=False):
    value = float(value or 0)
    return f'{value:,.2f}' if money else f'{value:,.6f}'.rstrip('0').rstrip('.')


def _ltr(value):
    # Numeric dates, international phone numbers and SKUs need a stable LTR run
    # even when their surrounding label is Arabic.
    return '\u200e' + _text(value) + '\u200e'


class QuotationPDF(FPDF):
    def __init__(self, company, language):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.language = language
        self.labels = LABELS[language]
        self.align = 'R' if language == 'ar' else 'L'
        self.company = company
        self.set_margins(16, 16, 16)
        self.set_auto_page_break(auto=True, margin=23)
        self.add_font('DejaVu', fname=FONT_DIRECTORY / 'DejaVuSans.ttf')
        self.add_font('DejaVu', style='B', fname=FONT_DIRECTORY / 'DejaVuSans-Bold.ttf')
        # Let HarfBuzz and the Unicode bidi algorithm detect each text run. Forcing
        # a global Arabic script/direction would corrupt mixed client names/SKUs.
        self.set_text_shaping(True)
        self.set_title(self.labels['title'])
        self.set_author('Serviq')
        self.set_creator('Serviq')

    def text_block(self, text, size=10, bold=False, color=INK, fill=False, padding=0):
        self.set_font('DejaVu', 'B' if bold else '', size)
        self.set_text_color(*color)
        self.multi_cell(0, size * 0.54, _text(text), align=self.align,
                        fill=fill, padding=padding, new_x='LMARGIN', new_y='NEXT')

    def header(self):
        self.set_text_color(*NAVY)
        self.set_font('DejaVu', 'B', 23)
        self.cell(0, 10, 'Serviq', align=self.align, new_x='LMARGIN', new_y='NEXT')
        self.text_block(self.company.get('company_name') or 'Serviq', 11, bold=True)
        contact = '  |  '.join((_ltr(self.company[key]) if key == 'company_phone' else self.company[key])
                              for key in ('company_phone', 'company_address') if self.company.get(key))
        if contact:
            self.text_block(contact, 8)
        if self.company.get('tax_number'):
            self.text_block(self.labels['tax_number'] + ': ' + _text(self.company['tax_number']), 8)
        self.ln(3)
        self.set_draw_color(*TEAL)
        self.set_line_width(0.7)
        self.line(self.l_margin, self.y, self.w - self.r_margin, self.y)
        self.ln(7)

    def footer(self):
        self.set_y(-18)
        self.set_draw_color(222, 229, 236)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.y, self.w - self.r_margin, self.y)
        self.ln(3)
        self.set_font('DejaVu', '', 8)
        self.set_text_color(*INK)
        self.cell(0, 5, self.labels['footer'], align=self.align, new_x='LMARGIN', new_y='NEXT')
        self.cell(0, 4, f"{self.labels['page']} {self.page_no()}", align='C')


def render_quotation(document, settings, language='ar'):
    """Return a branded PDF using public quotation fields, never internal notes.

    Monetary values are in major currency units, as returned by
    ``erp.document_detail``. A fresh PDF object prevents cross-request leakage.
    """
    language = 'en' if language == 'en' else 'ar'
    labels = LABELS[language]
    company = {key: _text(settings.get(key)) for key in
               ('company_name', 'company_address', 'company_phone', 'tax_number')}
    currency = _text(settings.get('currency') or 'EGP')
    if currency == 'ج.م':
        currency = 'EGP'
    pdf = QuotationPDF(company, language)
    pdf.add_page()
    pdf.text_block(labels['title'], 20, bold=True, color=NAVY)
    pdf.ln(4)
    # The client's name is the most prominent content after the document title.
    pdf.set_fill_color(*LIGHT)
    pdf.text_block(labels['customer'], 9, color=TEAL, fill=True, padding=(3, 4, 1, 4))
    pdf.text_block(document.get('customer') or '—', 15, bold=True,
                   color=NAVY, fill=True, padding=(1, 4, 4, 4))
    pdf.ln(4)
    for key, label in (('number', 'number'), ('date', 'date'),
                       ('appointment_date', 'appointment'), ('location', 'location')):
        if document.get(key):
            value = _ltr(document[key]) if key in ('number', 'date', 'appointment_date') else _text(document[key])
            pdf.text_block(labels[label] + ': ' + value, 9)
    pdf.text_block(labels['currency'] + ': ' + currency, 9)
    pdf.ln(6)
    headings = ['#', labels['item'], labels['quantity'], labels['price'], labels['amount']]
    widths = [9, 83, 23, 31, 32]
    # The Arabic table starts with the item number on the right. Numeric values
    # retain their natural reading order inside each shaped cell.
    if language == 'ar':
        headings.reverse()
        widths.reverse()
    pdf.set_font('DejaVu', '', 9)
    pdf.set_text_color(*INK)
    pdf.set_draw_color(222, 229, 236)
    with pdf.table(
        col_widths=widths, line_height=5.5, padding=(3, 2),
        text_align=('R' if language == 'ar' else 'L'),
        headings_style=FontFace(emphasis='BOLD', color=(255, 255, 255), fill_color=NAVY),
        cell_fill_color=LIGHT, cell_fill_mode='ROWS', borders_layout='HORIZONTAL_LINES',
        repeat_headings=1,
    ) as table:
        table.row(headings)
        for index, line in enumerate(document.get('lines') or [], 1):
            description = _text(line.get('name'))
            if line.get('sku'):
                description += '\n' + _ltr(line['sku'])
            quantity = _number(line.get('quantity'))
            unit = line.get('unit_en') if language == 'en' else line.get('unit')
            unit = unit or line.get('unit')
            if unit:
                quantity += '\n' + _text(unit)
            # A valid product name/SKU can be longer than a page. Split only
            # the description into continuation rows rather than truncating it
            # or letting the table reject an oversized row. Prices appear once.
            chunks = [description]
            if len(description) > 500:
                wrapped = pdf.multi_cell(79, 5.5, description, dry_run=True, output='LINES')
                chunks = ['\n'.join(wrapped[start:start + 18])
                          for start in range(0, len(wrapped), 18)]
            for chunk_index, chunk in enumerate(chunks):
                row = ([str(index), chunk, quantity, _number(line.get('price'), True),
                        _number(line.get('total'), True)] if chunk_index == 0
                       else ['', chunk, '', '', ''])
                table.row(list(reversed(row)) if language == 'ar' else row)
    # Keep all totals together, moving to the next page when needed.
    if pdf.y + 51 > pdf.page_break_trigger:
        pdf.add_page()
    pdf.ln(7)
    for label, value in (
        (labels['subtotal'], document.get('subtotal')),
        (labels['discount'], document.get('discount')),
        (labels['tax'] + ' (' + _number(document.get('tax_rate')) + '%)', document.get('tax')),
    ):
        pdf.text_block(f'{label}: {_number(value, True)} {currency}', 10)
        pdf.ln(1)
    pdf.ln(2)
    pdf.set_fill_color(*TEAL)
    pdf.text_block(labels['total'] + ': ' + _number(document.get('total'), True) + ' ' + currency,
                   13, bold=True, color=(255, 255, 255), fill=True, padding=4)
    # Instructions are the server-created snapshot for the chosen service line.
    # They are customer-facing catalog content, not an arbitrary document note.
    # Product lines and empty methods must never expose internal notes here.
    methods = [line for line in document.get('lines') or []
               if line.get('item_type') == 'service' and _text(line.get('service_method'))]
    if methods:
        if pdf.y + 35 > pdf.page_break_trigger:
            pdf.add_page()
        pdf.ln(9)
        pdf.text_block(labels['service_method'], 14, bold=True, color=TEAL)
        pdf.ln(3)
        for line in methods:
            if pdf.y + 22 > pdf.page_break_trigger:
                pdf.add_page()
            pdf.set_fill_color(*LIGHT)
            pdf.text_block(line.get('name') or labels['item'], 11, bold=True,
                           color=NAVY, fill=True, padding=3)
            pdf.ln(2)
            pdf.text_block(line['service_method'], 9)
            pdf.ln(5)
    return bytes(pdf.output())
