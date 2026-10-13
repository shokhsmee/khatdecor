{
    "name": "Khatdecor Sales → Production",
    "summary": "«Ishlab chiqarishga yuborish» on the sales order: stock check of the order's "
               "products, pick what to make, and raise the orders through the shared "
               "«Yangi buyurtma» dialog — they land in the department queue as new, not started.",
    "description": """
Khatdecor Sales → Production
============================

* **Send to production** (sales order header, confirmed orders): a wizard lists the
  order's products against the warehouse — ordered, delivered, in stock for this order,
  already in production, short — and ticks the lines that are short and have a bill of
  materials.
* **Send** opens the shared «Yangi buyurtma» dialog (Smena boshqaruvi) for each ticked
  product in turn: materials, operations and lines are shaped there. The manufacturing
  order is confirmed but not started, stamped with the sales order line, and appears in
  the queue of the department that runs its first operation — the manager checks it and
  presses «Boshlash» in the department window.
* The Project Hub's «Create / Open Project» buttons are hidden on the sales order.
    """,
    "author": "Khatdecor",
    "category": "Sales",
    "version": "19.0.1.0.1",
    "depends": ["sale_stock", "sale_mrp", "cst_kerama_shift", "cst_kerama_project"],
    "data": [
        "security/ir.model.access.csv",
        "wizard/send_production_views.xml",
        "views/sale_order_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cst_kerama_sale_production/static/src/sale_mo/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
