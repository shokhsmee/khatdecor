{
    "name": "Kerama Dynamic Dashboard",
    "summary": "Dynamic Sales / Accounting / Debts / Inventory dashboards for Kerama.",
    "description": """
Kerama Dynamic Dashboard
========================

A custom OWL dashboard application with four sub-dashboards:

* **Sales** – KPIs (total sales, order count, debt due, cash in, m² sold),
  charts (sales over time, top customers, top products, by salesperson,
  by currency, status funnel) and a rich filter bar.
* **Accounting** – (planned)
* **Debts** – (planned, reuses the sale order Amount Due logic)
* **Inventory** – (planned)

All figures are shown split by currency (UZS / USD) and can be scoped to one or
more companies.
    """,
    "author": "Khatdecor",
    "category": "Productivity",
    "version": "19.0.1.2.0",
    "depends": ["sale", "account", "stock", "uom", "cst_kerama_payment_summary"],
    "data": [
        "views/dashboard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cst_kerama_dashboard/static/src/dashboard/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": True,
    "auto_install": False,
}
