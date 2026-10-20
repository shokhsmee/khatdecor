{
    "name": "Khatdecor Ishlab chiqarish zayafkalari",
    "summary": "Sotuvdagi buyurtmalarning omborda yetmayotgan mahsulotlari bitta rejalashtirish "
               "oynasida: texkarta, zayafka soni, tezkor belgisi, xomashyo tekshiruvi — tanlanganlar "
               "bo'lim navbatiga (smena oynasiga) yangi buyurtma bo'lib tushadi.",
    "description": """
Khatdecor Ishlab chiqarish zayafkalari
======================================

* **Berilmagan** — tasdiqlangan sotuv buyurtmalarining hali jo'natilmagan qatorlari, sotuv
  omboridagi qoldiq bilan solishtirilgan: shu buyurtmaga band qilingani + bo'sh qoldiq
  (eski buyurtma oldin), ishlab chiqarishga allaqachon berilgani ayriladi, qolgani «Yetmaydi».
* **Zayafka yaratish** — tanlangan qatorlar uchun texkarta va soni bo'yicha ishlab chiqarish
  buyurtmasi ochiladi (tasdiqlangan, boshlanmagan), tanlangan bo'limning omborida va
  liniyasida — bo'lim oynasidagi «Yangi buyurtmalar» ustuniga tushadi. «Tezkor» bo'lsa
  navbat boshida turadi.
* **Ombor to'ldirish zayafkasi** — sotuv buyurtmasisiz, omborga ishlab chiqarish.
* **Xomashyo** — bo'lim omborida bor / boshqa xomashyo omboridan ko'chirish kerak / yetmaydi.
* **Sotuvga chiqarish** — tayyor bo'lgan mahsulot sotuv buyurtmasining jo'natmasiga band qilinadi.
    """,
    "author": "Khatdecor",
    "category": "Manufacturing",
    "version": "19.0.1.1.0",
    "depends": ["cst_kerama_wh_flow", "cst_kerama_sale_production", "cst_kerama_shift", "sale_stock", "sale_mrp"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/production_request_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cst_kerama_production_request/static/src/board/**/*",
            "cst_kerama_production_request/static/src/floor_patch/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
