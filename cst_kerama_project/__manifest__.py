{
    "name": "Khatdecor Project Hub",
    "summary": "Make Project the hub: link sales, purchases and expenses to a project "
               "and see income (paid/due), purchases, expenses and margin on a dashboard.",
    "description": """
Khatdecor Project Hub (Phase 1)
===============================

Turns *Project* into the centre of the business:

* **Sales** – a *Create Project* / *Connect Project* button on the sale order.
  Income flows from the project's linked sale orders.
* **Purchases & Expenses** – a *Project* field on purchase orders and expenses.
  Setting it auto-tags the project's analytic account, so both this module's
  figures and Odoo's native Project Profitability panel stay in sync.
* **Project KPIs** – income, amount paid, amount due, purchases, expenses and
  margin, plus smart buttons to the underlying documents.
* **Dashboard** – an OWL dashboard summarising the above across all projects,
  reusing the group's existing dashboard components.
* **Material Requests (MRF)** – from a project, check the sale-order needs
  against warehouse stock (BoM-aware) and raise a request for the shortage:
  submit → approve → distribute to purchasers → create RFQs tagged to the
  project. A *Materials* page on the project tracks where each product is
  (stock per location) and its purchase status.
* **Manufacturing** – a sold product that has a bill of materials becomes a
  *Manufacture* line on the request and turns into a manufacturing order
  linked to the project, while its components become *Buy* lines. The project
  reports what was consumed and what is ready.
* **Start Manufacturing** – when every component of a request is free in the
  warehouse, the project offers a *Start Manufacturing* wizard: keep only the
  operations the order really needs, split each of them over the work centers
  with their own quantities, and name the responsible manager and the workers
  for every slice. One manufacturing order per product is raised, carrying
  exactly those work orders.
* **Create Manufacturing Order** – as soon as every component a project still
  has to produce is free in the warehouse, whether it was bought or was there
  all along, the project offers Odoo's own manufacturing form already filled
  in. No material request is needed: the plan is read from the confirmed sale
  orders when there is none. While something is missing the button stays away
  and the Manufacturing page says what is short, free against needed.
* **Project Hub** – each project has its own dashboard gathering its sales,
  purchases, manufacturing, expenses and material requests, with period,
  date-range and draft filters.
* **Every figure in any currency** – a project is read in the currency chosen
  on it, each document converted at the rate of its own date, with what the
  documents themselves say kept beside the total. Both dashboards have a
  currency picker of their own, and a material request can be priced in the
  currency it will be bought in, raising an RFQ that speaks it.
    """,
    "author": "Khatdecor",
    "category": "Project",
    "version": "19.0.5.0.0",
    "depends": [
        "sale_project",
        "purchase",
        "hr_expense",
        "stock",
        "mrp",
        "mrp_workorder",
        "project_mrp",
        "account",
        "analytic",
        "cst_kerama_dashboard",
        "cst_kerama_payment_summary",
        "cst_kerama_variants", "cst_kerama_shift",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "views/sale_order_views.xml",
        "views/purchase_order_views.xml",
        "views/hr_expense_views.xml",
        "views/material_request_views.xml",
        "views/manufacture_wizard_views.xml",
        "views/mrp_workorder_views.xml",
        "views/project_views.xml",
        "views/project_kanban_views.xml",
        "views/dashboard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cst_kerama_project/static/src/project_dashboard/**/*",
            "cst_kerama_project/static/src/project_hub/**/*",
            "cst_kerama_project/static/src/project_kanban/**/*",
            "cst_kerama_project/static/src/mo_button/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
