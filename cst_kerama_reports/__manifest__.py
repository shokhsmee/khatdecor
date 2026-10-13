{
    "name": "Khatdecor Xisobotlar",
    "summary": "One Xisobotlar app that gathers every report the company reads — "
               "Odoo's own where they exist, purpose-built where they do not.",
    "description": """
Khatdecor Xisobotlar
====================

A single **Xisobotlar** app, split into categories, so nobody has to remember
which Odoo app a figure lives under. Wherever Odoo already ships the report,
the menu simply points at Odoo's own action — same screen, same filters, same
pivot and graph views, nothing reimplemented:

* **Moliya** — Foyda va zarar, Balans, Pul oqimi, Boshqaruv xulosasi,
  Bosh kitob, Aylanma balans (``account_reports``).
* **Mijozlar** — akt sverka, qarzdorlik yoshi, kontragent kitobi, savdo tahlili.
* **Ta'minotchilar / 3-shaxslar** — qarz yoshi, xarid tahlili.
* **Savdo** — savdo tahlili kesimlari, **mahsulot foyda/zarari**
  (``product_margin``), hisob-faktura tahlili.
* **Ombor** — qoldiqlar, kirim/chiqim tarixi, harakatlar tahlili,
  **rulon va partiyalar** (lots), **min/max** (reordering rules), sanadagi
  qoldiq, ombor samaradorligi.
* **Ishlab chiqarish** — ishlab chiqarish tahlili, ish buyruqlari, OEE va
  ishlab chiqarishga berilgan / undan qaytgan materiallar harakati.

And six reports Odoo does not have, built to the shape the company already
uses on paper:

1.  **Mijozning oxirgi operatsiyasi** — every customer with their last
    movement, how long they have been quiet (sorted by that) and what they
    owe. Double-clicking the customer opens their akt sverka; double-clicking
    the movement opens the document behind it.
2.  **Omborlar hisoboti (rasmli)** — the warehouse sheet with the product
    photo, characteristic, opening balance, in, out and closing balance,
    grouped company ▸ ombor ▸ kategoriya ▸ tovar.
3.  **Yoqilg'i hisoboti** — fuel in and out with a running balance, and per
    machine what it burned, how far it drove and the ratio between the two.
    Fuel is an ordinary stocked product, so issuing it moves real stock.
4.  **Ta'minotchilar harakati** and **3-shaxslar harakati** — opening
    qarzimiz/haqqimiz, the turnover of the period and the closing balance,
    per counterparty and per currency. Same shape, two separate reports.
5.  **Ta'minotchi / 3-shaxs akt sverkasi** — the counterparty card: every
    document of the period with the balance before and after it, per currency.
6.  **Mahsulot narx oralig'i** — the lowest and the highest price each product
    went out to a customer and came in from a supplier, with the quantity and
    the document count behind it.

Second wave (19.0.2): **Rahbar oynasi** (cash position, today's and the
month's flows, debts both ways, thirty days of cash as a line — every card
opens its detail); an **Oylik** category over the payroll app's own running
account plus the employee card, the bonus/penalty sheet and the KPI sheet;
a **Kassa** category — pullar harakati per cash box and bank account,
expenses by account group, only-through-the-cash-desk or all; and for the
warehouse the **detailed ledger** (Excel-first, 31 columns as the workbook it
replaces), the write-off list, the reviziya result sheet and the norm-versus-
actual consumption sheet per manufacturing order.
    """,
    "author": "Khatdecor",
    "category": "Reporting",
    "version": "19.0.2.9.0",
    "depends": [
        "base",
        "account",
        "account_reports",
        "accountant",
        "product",
        "product_margin",
        "sale",
        "sale_management",
        "purchase",
        "stock",
        "stock_account",
        "sale_stock",
        "stock_enterprise",
        "mrp",
        "mrp_account_enterprise",
        "uom",
        "hr",
        "cst_kerama_payroll",
        "cst_kerama_dashboard",
        "cst_kerama_variants",
        "account_asset",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/reports_security.xml",
        "data/fuel_product_data.xml",
        "data/partner_category_data.xml",
        "report/report_actions.xml",
        "report/report_actions2.xml",
        "report/report_actions3.xml",
        "report/partner_movement_template.xml",
        "report/partner_statement_template.xml",
        "report/warehouse_report_template.xml",
        "report/fuel_report_template.xml",
        "report/payroll_templates.xml",
        "report/cash_templates.xml",
        "report/stock_templates.xml",
        "report/stock_ledger_template.xml",
        "report/extra_templates.xml",
        "views/partner_last_operation_views.xml",
        "views/product_price_range_views.xml",
        "views/fuel_views.xml",
        "views/production_moves_actions.xml",
        "views/wizard_views.xml",
        "views/wizard_views2.xml",
        "views/wizard_views3.xml",
        "views/director_dashboard_views.xml",
        "views/reports_menus.xml",
        "views/menus2.xml",
        "views/menus3.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cst_kerama_reports/static/src/last_operation/last_operation_list.js",
            "cst_kerama_reports/static/src/director_dashboard/*",
            "cst_kerama_reports/static/src/report_filter_bar/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": True,
    "auto_install": False,
}
