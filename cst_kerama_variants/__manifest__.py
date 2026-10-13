{
    "name": "Khatdecor Mahsulot xarakteristikalari",
    "summary": "Ustki qismi, zichligi va o'lchami — mahsulot variantlari sifatida, "
               "1C'dagi «характеристика» o'rnida.",
    "description": """
Khatdecor Mahsulot xarakteristikalari
=====================================

The three characteristics the company tells its products apart by — the
surface finish (*Ustki qismi*), the paper density (*Zichligi*) and the sheet
size (*Uzunligi va eni*) — as Odoo product attributes in **instant** mode:
every value listed on a product is a variant of its own from that moment, so
each characteristic is a line of its own in every list, with its own stock and
prices. Only the values a product really comes in are listed, so a board with
two finishes has two variants, not the 18 × 9 × 2 cross-product.

Ships with:

* the three attributes and their values (noupdate — the accountants own them
  from here on);
* ``cst_characteristic`` on every product variant — the attribute values as
  one searchable, groupable text, shown on product and stock lists — and the
  same column on the warehouse quants;
* the same characteristic as a column on every document a product travels
  through — sale and purchase orders, invoices and bills, bills of materials,
  manufacturing orders, stock moves and quants — so nobody has to open a line
  to learn which variant it is about;
* a **Mahsulotlar (xarakteristika bo'yicha)** menu in Inventory, Sales and
  Purchase: the ordinary Products list shows one line per product, this one
  shows one line per characteristic, each with its own stock and prices;
* **Xarakteristika biriktirish**, a wizard reached from the product list: pick
  the products, say which values *the product you already have* carries and
  which other values it comes in. The existing product keeps its id, code,
  stock and history and simply becomes that variant; the other combinations
  are created at once, one line each.

Why the wizard adds one value per attribute first: Odoo re-creates variants
whenever attribute lines change, and a variant whose combination is no longer
valid is archived — with its stock. A line with a single value is the one case
Odoo writes onto the existing variant instead, so that is the door the wizard
walks the existing product through before opening the other values.
    """,
    "author": "Khatdecor",
    "category": "Inventory",
    "version": "19.0.3.2.0",
    "depends": ["product", "stock", "mrp", "sale_management", "purchase", "account"],
    "data": [
        "security/ir.model.access.csv",
        "data/product_attribute_data.xml",
        "views/product_views.xml",
        "views/document_views.xml",
        "views/second_grade_views.xml",
        "wizard/variant_assign_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
