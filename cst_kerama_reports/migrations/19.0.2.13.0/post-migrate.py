def migrate(cr, version):
    # fuel logs written before prices existed: their currency is the company's
    cr.execute("""
        UPDATE cst_fuel_log l SET currency_id = c.currency_id, rate = 1.0
          FROM res_company c
         WHERE c.id = l.company_id AND l.currency_id IS NULL
    """)
    # confirmed before the bill option: no bill was made, do not pretend one was
    cr.execute("UPDATE cst_fuel_log SET create_bill = FALSE WHERE state = 'done' AND bill_id IS NULL")
