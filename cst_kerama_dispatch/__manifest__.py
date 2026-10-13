{
    "name": "Khatdecor Jo'natish",
    "summary": "Barcode-style dispatch app: the warehouse prepares a sales order, "
               "the gate checks it line by line, the differences go back to the order.",
    "description": """
Jo'natish (dispatch)
====================

* **Ombor** — pick a confirmed sales order, see how much of each product has to
  leave, change the quantities, add extra products (scan or search), then mark
  the order «Jo'natishga tayyor».
* **Eshik** — the gate guard opens a ready order and checks every line by
  scanning or tapping. On approval the sales order is updated (extra / fewer
  quantities, extra products), the delivery is validated with exactly those
  quantities, and an extra invoice / credit note is posted when the order had
  already been invoiced.

A dedicated access role «Jo'natish (ombor va eshik)» sees this app only.
    """,
    "author": "Khatdecor",
    "category": "Inventory",
    "version": "19.0.1.3.0",
    "depends": [
        "sale_stock",
        "hr",
        "barcodes",
        "cst_kerama_wh_control",
        "cst_kerama_roles",
        "cst_kerama_sale_receipt",
        "cst_kerama_variants",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/dispatch_views.xml",
        "views/waybill_templates.xml",
        "data/role_data.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cst_kerama_dispatch/static/src/app/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": True,
}
