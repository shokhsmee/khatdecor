from collections import defaultdict

from odoo import api, fields, models


class StockMove(models.Model):
    """Show the real stock of the source and the destination location on
    transfer lines, so the storekeeper sees how much is on both sides before
    moving it."""

    _inherit = "stock.move"

    cst_qty_on_hand = fields.Float(
        string="On Hand", digits="Product Unit",
        compute="_compute_cst_qty_on_hand",
        help="Actual quantity in the source location (sub-locations included), "
             "in the line's unit of measure.")
    cst_qty_on_hand_dest = fields.Float(
        string="On Hand (destination)", digits="Product Unit",
        compute="_compute_cst_qty_on_hand",
        help="Actual quantity in the destination location (sub-locations included), "
             "in the line's unit of measure.")

    @api.depends("product_id", "product_uom", "location_id", "location_dest_id")
    def _compute_cst_qty_on_hand(self):
        self.cst_qty_on_hand = 0.0
        self.cst_qty_on_hand_dest = 0.0
        for field, loc_field in (("cst_qty_on_hand", "location_id"),
                                 ("cst_qty_on_hand_dest", "location_dest_id")):
            by_location = defaultdict(lambda: self.browse())
            for move in self:
                location = move[loc_field]
                if move.product_id.is_storable and location.usage == "internal":
                    by_location[location.id] |= move
            for location_id, moves in by_location.items():
                products = moves.product_id.with_context(location=location_id)
                on_hand = {p.id: p.qty_available for p in products}
                for move in moves:
                    qty = on_hand.get(move.product_id.id, 0.0)
                    if move.product_uom and move.product_uom != move.product_id.uom_id:
                        qty = move.product_id.uom_id._compute_quantity(qty, move.product_uom)
                    move[field] = qty
