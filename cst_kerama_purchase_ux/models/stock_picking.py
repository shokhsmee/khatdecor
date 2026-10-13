from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    cst_purchase_photo_ids = fields.Many2many(
        related="purchase_id.cst_photo_ids", string="Xarid buyurtmasidagi rasmlar")

    def _action_done(self):
        result = super()._action_done()
        # the plate the dock wrote down goes back to an order that had none
        for picking in self.filtered(
                lambda p: p.picking_type_code == "incoming" and p.purchase_id
                and p.cst_car_number and not p.purchase_id.cst_car_number):
            picking.purchase_id.cst_car_number = picking.cst_car_number
        return result
