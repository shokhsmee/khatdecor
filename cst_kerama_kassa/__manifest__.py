{
    "name": "Khatdecor Kassa",
    "summary": "Cash desk app: open / close / confirm the cash day, cash in and out, "
               "client payments with or without a sales order, and settling client "
               "money against their sales order debts.",
    "description": """
Khatdecor Kassa
===============

* **Kassa** — one card per cash journal with its live balance and today's state.
* **Cash day** — the cashier opens the day, receives and pays money, counts the
  cash and closes the day; a manager confirms it. A confirmed day is locked and
  the counted difference is posted to the cash difference account.
* **Operations** — client payment (always lowers the client's debt, with or
  without a sales order), supplier payment, client refund, expense and other
  income by category.
* **Settlement (moslash)** — the client's unallocated money is applied to his
  sales order debts, oldest first (the order is invoiced when needed); the rest
  stays as an advance. Every allocation is recorded and can be undone.
* **Client accounts** — per client: order debt, advance, balance, payments,
  allocations.
    """,
    "author": "Khatdecor",
    "category": "Accounting",
    "version": "19.0.1.6.0",
    "depends": ["mail", "account", "sale", "hr", "base_setup", "cst_kerama_payment_summary", "cst_kerama_sale_receipt",
                "cst_kerama_payroll"],
    "data": [
        "security/kassa_security.xml",
        "security/ir.model.access.csv",
        "data/kassa_data.xml",
        "report/kassa_report.xml",
        "views/kassa_receipt_templates.xml",
        "views/kassa_views.xml",
        "views/kassa_day_views.xml",
        "views/kassa_operation_views.xml",
        "views/kassa_category_views.xml",
        "views/kassa_allocation_views.xml",
        "views/partner_balance_views.xml",
        "wizard/day_open_views.xml",
        "wizard/day_close_views.xml",
        "wizard/reconcile_wizard_views.xml",
        "views/res_partner_views.xml",
        "views/sale_order_views.xml",
        "views/res_config_settings_views.xml",
        "data/kassa_setup.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cst_kerama_kassa/static/src/scss/kassa.scss",
        ],
    },
    "post_init_hook": "post_init_hook",
    "license": "LGPL-3",
    "installable": True,
    "application": True,
    "auto_install": False,
}
