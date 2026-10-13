{
    "name": "Khatdecor HR Documents",
    "summary": "Kadr hujjatlarini xodim kartasidan Word (.docx) qilib yaratish.",
    "description": """
Khatdecor HR Documents
======================

Kadr bo'limi «Xodimni ishga olish xujjatlari» Excel kitobini yuritar edi: bitta
reestr, bitta «Киритиш» varag'i va har bir hujjat uchun formulalar bilan
to'ldiriladigan varaq.  Shu tartib Odoo ichiga ko'chirildi.

Har bir xodim kartasida **Hujjatlar** varag'i bor.  Unda kadr harakatlari
turlari bo'yicha ajratilgan:

* **Ishga qabul** — Ariza, Buyruq, Mehnat shartnomasi
* **Boshqa lavozimga o'tkazish** — Rozilik xati, Qo'shimcha kelishuv, Buyruq
* **Ishdan bo'shatish** — Ariza, Buyruq

Harakat yaratilganda unga tegishli hujjatlar ro'yxati o'zi paydo bo'ladi;
«Yaratish» tugmasi Word shablonini xodim ma'lumotlari bilan to'ldirib, tayyor
.docx faylni o'sha qatorga biriktiradi.  Shablonlar — alohida model, ularni
kadr bo'lim boshlig'i Word'da tahrirlab qayta yuklashi mumkin, kod tegmaydi.

Buyruq va shartnoma raqamlari «<tartib>-<oy>/k» va «<tartib>-<oy>/qk»
ko'rinishida avtomatik beriladi, kerak bo'lsa qo'lda o'zgartiriladi.
    """,
    "author": "Khatdecor",
    "category": "Human Resources",
    "version": "19.0.1.0.0",
    "depends": ["hr", "cst_kerama_payroll"],
    "external_dependencies": {"python": ["docx"]},
    "data": [
        "security/ir.model.access.csv",
        "data/hr_docs_sequence.xml",
        "data/hr_doc_template_data.xml",
        "views/hr_doc_template_views.xml",
        "views/hr_event_views.xml",
        "views/hr_employee_views.xml",
        "views/hr_docs_menus.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
