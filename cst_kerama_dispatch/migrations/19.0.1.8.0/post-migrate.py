def migrate(cr, version):
    # dispatches left open on orders that were cancelled before the cancel hook existed
    cr.execute("""
        UPDATE cst_dispatch d SET state = 'cancel'
          FROM sale_order so
         WHERE so.id = d.sale_order_id AND so.state = 'cancel'
           AND d.state IN ('draft', 'ready')
    """)
