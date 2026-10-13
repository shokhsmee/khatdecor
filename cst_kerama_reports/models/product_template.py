from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # The fuel report is driven from the product list rather than from a
    # hard-coded product: diesel today, petrol or gas tomorrow.
    cst_is_fuel = fields.Boolean(
        string="Yoqilg'i",
        help="Bu mahsulot yoqilg'i hisobotida tanlanadigan yoqilg'i turi "
             "sifatida ko'rsatiladi.",
    )
