from odoo import models


class ResPartner(models.Model):
    _inherit = "res.partner"

    def action_cst_kassa_account(self):
        self.ensure_one()
        return self.env["cst.kassa.partner.balance"].cst_open_for_partner(self)
