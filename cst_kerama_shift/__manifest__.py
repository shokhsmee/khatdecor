{
    "name": "Khatdecor Smena boshqaruvi",
    "summary": "Bo'limlar, smenalar, bo'lim oynasi: buyurtmani liniyaga qo'yish, natija "
               "(1-sort / 2-sort / brak), smena yopilganda KPI fondi va jarima.",
    "description": """
Khatdecor Smena boshqaruvi
==========================

Ishlab chiqarish uch bo'limdan iborat zanjir: Bosma → Kesish → Preslash. Har
bo'limning o'z stanoklari, menejerlari va xodimlari bor. Menejer smenani ochadi,
Face ID bo'yicha kelgan xodimlarni belgilaydi, bo'lim navbatidagi buyurtmani
liniyaga qo'yadi, natijani kun davomida kiritadi (1-sort, 2-sort, brak) va
smenani yopadi. Yopilganda menejer umumiy KPI summasini kiritadi, u kelgan
xodimlarga teng bo'linadi va oylik qatorlari bo'lib yoziladi; brak jarimasi ham.

* **Bo'lim** — stanoklar guruhi, menejerlari, doimiy xodimlari, chiqaradigan mahsulot turi.
* **Smena vaqtlari** — sozlanadigan: 1-smena 06–14, 2-smena 14–22, 3-smena 22–06.
* **Smena** — bo'limda bir vaqtda bittasi ochiq; ish buyurtmalari, natija yozuvlari, yakun.
* **Natija** — oxirgi operatsiyada mahsulot omborga tushadi, brak scrap'ga, 2-sort
  o'z egizak mahsulotiga (cst_kerama_variants) o'tadi; oraliq bo'limlarda soni yoziladi.
* **Oylik** — SMENA_KPI va JARIMA komponentlari; smenaga bog'langan ish buyurtmalari
  eski ishbaydan chiqariladi, ikki marta to'lanmaydi.
    """,
    "author": "Khatdecor",
    "category": "Manufacturing",
    "version": "19.0.1.7.0",
    "depends": ["mrp", "mrp_workorder", "stock", "hr", "hr_attendance",
                "cst_kerama_variants", "cst_kerama_payroll", "cst_kerama_reports"],
    "data": [
        "security/shift_security.xml",
        "security/ir.model.access.csv",
        "data/shift_data.xml",
        "views/department_views.xml",
        "views/shift_template_views.xml",
        "views/shift_views.xml",
        "views/mrp_views.xml",
        "wizard/shift_close_views.xml",
        "views/menus.xml",
        "views/floor_views.xml",
        "wizard/shift_report_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cst_kerama_shift/static/src/floor/**/*",
            "cst_kerama_shift/static/src/department/**/*",
            "cst_kerama_shift/static/src/mo_builder/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
    "license": "LGPL-3",
    "installable": True,
    "application": True,
    "auto_install": False,
}
