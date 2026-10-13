{
    "name": "Khatdecor Sale Receipt",
    "summary": "Print a POS-style receipt from a confirmed sales order.",
    "description": """
Kerama Sale Receipt
===================

Adds a **Chek chiqarish** (Print receipt) button to the sales order header that
appears once the quotation has been confirmed (state = *Sales Order*). Clicking
it opens a thermal, POS-style 80 mm receipt in a new browser tab and immediately
triggers the computer's print dialog for direct printing.
    """,
    "author": "Khatdecor",
    "category": "Sales",
    "version": "19.0.2.1.0",
    "depends": ["sale"],
    "data": [
        "views/sale_order_views.xml",
        "views/sale_receipt_templates.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
