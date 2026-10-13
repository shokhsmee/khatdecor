{
    "name": "Khatdecor Warehouse Controls",
    "summary": "Photo proof on receipts and scraps, a named receiver on internal "
               "transfers, driver and vehicle details on receipts and deliveries, "
               "and a ready-to-validate badge on the transfer cards.",
    "description": """
Khatdecor Warehouse Controls
============================

* **Receipts (kirim)** – a photo of the goods must be attached before the
  receipt can be validated, and validating always books the full demanded
  quantity into the warehouse when nothing was counted by hand.
* **Scrap (hisobdan chiqarish)** – a scrap order cannot be closed without a
  photo.
* **Internal transfers (ombordan omborga)** – a *Receiver* must be named, and
  only that person can validate the transfer.
* **Receipts and deliveries** – free-text *Driver*, *Car Model* and *Car
  Number* fields record the vehicle that brought or took the goods.  They are
  hidden on internal transfers.
* **Transfer cards** – show whether every line has been confirmed; a transfer
  whose lines are all confirmed turns green and is flagged ready to validate.

The rules apply everywhere a transfer is validated, the Barcode app included.
Members of *Warehouse Supervisor* may override them.
    """,
    "author": "Khatdecor",
    "category": "Inventory",
    "version": "19.0.1.9.0",
    "depends": ["stock", "stock_barcode"],
    "data": [
        "security/wh_control_groups.xml",
        "security/ir.model.access.csv",
        "views/stock_picking_views.xml",
        "views/stock_scrap_views.xml",
        "views/stock_move_line_views.xml",
        "views/stock_barcode_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cst_kerama_wh_control/static/src/scss/**/*",
            "cst_kerama_wh_control/static/src/barcode/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
