from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        result = super()._action_done()
        if not self.env.context.get("cst_no_auto_invoice"):
            done = self.filtered(lambda p: p.state == "done")
            # after the delivery quantity sync (cst_kerama_dispatch): the order
            # already says what really left
            sales = done.filtered(lambda p: p.picking_type_code == "outgoing").sale_id
            if sales:
                sales._cst_auto_invoice()
            purchases = done.filtered(lambda p: p.picking_type_code == "incoming").purchase_id
            if purchases:
                purchases._cst_auto_bill()
        return result
