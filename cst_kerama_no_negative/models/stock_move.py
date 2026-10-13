from collections import defaultdict

from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class StockMove(models.Model):
    _inherit = "stock.move"

    def _cst_outgoing_by_location(self):
        """{(product, location): qty in the product's UoM} leaving internal stock."""
        needed = defaultdict(float)
        for move in self:
            if move.state in ("done", "cancel"):
                continue
            lines = move.move_line_ids
            if lines:
                for line in lines:
                    if line.location_id.usage != "internal":
                        continue
                    needed[(line.product_id, line.location_id)] += line.quantity_product_uom
            elif move.location_id.usage == "internal":
                qty = move.quantity or move.product_uom_qty
                needed[(move.product_id, move.location_id)] += \
                    move.product_uom._compute_quantity(qty, move.product_id.uom_id)
        return needed

    def _cst_stock_shortages(self):
        """[(product, location, needed, available)] where stock would go negative."""
        shortages = []
        for (product, location), needed in self._cst_outgoing_by_location().items():
            available = product.with_context(location=location.id).qty_available
            rounding = product.uom_id.rounding or 0.01
            if float_compare(needed, available, precision_rounding=rounding) > 0:
                shortages.append((product, location, needed, available))
        return shortages

    def _cst_raise_if_negative(self, what):
        """Refuse the operation when it would take an internal location below zero."""
        shortages = self._cst_stock_shortages()
        if not shortages:
            return
        rows = "\n".join(
            _("  • %(product)s in %(location)s: need %(needed).2f, have %(available).2f",
              product=product.display_name, location=location.display_name,
              needed=needed, available=available)
            for product, location, needed, available in shortages)
        raise UserError(_(
            "%(what)s would take stock below zero:\n\n%(rows)s\n\n"
            "Receive or correct the stock first, or ask someone with the "
            "\"Allow Negative Stock\" right to do it.",
            what=what, rows=rows))
