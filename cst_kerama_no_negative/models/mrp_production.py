from odoo import _, models

from .stock_quant import bypasses_stock_guard


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    def button_mark_done(self):
        """Refuse to close a manufacturing order that would consume stock we
        do not have. Only the raw materials are checked — the finished product
        moves *into* stock."""
        if not bypasses_stock_guard(self.env):
            for production in self:
                production.move_raw_ids._cst_raise_if_negative(
                    _("Finishing %s", production.name))
        return super().button_mark_done()
