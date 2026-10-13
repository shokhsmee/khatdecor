{
    "name": "Khatdecor Finance — cash, bank and statements",
    "summary": "Keeps the cash and bank configuration honest so the standard "
               "P&L, balance sheet and cash flow statement have a real basis.",
    "description": """
Khatdecor Finance
=================

This module adds no accounting of its own.  Everything is standard Odoo:
payments, outstanding accounts, bank statements, the Excel/CSV statement
importer and the standard financial reports.  What it does is keep the
configuration those depend on from silently drifting.

**Liquidity journals are configured on creation.**  A bank or cash journal
whose payment methods carry no outstanding account produces payments with *no
journal entry at all* — the money simply never reaches the books.  That is a
legitimate Odoo flow (the bank statement becomes the only source of truth) but
it is not how a company with a cash drawer works, and it is impossible to
notice until a report is short.  So:

* a **cash** journal gets its own account as the outstanding account — the
  drawer is the destination, the payment lands there in one step and is marked
  paid straight away;
* a **bank** journal (and the Click / Payme aggregators, whose money settles
  later) keeps the two-step flow through Outstanding Receipts / Payments, and
  clears when the imported statement is reconciled.

**The statement import has one obvious door.**  Odoo's importer only offers
the Debit / Credit / Cumulative Balance columns when it is opened from a
journal; reached through the generic *Import a File* screen the same file is
read as plain journal entries and every row fails as unbalanced.  A wizard
under *Accounting > Transactions > Bank vipiskasini yuklash* asks for the
journal and the file and hands both to the standard importer.

**The columns arrive already matched.**  base_import only learns a heading
after a successful import, so the first file is always mapped by hand.  The
usual Uzbek, Russian and English headings are seeded into `base_import.mapping`
up front - Sana / Дата / Date, Debet / Дебет / Debit, Qoldiq / Остаток /
Balance and so on.

**The statement import's "Test" button works.**  Testing an Excel file used to
die with *Record does not exist*: the standard importer rolls the rows back on
a dry run, then tries to wrap those very rows in a statement.  Checking the
file before importing it is exactly when an accountant needs an answer, so the
dry run now validates the rows and skips the wrapper.
    """,
    "author": "Khatdecor",
    "category": "Accounting/Accounting",
    "version": "19.0.1.0.0",
    "depends": ["account", "account_bank_statement_import_csv"],
    "data": [
        "security/ir.model.access.csv",
        "data/bank_statement_import_mappings.xml",
        "wizard/bank_statement_import_wizard_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
