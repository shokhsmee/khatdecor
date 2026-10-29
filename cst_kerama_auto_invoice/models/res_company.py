from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    cst_auto_invoice_sale = fields.Boolean(
        string="Sotuvda avtomatik hisob-faktura", default=True,
        help="Yuk chiqarilganda (eshik / yetkazib berish tasdiqlanganda) chiqqan tovarga hisob-faktura "
             "darhol yaratiladi va tasdiqlanadi; mijozning avansi unga yopiladi.")
    cst_auto_invoice_purchase = fields.Boolean(
        string="Xaridda avtomatik schyot", default=True,
        help="Tovar qabul qilinganda qabul qilingan miqdorga ta'minotchi schyoti (vendor bill) darhol "
             "yaratiladi va tasdiqlanadi; oldindan to'langan pul unga yopiladi.")


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    cst_auto_invoice_sale = fields.Boolean(related="company_id.cst_auto_invoice_sale", readonly=False)
    cst_auto_invoice_purchase = fields.Boolean(related="company_id.cst_auto_invoice_purchase", readonly=False)
