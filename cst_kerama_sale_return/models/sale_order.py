from odoo import _, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_open_return_wizard(self):
        """Open the "Qaytarish" (return / refund) wizard for this order."""
        self.ensure_one()
        if self.state != "sale":
            raise UserError(
                _("The order must be confirmed before a return can be registered.")
            )
        return {
            "name": _("Qaytarish"),
            "type": "ir.actions.act_window",
            "res_model": "cst.sale.return.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_order_id": self.id,
            },
        }
