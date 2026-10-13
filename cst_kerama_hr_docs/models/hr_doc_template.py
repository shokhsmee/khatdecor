"""The Word files the documents are made from.

The wording belongs to the HR department, not to this module: every document
is a .docx carrying ``{{placeholder}}`` markers, stored as a record so the
head of HR can download it, edit it in Word and upload it back without a
developer.  The module only ships the first version of each file.
"""
from odoo import fields, models

EVENT_KINDS = [
    ("kirish", "Ishga qabul"),
    ("otkazish", "Boshqa lavozimga o'tkazish"),
    ("boshash", "Ishdan bo'shatish"),
]


class CstHrDocTemplate(models.Model):
    _name = "cst.hr.doc.template"
    _description = "Kadr hujjati shabloni"
    _order = "kind, sequence, id"

    name = fields.Char(string="Hujjat nomi", required=True, translate=False)
    code = fields.Char(
        string="Kod", required=True, copy=False,
        help="Shablonni kod orqali topish uchun — faylni almashtirganda ham "
             "o'zgarmaydi.")
    kind = fields.Selection(
        EVENT_KINDS, string="Kadr harakati", required=True,
        help="Shu turdagi harakat yaratilganda ushbu hujjat ro'yxatga qo'shiladi.")
    sequence = fields.Integer(string="Tartib", default=10)
    file = fields.Binary(string="Word shabloni", attachment=True, required=True)
    filename = fields.Char(string="Fayl nomi")
    note = fields.Text(string="Izoh")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Bunday kodli shablon allaqachon bor.")
