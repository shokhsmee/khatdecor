from markupsafe import Markup

from odoo import api, fields, models
from odoo.tools import formatLang


class SaleOrder(models.Model):
    _inherit = "sale.order"

    payment_invoiced_total = fields.Monetary(
        string="Invoiced Amount",
        compute="_compute_payment_summary",
        currency_field="currency_id",
        help="Total amount of the posted customer invoices for this order.",
    )
    payment_amount_due = fields.Monetary(
        string="Amount Due",
        compute="_compute_payment_summary",
        currency_field="currency_id",
        help="Order total still owed: order total minus every payment already "
        "received, including the ones still waiting for approval.",
    )
    payment_waiting_total = fields.Monetary(
        string="Waiting Approval (order currency)",
        compute="_compute_payment_summary",
        currency_field="currency_id",
        help="Pending (In Process) payments converted to the order currency.",
    )
    payment_has_waiting = fields.Boolean(
        compute="_compute_payment_summary",
    )
    payment_waiting_html = fields.Html(
        string="Waiting approval",
        compute="_compute_payment_summary",
        sanitize=False,
        help="Payments registered but not yet confirmed (In Process), shown per "
        "currency.",
    )

    @api.depends(
        "amount_total",
        "currency_id",
        "invoice_ids.state",
        "invoice_ids.move_type",
        "invoice_ids.amount_total",
        "invoice_ids.amount_residual",
        "invoice_ids.matched_payment_ids",
        "invoice_ids.matched_payment_ids.state",
        "invoice_ids.matched_payment_ids.amount",
        "invoice_ids.matched_payment_ids.currency_id",
    )
    def _compute_payment_summary(self):
        for order in self:
            company = order.company_id
            order_ccy = order.currency_id
            date = fields.Date.context_today(order)

            invoices = order.invoice_ids.filtered(
                lambda m: m.state == "posted"
                and m.move_type in ("out_invoice", "out_refund")
            )

            invoiced = 0.0
            received = 0.0
            for inv in invoices:
                sign = 1.0 if inv.move_type == "out_invoice" else -1.0
                inv_ccy = inv.currency_id
                total = inv_ccy._convert(inv.amount_total, order_ccy, company, date)
                residual = inv_ccy._convert(
                    inv.amount_residual, order_ccy, company, date
                )
                invoiced += sign * total
                # paid + pending portion already reflected in the residual
                received += sign * (total - residual)

            # Pending ("In Process") payments, kept in their own currency so that
            # several pending payments in different currencies are listed apart.
            pending = invoices.matched_payment_ids.filtered(
                lambda p: p.state == "in_process"
            )
            waiting_by_ccy = {}
            waiting_order_ccy = 0.0
            for pay in pending:
                waiting_by_ccy.setdefault(pay.currency_id, 0.0)
                waiting_by_ccy[pay.currency_id] += pay.amount
                waiting_order_ccy += pay.currency_id._convert(
                    pay.amount, order_ccy, company, date
                )

            order.payment_invoiced_total = invoiced
            order.payment_amount_due = order.amount_total - received
            order.payment_waiting_total = waiting_order_ccy
            order.payment_has_waiting = bool(pending)

            if pending:
                lines = [
                    Markup('<span class="fw-bold" style="color:#d9a400;">%s</span>')
                    % formatLang(order.env, amount, currency_obj=ccy)
                    for ccy, amount in waiting_by_ccy.items()
                ]
                order.payment_waiting_html = Markup("<br/>").join(lines)
            else:
                order.payment_waiting_html = False
