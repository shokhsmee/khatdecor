{
    "name": "Khatdecor Product Search",
    "summary": "Mahsulotni bir necha so'z bilan, xarakteristikasi bilan qidirish.",
    "description": """
Khatdecor Product Search
========================

Odoo mahsulotni yozilgan matnni **bitta butun satr** sifatida qidiradi:
«бел лдсп» deb yozilsa nomida aynan «бел лдсп» ketma-ket turgan mahsulot
izlanadi va «Белый Корона ЛДСП» topilmaydi.  Bu modul so'rovni so'zlarga
bo'ladi — har bir so'z nom, ichki kod, shtrix-kod yoki xarakteristikaning
qayeridadir bo'lsa yetarli — va nomi birinchi so'z bilan boshlanadigan
mahsulotlarni ro'yxat boshiga chiqaradi.

Buyurtma qatoridagi tanlash oynasi, mahsulotlar ro'yxatidagi qidiruv va
variantlar bo'yicha qidiruv bir xil ishlaydi.
    """,
    "author": "Khatdecor",
    "category": "Sales",
    "version": "19.0.1.0.0",
    "depends": ["product", "cst_kerama_variants"],
    "data": [
        "views/product_search_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
