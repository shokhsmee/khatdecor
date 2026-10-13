{
    "name": "Khatdecor Receipt Expenses (Landed Costs)",
    "summary": "Enter delivery, customs and other expenses straight on a receipt, "
               "bill each service provider and roll the cost into the goods.",
    "description": """
Khatdecor Receipt Expenses
==========================

Adds an **Expenses** page to every receipt (kirim).  Each line records the
service provider, what the expense was for, its currency and rate, and how the
amount should be spread over the goods that arrived.

Pressing **Add to Cost** then does three things in one go:

* a **vendor bill** is created and posted per service provider and currency, so
  the debt shows up in Accounting and in the partner ledger;
* a **landed cost** document spreads the amounts over the received goods, either
  *by value* (a product worth twice as much carries twice the freight) or
  *by quantity* (every unit carries the same share);
* the **average cost** of each product is recalculated, so 2 000 boards bought
  at 8 $ with 16 000 $ of freight are worth 16 $ apiece from then on.

The expense account is debited by the bill and credited by the landed cost, so
it nets to zero and the money ends up where it belongs: in stock valuation.

Only works on receipts of a company valued at average cost or FIFO with
perpetual valuation - with standard costing there is no cost to correct.
    """,
    "author": "Khatdecor",
    "category": "Inventory",
    "version": "19.0.1.0.0",
    "depends": ["stock_landed_costs", "purchase_stock", "account"],
    "data": [
        "security/ir.model.access.csv",
        "data/landed_cost_products.xml",
        "views/cst_picking_expense_views.xml",
        "views/stock_picking_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
