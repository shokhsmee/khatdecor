{
    "name": "Kerama Sales Return",
    "summary": "Return / refund (Qaytarish) from the sales order: credit note, "
    "refund payment and stock return back to inventory in one wizard.",
    "description": """
Kerama Sales Return (Qaytarish / Возврат)
=========================================

Adds a **Qaytarish** button to confirmed sales orders. The button opens a
wizard split in two groups:

* **To'lov** (payment): the amount already paid, the amount to refund
  (*qaytariladigan summa*) and the payment journal;
* **Mahsulot qaytarish** (products): one line per delivered product, showing
  the delivered quantity and the quantity to send back.

On **Tasdiqlash** the module:

#. creates and posts a customer credit note (``out_refund``) for the returned
   lines;
#. registers and confirms an outbound refund payment on the chosen journal;
#. creates and validates a return picking so the returned products go back
   into inventory.

The button is only visible once the sales order is confirmed.
    """,
    "author": "Kerama City",
    "category": "Sales",
    "version": "19.0.1.0.0",
    "depends": ["sale", "account", "stock", "sale_stock", "stock_delivery"],
    "data": [
        "security/ir.model.access.csv",
        "wizard/return_wizard_views.xml",
        "views/sale_order_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cst_kerama_sale_return/static/src/scss/return_wizard.scss",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
