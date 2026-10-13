"""The constants the printed documents spell out."""
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    cst_hr_company_label = fields.Char(
        string="Hujjatlardagi nomi", default='"KHATDECOR" MCHJ',
        help="Buyruq va shartnomalarda korxona shu ko'rinishda yoziladi.")
    cst_hr_director = fields.Char(
        string="Direktor (hujjatlarda)", default="A.X.Tolipov")
    cst_hr_place = fields.Char(
        string="Hujjat tuzilgan joy", default="Uchko'prik tumani")
