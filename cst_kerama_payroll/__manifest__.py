{
    "name": "Khatdecor Payroll & KPI",
    "summary": "Employee salary, bonuses, fines and KPI — posted to the ledger.",
    "description": """
Khatdecor Payroll & KPI
=======================

A payroll ledger built the way the accounting department already reads it: a
running account per employee, not a period-closed payslip.

**Ходимлар ойлиги буйича батафсил хисобот** — for any date range::

    Охирги колдик = Бошлангич колдик + Жами хисобланди - Жами ушланди

**Components** drive the report's columns.  *Ойлик суммаси*, *Ишбай иш хаки*,
*KPI бонуси*, *Накд аванс*, *Жарима*… are records, not fields, so a new bonus
type is a configuration change and the report widens by itself.

**Accounting** — nothing reaches the ledger until a period is confirmed.  On
posting, salary expense hits the P&L, the employee's balance sits on the
payable account, and advances leave through cash or bank.  The report's opening
and closing balances and the partner ledger are therefore the same number.

**Official and cash streams** run side by side on separate expense accounts.
Income tax, pension and social tax are computed on the official part only, at
rates configured per company — nothing is hard-coded.

KPI accrual from sales, manufacturing, unloading and manual entry is layered on
top of the same lines in the following phases.
    """,
    "author": "Khatdecor",
    "category": "Human Resources",
    "version": "19.0.1.2.0",
    "depends": ["hr", "account", "sale", "mrp", "mrp_workorder", "stock"],
    "data": [
        "security/payroll_groups.xml",
        "security/ir.model.access.csv",
        "data/payroll_component_data.xml",
        "views/payroll_component_views.xml",
        "views/product_views.xml",
        "views/sale_order_views.xml",
        "views/mrp_views.xml",
        "views/stock_picking_views.xml",
        "views/payroll_line_views.xml",
        "views/payroll_report_views.xml",
        "wizard/payroll_wizard_views.xml",
        "views/payroll_period_views.xml",
        "views/hr_employee_views.xml",
        "views/res_config_settings_views.xml",
        "views/payroll_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cst_kerama_payroll/static/src/payroll_report/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": True,
    "auto_install": False,
}
