from odoo import fields, models


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    # copied onto backorders, so a request follows its order to the end
    cst_request_id = fields.Many2one("cst.production.request", string="Zayafka", index=True, copy=True,
                                     readonly=True, ondelete="set null")
