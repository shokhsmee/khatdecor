{
    "name": "Khatdecor Avtomatik hisob-faktura",
    "summary": "Invoice what left the gate, bill what was received, and match the "
               "money already paid — so the P&L and debts follow the goods.",
    "description": """
Avtomatik hisob-faktura
=======================

* **Sotuv** — a delivery validated (the Jo'natish gate or the Delivery form)
  invoices at once what has left the warehouse and was not invoiced yet, and
  posts it. A partial trip invoices its own goods only.
* **Kassa** — a client payment no longer invoices the whole order: it settles
  the invoices that exist; money for goods not delivered yet stays as the
  client's advance and closes the invoice the moment the goods leave.
* **Xarid** — a receipt validated bills at once what was received and not
  billed yet (posted, dated the receipt day); a supplier prepayment closes it.
  A kassa payment to a supplier settles his open bills, oldest first.

Company switches in Settings ▸ Kassa.
    """,
    "author": "Khatdecor",
    "category": "Accounting",
    "version": "19.0.1.0.0",
    "depends": [
        "sale_stock",
        "purchase_stock",
        "cst_kerama_kassa",
        "cst_kerama_dispatch",
    ],
    "data": [
        "views/res_config_settings_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
}
