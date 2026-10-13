{
    "name": "Khatdecor Product Names Without Codes",
    "summary": "Show products by name and variant only - no internal reference "
               "in front of them.",
    "description": """
Khatdecor Product Names Without Codes
=====================================

Odoo puts a product's internal reference in front of its name everywhere it is
shown - `[00011887] Kashmir LDSP`.  With five-digit references on thousands of
lookalike boards, a sales clerk reading a line sees the code before the goods,
and picking the wrong one off the dropdown is easy.

This addon drops the code from the displayed name, on products and on variants,
so a line reads `Kashmir (115076) LDSP (Koja)`.

Nothing else changes: the reference is still on the product form, still exported
and imported, and **still searchable** - typing a code or a barcode into a
product field finds the product exactly as before.
    """,
    "author": "Khatdecor",
    "category": "Inventory",
    "version": "19.0.1.1.0",
    "depends": ["product"],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
