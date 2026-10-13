{
    "name": "Khatdecor Product Price Update",
    "summary": "Mass price update from the product list: Excel template download "
               "and upload matched on barcode, prices entered in USD, and "
               "bulk +/- adjustment by percent or amount.",
    "description": """
Khatdecor Product Price Update
==============================

Adds **Maxsulot narxlarini yangilash** to the *Actions* menu of the product
list (both templates and variants).  Select the products, open the wizard and
choose what to update:

* **Qaysi narx** – *Sotish narxi* (``list_price``) or *Tannarx*
  (``standard_price``, per company).
* **Valyuta** – the company currency, or **USD**: every figure typed in the
  file or in the wizard is read as dollars and converted with the rate shown
  (defaulted from the currency rate of the chosen date, editable).

**Excel** tab

#. *Shablon yuklab olish* exports the selected products to an ``.xlsx``
   sheet – barcode, name, internal reference, unit, current price and a
   *Yangi narx* column pre-filled with the current price.
#. Fill in the new prices, pick the file and press *Narxlarni yuklash*.

Products are matched **on barcode**, so the other columns can be reordered or
edited freely.  Valid rows are applied and a report lists every row that was
skipped (unknown barcode, empty or non-numeric price) together with the rows
whose price did not change.  ``.xlsx`` and ``.csv`` files are accepted.

**Ommaviy o'zgartirish** tab

Raise or lower the price of every selected product by a percentage or by a
fixed amount.  *Ko'rish* shows the old and new price per product before
anything is written.

Only members of *Product Manager* (``product.group_product_manager``) see the
action.
    """,
    "author": "Khatdecor",
    "category": "Inventory",
    "version": "19.0.1.0.0",
    "depends": ["product"],
    "data": [
        "security/ir.model.access.csv",
        "wizard/product_price_update_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cst_kerama_product_price/static/src/scss/price_update_wizard.scss",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
