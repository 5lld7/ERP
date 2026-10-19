"""Company base currencies supported by the ERP's two-decimal money model.

Choosing a currency never performs an exchange-rate conversion. Once a journal
entry exists, changing its meaning would invalidate historical financial totals.
"""
import erp


_DEFINITIONS = (
    ('EGP', 'جنيه مصري', 'Egyptian pound', 'ج.م'),
    ('SAR', 'ريال سعودي', 'Saudi riyal', 'ر.س'),
    ('AED', 'درهم إماراتي', 'UAE dirham', 'د.إ'),
    ('USD', 'دولار أمريكي', 'US dollar', 'USD'),
    ('EUR', 'يورو', 'Euro', 'EUR'),
    ('GBP', 'جنيه إسترليني', 'Pound sterling', 'GBP'),
    ('QAR', 'ريال قطري', 'Qatari riyal', 'ر.ق'),
    ('CAD', 'دولار كندي', 'Canadian dollar', 'CAD'),
    ('AUD', 'دولار أسترالي', 'Australian dollar', 'AUD'),
    ('CHF', 'فرنك سويسري', 'Swiss franc', 'CHF'),
    ('MAD', 'درهم مغربي', 'Moroccan dirham', 'MAD'),
    ('DZD', 'دينار جزائري', 'Algerian dinar', 'DZD'),
)
CURRENCIES = tuple(dict(code=code, label_ar=ar, label_en=en, symbol_ar=symbol,
                        symbol_en=code) for code, ar, en, symbol in _DEFINITIONS)
_CODES = frozenset(currency['code'] for currency in CURRENCIES)
_ALIASES = {'ج.م': 'EGP', 'جنيه مصري': 'EGP', 'ر.س': 'SAR', 'ريال سعودي': 'SAR',
            'د.إ': 'AED', 'درهم إماراتي': 'AED', 'ر.ق': 'QAR', 'ريال قطري': 'QAR',
            '$': 'USD', '€': 'EUR', '£': 'GBP'}


def normalize_currency(value):
    text = str(value or '').strip()
    code = _ALIASES.get(text, text.upper())
    return code if code in _CODES else None


def currency_locked(db):
    return bool(db.execute('SELECT 1 FROM journal LIMIT 1').fetchone())


def currency_metadata(db, current=None):
    return {'currencies': [dict(currency) for currency in CURRENCIES],
            'currency_locked': currency_locked(db)}


def validate_currency_change(db, current, requested):
    """Validate inside the transaction that updates the settings row."""
    if requested == current:
        # Existing installations may have a custom label from the old free-text
        # field. Saving unrelated settings must continue to preserve it exactly.
        return current
    code = normalize_currency(requested)
    if not code:
        raise erp.BusinessError('العملة المحددة غير مدعومة')
    if currency_locked(db) and normalize_currency(current) != code:
        raise erp.BusinessError('لا يمكن تغيير العملة الأساسية بعد ترحيل عمليات مالية')
    return code


def currency_label(value, language='ar'):
    code = normalize_currency(value)
    currency = next((item for item in CURRENCIES if item['code'] == code), None)
    return currency['symbol_en' if language == 'en' else 'symbol_ar'] if currency else str(value)
