{
    "name": "Khatdecor Purchase & Receipt Layout",
    "summary": "Xarid buyurtmasi: rasm, transport raqami, qabul xarajatlari; qabul sahifalari tartibi.",
    "description": """
Khatdecor Purchase & Receipt Layout
===================================

Xarid bo'limining so'rovi bo'yicha:

* **Xarid buyurtmasi** — «Yetkazib beruvchi havolasi» va «Kutilayotgan kelish
  vaqti» yashirildi; ombor (Yetkazib berish) yetkazib beruvchining tagiga
  ko'chdi; **Transport vositasi raqami** qo'shildi.  Sahifalar: Mahsulotlar,
  **Rasmlar** (narx kiritilishidan oldin ham yuklanadi), **Xarajatlar**,
  Qo'shimcha ma'lumotlar.
* Qabul (kirim) tasdiqlangach uning rasmlari, xarajatlari va transport raqami
  xarid buyurtmasida ham ko'rinadi — bir hujjatdan ikkinchisiga o'tib yurish
  shart emas.  Transport raqami buyurtmadan qabulga o'zi o'tadi.
* **Qabul** sahifalari tartibi: Operatsiyalar, Xarajatlar, Rasmlar,
  Yuk tushirish, Qo'shimcha ma'lumot, Eslatma.
    """,
    "author": "Khatdecor",
    "category": "Inventory/Purchase",
    "version": "19.0.1.2.0",
    "depends": [
        "purchase_stock",
        "cst_kerama_wh_control",
        "cst_kerama_landed_cost",
        "cst_kerama_payroll",
        "cst_kerama_project",
    ],
    "data": [
        "views/purchase_order_views.xml",
        "views/stock_picking_views.xml",
        "views/purchase_list_search_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cst_kerama_purchase_ux/static/src/po_lines_info/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
