{
    "name": "Khatdecor Negative Balance Guard",
    "summary": "Never let warehouse stock or a cash box go negative.",
    "description": """
Khatdecor Negative Balance Guard
================================

**Warehouse** – a delivery, an internal transfer, a scrap or a manufacturing
order can no longer take more of a product out of an internal location than is
actually there. The attempt is refused with the product, the location and the
missing quantity spelled out.

Virtual locations (customers, suppliers, production, inventory loss) are left
alone: those are negative by design in Odoo's double-entry stock model.

**Cash box** – posting a journal entry that would push a cash account below
zero is refused, so a cash desk can never pay out money it does not hold.
Which accounts are watched is driven by the *Prevent Negative Balance* flag on
the journal, switched on for cash journals by default.

**Overrides** – two groups, *Allow Negative Stock* and *Allow Negative Cash*,
let named users bypass the guard (stock takes, corrections, opening balances).
Code can pass ``cst_allow_negative=True`` in the context for data migrations.
    """,
    "author": "Khatdecor",
    "category": "Inventory",
    "version": "19.0.1.0.0",
    "depends": ["stock", "mrp", "account"],
    "data": [
        "security/no_negative_groups.xml",
        "views/account_journal_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
