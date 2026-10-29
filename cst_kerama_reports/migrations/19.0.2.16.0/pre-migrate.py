def migrate(cr, version):
    """Adopt the «3-shaxslar» tag the users already made (2026-10-27) instead
    of loading a second one with the same name."""
    cr.execute("""
        SELECT 1 FROM ir_model_data
         WHERE module = 'cst_kerama_reports' AND name = 'partner_category_third_party'
    """)
    if cr.fetchone():
        return
    cr.execute("""
        SELECT id FROM res_partner_category
         WHERE lower(trim(name->>'en_US')) IN ('3-shaxslar', '3-shaxs', '3 shaxslar')
         ORDER BY id LIMIT 1
    """)
    row = cr.fetchone()
    if row:
        cr.execute("""
            INSERT INTO ir_model_data (module, name, model, res_id, noupdate)
            VALUES ('cst_kerama_reports', 'partner_category_third_party', 'res.partner.category', %s, true)
        """, [row[0]])
