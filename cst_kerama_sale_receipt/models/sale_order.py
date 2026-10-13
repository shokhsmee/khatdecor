from odoo import models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_print_sale_receipt(self):
        """Open the POS-style receipt in a new tab; the page auto-prints."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/kerama/sale/receipt/%s" % self.id,
            "target": "new",
        }
