{
    "name": "Khatdecor Ombor oqimi",
    "summary": "Har bo'lim o'z omborida ishlaydi: xomashyo so'rovi, tayyor mahsulotni "
               "keyingi omborga avtomatik ko'chirish, ombor qabul qiluvchisi.",
    "description": """
Khatdecor Ombor oqimi
=====================

Omborlar zanjiri (2026-09-28 sxemasi)::

    Хом ашё омбори ──► Принтер цехи ──► Обой цехи ──► Таййор обой омбори
          │                                               │
          └──────────────► Янги пресс / Пресс эски ◄──────┘
                                    │
                                    ▼
                              Савдо омбори (tayyor mahsulot, sotuv)

* **Bo'lim** — ishlaydigan ombori, xomashyo omborlari va tayyor mahsulot ketadigan ombori.
* **Ishlab chiqarish buyurtmasi** bo'limning omborida ochiladi: xomashyo shu ombordan
  olinadi, tayyor mahsulot shu omborga tushadi.
* **Xomashyo so'rovi** — buyurtma tasdiqlanganda yetmagan xomashyo uchun xomashyo omboridan
  bo'lim omboriga ichki ko'chirish avtomatik yaratiladi.
* **Tayyor mahsulot** — natija kiritilganda (1-sort va 2-sort; brak emas) keyingi omborga
  ichki ko'chirish avtomatik yaratiladi.
* **Qabul qiluvchi** — har omborning o'z qabul qiluvchisi; shu omborga keladigan ichki
  ko'chirishlarga avtomatik yoziladi va faqat u tasdiqlaydi (cst_kerama_wh_control).
    """,
    "author": "Khatdecor",
    "category": "Inventory/Inventory",
    "version": "19.0.1.3.0",
    "depends": ["cst_kerama_shift", "cst_kerama_wh_control", "cst_kerama_shopfloor",
                "cst_kerama_sale_production", "sale_stock", "purchase_stock"],
    "data": [
        "views/stock_warehouse_views.xml",
        "views/department_views.xml",
        "views/mrp_production_views.xml",
        "views/stock_picking_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
