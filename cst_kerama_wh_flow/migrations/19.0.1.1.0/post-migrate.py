"""Each warehouse takes the colour its operations already carry (the most common one)."""


def migrate(cr, version):
    cr.execute("""
        UPDATE stock_warehouse w SET cst_color = s.color
          FROM (SELECT DISTINCT ON (warehouse_id) warehouse_id, color
                  FROM stock_picking_type
                 WHERE warehouse_id IS NOT NULL AND COALESCE(color, 0) <> 0
                 GROUP BY warehouse_id, color
                 ORDER BY warehouse_id, count(*) DESC, color) s
         WHERE s.warehouse_id = w.id
    """)
