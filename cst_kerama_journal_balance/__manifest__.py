{
    "name": "Khatdecor Journal Balance on the Overview",
    "summary": "Show what is left in every bank, cash, sale and purchase "
               "journal on the Accounting Overview card.",
    "description": """
Khatdecor Journal Balance
=========================

Odoo only prints a bank or cash journal's *Balance* once that journal has a
statement or a direct payment on it; a journal whose money is still sitting in
the outstanding accounts shows nothing at all, so the overview cannot answer the
one question it is opened for - how much is in there.

This addon puts a **Balance** line on every card:

* **Bank, cash and credit** - everything posted to the journal's own account
  plus its outstanding payment and receipt accounts, in the journal's currency.
  Always shown, even at zero.
* **Sale and purchase** - what is still owed on the journal's posted invoices
  and bills.
    """,
    "author": "Khatdecor",
    "category": "Accounting",
    "version": "19.0.1.0.0",
    "depends": ["account"],
    "data": ["views/account_journal_dashboard_views.xml"],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
