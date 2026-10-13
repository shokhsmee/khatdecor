{
    "name": "Khatdecor Shop Floor",
    "summary": "Odoo Shop Floor operatorlar uchun: o'z stanoklari va o'z buyurtmalari, Face ID "
               "holati va ish vaqti taymeri, yangi buyurtma (texkarta, xomashyo, operatsiya va "
               "stanok tanlash), kartada sotuv raqami, 2-sort va brak.",
    "description": """
Khatdecor Shop Floor
====================

Odoo Enterprise Shop Floor (mrp_display) ekranini sexdagi operator uchun moslashtiradi.

* **Operator rejimi** — ishlab chiqarish menejeri yoki smena menejeri bo'lmagan foydalanuvchi
  faqat o'zini ko'radi (operator tanlash yo'q), faqat o'ziga biriktirilgan stanoklar tabini
  oladi va faqat o'ziga tegishli ish buyurtmalarini ko'radi.
* **Face ID** — smena boshqaruvidagi hr.attendance yozuvlari asosida: kelmagan operatorga
  qizil «Siz online emassiz» xabari, kelganiga kirgan vaqtidan boshlab yuradigan taymer.
* **Yangi buyurtma** — mahsulot (xarakteristikasi bilan) va miqdor; texkartadan xomashyo
  avtomatik hisoblanadi, lekin qatorni olib tashlash, qo'shish, miqdorni o'zgartirish mumkin;
  qaysi operatsiyalar bajarilishi va har biri qaysi stanokda — tanlanadi.
* **Karta** — sotuv buyurtmasi raqami (bo'lsa), kiritilgan 2-sort va brak soni; bosilsa
  ro'yxat ochiladi. Menyuda «2-sort / Brak yozish»: natija smena yozuviga tushadi va
  buyurtma yopilganda 2-sort egizak mahsulotga, brak scrap'ga o'tadi.
    """,
    "author": "Khatdecor",
    "category": "Manufacturing",
    "version": "19.0.1.1.0",
    "depends": ["mrp_workorder", "sale_mrp", "hr_attendance", "cst_kerama_shift"],
    "data": [
        "security/ir.model.access.csv",
    ],
    "assets": {
        "web.assets_backend": [
            "cst_kerama_shopfloor/static/src/shopfloor/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
