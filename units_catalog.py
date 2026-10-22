"""Practical bilingual units for cleaning, pest control and stock management.

These are labels, not automatic conversion rules. Companies may keep adding
their own units and English names. Seeding never replaces custom unit names or
an English label entered by a user, and never changes referenced unit IDs.
"""


_UNIT_DEFINITIONS = (
    ('piece', 'قطعة', 'Piece'),
    ('pair', 'زوج', 'Pair'),
    ('set', 'طقم', 'Set'),
    ('dozen', 'دستة', 'Dozen'),
    ('unit', 'وحدة', 'Unit'),
    ('meter', 'متر', 'Metre'),
    ('linear_meter', 'متر طولي', 'Linear metre'),
    ('centimeter', 'سنتيمتر', 'Centimetre'),
    ('millimeter', 'مليمتر', 'Millimetre'),
    ('kilometer', 'كيلومتر', 'Kilometre'),
    ('inch', 'بوصة', 'Inch'),
    ('foot', 'قدم', 'Foot'),
    ('yard', 'ياردة', 'Yard'),
    ('square_meter', 'متر مربع', 'Square metre (m²)'),
    ('square_centimeter', 'سنتيمتر مربع', 'Square centimetre (cm²)'),
    ('square_foot', 'قدم مربع', 'Square foot (ft²)'),
    ('square_yard', 'ياردة مربعة', 'Square yard (yd²)'),
    ('hectare', 'هكتار', 'Hectare'),
    ('acre', 'أكر', 'Acre'),
    ('feddan', 'فدان', 'Feddan'),
    ('cubic_meter', 'متر مكعب', 'Cubic metre (m³)'),
    ('cubic_centimeter', 'سنتيمتر مكعب', 'Cubic centimetre (cm³)'),
    ('cubic_foot', 'قدم مكعب', 'Cubic foot (ft³)'),
    ('liter', 'لتر', 'Litre'),
    ('milliliter', 'ملليلتر', 'Millilitre'),
    ('gallon', 'جالون', 'Gallon'),
    ('us_gallon', 'جالون أمريكي', 'US gallon'),
    ('imperial_gallon', 'جالون إمبراطوري', 'Imperial gallon'),
    ('kilogram', 'كيلوجرام', 'Kilogram'),
    ('gram', 'جرام', 'Gram'),
    ('milligram', 'مليجرام', 'Milligram'),
    ('tonne', 'طن', 'Tonne'),
    ('pound', 'رطل', 'Pound'),
    ('ounce', 'أونصة', 'Ounce'),
    ('container', 'عبوة', 'Container'),
    ('package', 'حزمة', 'Package'),
    ('box', 'علبة', 'Box'),
    ('carton', 'كرتونة', 'Carton'),
    ('bag', 'كيس', 'Bag'),
    ('sack', 'جوال', 'Sack'),
    ('roll', 'لفة', 'Roll'),
    ('bottle', 'زجاجة', 'Bottle'),
    ('can', 'علبة معدنية', 'Can'),
    ('bucket', 'دلو', 'Bucket'),
    ('drum', 'برميل', 'Drum'),
    ('tank', 'خزان', 'Tank'),
    ('spray', 'بخاخ', 'Spray'),
    ('tablet', 'قرص', 'Tablet'),
    ('capsule', 'كبسولة', 'Capsule'),
    ('dose', 'جرعة', 'Dose'),
    ('trap', 'مصيدة', 'Trap'),
    ('bait_station', 'محطة طُعم', 'Bait station'),
    ('bait', 'طُعم', 'Bait'),
    ('minute', 'دقيقة', 'Minute'),
    ('hour', 'ساعة', 'Hour'),
    ('day', 'يوم', 'Day'),
    ('week', 'أسبوع', 'Week'),
    ('month', 'شهر', 'Month'),
    ('year', 'سنة', 'Year'),
    ('visit', 'زيارة', 'Visit'),
    ('session', 'جلسة', 'Session'),
    ('service', 'خدمة', 'Service'),
    ('room', 'غرفة', 'Room'),
    ('apartment', 'شقة', 'Apartment'),
    ('villa', 'فيلا', 'Villa'),
    ('building', 'مبنى', 'Building'),
    ('floor', 'طابق', 'Floor'),
    ('bathroom', 'حمام', 'Bathroom'),
    ('kitchen', 'مطبخ', 'Kitchen'),
    ('carpet', 'سجادة', 'Carpet'),
    ('sofa', 'أريكة', 'Sofa'),
    ('seat', 'مقعد', 'Seat'),
    ('window', 'نافذة', 'Window'),
)

BUILTIN_UNITS = tuple(dict(code=code, name=arabic, name_en=english)
                      for code, arabic, english in _UNIT_DEFINITIONS)


def seed_units(db):
    """Add missing catalog labels inside the caller's migration transaction.

    A single read plus a bulk insert keeps initial migrations efficient on
    Turso. An old matching Arabic label is adopted without replacing its ID.
    Duplicate/custom labels remain separate and keep their original values.
    """
    rows = db.execute('SELECT id,name,code,name_en FROM units ORDER BY id').fetchall()
    by_code = {row[2]: row for row in rows if row[2]}
    available = {}
    for row in rows:
        if not row[2]:
            available.setdefault(row[1], row)
    missing = []
    for unit in BUILTIN_UNITS:
        current = by_code.get(unit['code'])
        if current is not None:
            # A renamed built-in is now company data, so do not add an old
            # English name back to it. Users can supply their own translation.
            if current[1] == unit['name'] and not current[3]:
                db.execute('UPDATE units SET name_en=? WHERE id=?', (unit['name_en'], current[0]))
            continue
        current = available.pop(unit['name'], None)
        if current is not None:
            db.execute("UPDATE units SET code=?,name_en=CASE WHEN name_en IS NULL OR name_en='' THEN ? ELSE name_en END WHERE id=?",
                       (unit['code'], unit['name_en'], current[0]))
        else:
            missing.append(unit)
    if missing:
        placeholders = ','.join('(?,?,?)' for _ in missing)
        parameters = tuple(value for unit in missing for value in
                           (unit['name'], unit['code'], unit['name_en']))
        db.execute('INSERT INTO units(name,code,name_en) VALUES ' + placeholders, parameters)
