from odoo import _, api, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


def bypasses_stock_guard(env):
    """True when the current user (or caller) may take stock below zero."""
    return bool(
        env.context.get("cst_allow_negative")
        or env.user.has_group("cst_kerama_no_negative.group_allow_negative_stock")
    )


class StockQuant(models.Model):
    """Backstop: whatever the path — a transfer, a manufacturing order, a scrap,
    an inventory adjustment or a script — an internal location may not end up
    holding a negative quantity."""

    _inherit = "stock.quant"

    @api.constrains("quantity", "location_id", "product_id")
    def _cst_check_not_negative(self):
        if bypasses_stock_guard(self.env):
            return
        for quant in self:
            # Virtual locations (customers, suppliers, production, inventory
            # loss) are negative by design — only real stock is guarded.
            if quant.location_id.usage != "internal":
                continue
            rounding = quant.product_uom_id.rounding or 0.01
            if float_compare(quant.quantity, 0.0, precision_rounding=rounding) < 0:
                raise ValidationError(_(
                    "Stock cannot go negative.\n\n"
                    "%(product)s in %(location)s would end at %(qty).2f %(uom)s.\n\n"
                    "Receive or correct the stock first, or ask someone with the "
                    "\"Allow Negative Stock\" right to do it.",
                    product=quant.product_id.display_name,
                    location=quant.location_id.display_name,
                    qty=quant.quantity,
                    uom=quant.product_uom_id.name or "",
                ))
