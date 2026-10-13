{
    "name": "Kerama Sales Full Payment",
    "summary": "One-click full payment from the sales order: create + post the "
    "invoice, register and confirm the payment, all linked together.",
    "description": """
Kerama Sales Full Payment
=========================

Adds a **To'liq to'lov** (Full payment) button to the sales order form. The
button opens a wizard reminiscent of the *Register Payment* flow on invoices:

* it shows the amount to pay in the chosen payment currency;
* it offers a journal (bank / cash) selection section.

When the user presses **To'lash**, the module:

#. creates and posts the customer invoice for the order (or posts the existing
   draft invoice);
#. registers the payment in full on that invoice through the standard
   ``account.payment.register`` machinery;
#. confirms (validates) the payment so it does not stay in *waiting approval*;
#. links the sales order, invoice and payment together and closes the wizard.
    """,
    "author": "Kerama City",
    "category": "Sales",
    "version": "19.0.1.0.0",
    "depends": ["sale", "account"],
    "data": [
        "security/ir.model.access.csv",
        "wizard/full_payment_wizard_views.xml",
        "views/sale_order_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
