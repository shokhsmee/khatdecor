from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Invoice payment states that mean nothing is left to collect.
_SETTLED_STATES = ("paid", "in_payment", "reversed")


class SaleOrder(models.Model):
    _inherit = "sale.order"

    cst_can_full_pay = fields.Boolean(
        compute="_compute_cst_can_full_pay",
        help="Whether there is still something to collect on this order, so the "
        "full-payment button should be offered.",
    )

    @api.depends(
        "state",
        "invoice_status",
        "invoice_ids.state",
        "invoice_ids.payment_state",
        "invoice_ids.move_type",
    )
    def _compute_cst_can_full_pay(self):
        for order in self:
            can = False
            if order.state == "sale":
                invoices = order.invoice_ids.filtered(
                    lambda m: m.move_type in ("out_invoice", "out_refund")
                    and m.state != "cancel"
                )
                open_invoices = invoices.filtered(
                    lambda m: m.state == "draft"
                    or (
                        m.state == "posted"
                        and m.payment_state not in _SETTLED_STATES
                    )
                )
                can = bool(open_invoices) or order.invoice_status == "to invoice"
            order.cst_can_full_pay = can

    def action_open_full_payment_wizard(self):
        """Open the "To'liq to'lov" (full payment) wizard for this order."""
        self.ensure_one()
        if self.state != "sale":
            raise UserError(
                _("The order must be confirmed before registering a full payment.")
            )
        return {
            "name": _("To'liq to'lov"),
            "type": "ir.actions.act_window",
            "res_model": "cst.sale.full.payment.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_order_id": self.id,
            },
        }
