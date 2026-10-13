from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

from .stock_quant import bypasses_stock_guard


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def button_validate(self):
        if not bypasses_stock_guard(self.env):
            for picking in self:
                picking.move_ids._cst_raise_if_negative(_("Validating %s", picking.name))
        return super().button_validate()


class StockScrap(models.Model):
    _inherit = "stock.scrap"

    def action_validate(self):
        if not bypasses_stock_guard(self.env):
            for scrap in self:
                scrap._cst_check_not_negative()
        return super().action_validate()

    def _cst_check_not_negative(self):
        self.ensure_one()
        if self.location_id.usage != "internal":
            return
        product = self.product_id
        needed = self.product_uom_id._compute_quantity(self.scrap_qty, product.uom_id)
        available = product.with_context(location=self.location_id.id).qty_available
        rounding = product.uom_id.rounding or 0.01
        if float_compare(needed, available, precision_rounding=rounding) > 0:
            raise UserError(_(
                "Scrapping would take stock below zero:\n\n"
                "  • %(product)s in %(location)s: need %(needed).2f, have %(available).2f\n\n"
                "Receive or correct the stock first, or ask someone with the "
                "\"Allow Negative Stock\" right to do it.",
                product=product.display_name,
                location=self.location_id.display_name,
                needed=needed, available=available))
