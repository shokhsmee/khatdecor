from collections import defaultdict

from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    cst_qty_on_hand = fields.Float(
        string="Omborda", digits="Product Unit",
        compute="_compute_cst_qty_on_hand",
        help="Buyurtma omboridagi haqiqiy qoldiq (prognoz emas), qator o'lchov birligida.")

    @api.depends("product_id", "product_uom_id", "warehouse_id")
    def _compute_cst_qty_on_hand(self):
        self.cst_qty_on_hand = 0.0
        by_location = defaultdict(lambda: self.browse())
        for line in self:
            if line.product_id.is_storable:
                by_location[line.warehouse_id.lot_stock_id.id or False] |= line
        for location_id, lines in by_location.items():
            # the `warehouse` context key does not scope qty_available in 19 — `location` does
            ctx = {"location": location_id} if location_id else {}
            products = lines.product_id.with_context(**ctx)
            on_hand = {p.id: p.qty_available for p in products}
            for line in lines:
                qty = on_hand.get(line.product_id.id, 0.0)
                if line.product_uom_id and line.product_uom_id != line.product_id.uom_id:
                    qty = line.product_id.uom_id._compute_quantity(qty, line.product_uom_id)
                line.cst_qty_on_hand = qty
