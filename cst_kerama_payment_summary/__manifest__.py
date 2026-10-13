{
    "name": "Kerama Sales Payment Summary",
    "summary": "Show Invoiced Amount, Waiting-for-approval payments (per currency) and Amount Due on the sales order.",
    "description": """
Kerama Sales Payment Summary
============================

Adds a small payment summary to the bottom of every sales order, mirroring the
group's other Odoo deployments:

* **Invoiced Amount** – total of the posted customer invoices for the order.
* **Waiting approval** (amber) – payments that are registered but still in the
  *In Process* state (received but not yet confirmed). Shown once per currency
  when several pending payments use different currencies, and only visible when
  at least one such payment exists.
* **Amount Due** (red) – the order total still owed (order total minus every
  payment already received, including the ones waiting for approval).
    """,
    "author": "Kerama City",
    "category": "Sales",
    "version": "19.0.1.0.0",
    "depends": ["sale", "account"],
    "data": [
        "views/sale_order_views.xml",
        "views/account_payment_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
