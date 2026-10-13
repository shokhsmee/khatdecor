{
    "name": "Khatdecor Access Roles",
    "summary": "The eleven Khatdecor job roles for the Access Roles app, "
               "with their group matrix and the payroll/accounting menus hidden.",
    "description": """
Khatdecor Access Roles
======================

Ships the job roles of the company as **data** for Cybrosys' *Access Roles*
app, so a new user is set up by picking one role instead of ticking group
boxes by hand:

1.  Administrator — every department.
2.  Rahbar — sees dashboards, reports, sales, purchase, cash and manufacturing.
3.  Sotuv bo‘limi boshlig‘i — the sales department, its reports, stock on hand
    per warehouse, customer invoices.
4.  Sotuv menejeri — the sales window and the projects behind their own deals.
5.  Nazoratchi — watches every operational process, finance and sales
    included; the whole interface is read-only for this role.
6.  HR — the HR department (employees, attendance, expenses).
7.  Bosh omborchi — every warehouse, transfers between them, outgoing goods.
8.  Ishlab chiqarish menejeri — manufacturing.
9.  Omborchi — one warehouse only, hands materials to production.
10. Buxgalter — invoices, accounting, sales and purchase.
11. Kassir — sales and invoices.

**Oylik and Buxgalteriya hisobi stay out of sight** for every role except
Kassir, Buxgalter, Rahbar and Administrator. The underlying access rights are
*not* taken away — the menus are hidden through the role's Role Management
record, exactly as the Access Roles app is meant to do it.

Three defects in the Access Roles app are fixed here, because the roles above
do not work without the fixes:

* ``access.role`` wrote ``groups_ids`` on ``res.users``, a field Odoo 19
  renamed to ``group_ids`` — editing the groups of a role that already had
  users raised a ValueError.
* ``load_menus`` was re-cached per *group set* instead of per user, so two
  users holding different roles but the same groups shared one menu tree and
  the hidden menus leaked. The cache is restored to Odoo's per-user key.
* Nothing cleared the menu cache when a role or a Role Management record
  changed, so hiding a menu only took effect after a restart.

It also tightens the app's own access rights: every internal user could write
to ``access.role``, which meant any user could add *Settings / Administrator*
to their own role. Reading stays open (the menu filter needs it), writing is
now limited to the Access Role administrator group.

**Not covered on purpose** — which companies a user may enter stays a per-user
setting (``Allowed Companies``). Warehouses here belong to one company each,
so *Omborchi* is pinned to a single warehouse by giving that user a single
company, while *Bosh omborchi* and *Rahbar* get all of them.
    """,
    "author": "Khatdecor",
    "category": "Security",
    "version": "19.0.1.4.0",
    "depends": [
        "access_roles",
        "cst_kerama_kassa",
        "base",
        "mail",
        "product",
        "analytic",
        "sales_team",
        "sale_management",
        "purchase",
        "stock",
        "mrp",
        "quality",
        "account",
        "accountant",
        "hr",
        "hr_attendance",
        "hr_expense",
        "project",
        "spreadsheet_dashboard",
        "cst_kerama_payroll",
        "cst_kerama_wh_control",
        "cst_kerama_dashboard",
        "cst_kerama_reports",
        "cst_kerama_shift",
        "muk_product",
    ],
    "data": [
        "security/access_roles_acl.xml",
        "data/access_role_data.xml",
        "data/role_management_data.xml",
        "views/sale_invoice_menu.xml",
        "views/role_management_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
