from odoo import api, fields, models

# Invoice payment states that mean nothing is left to collect.  Mirrors
# cst_kerama_full_payment, which is where these orders normally get paid.
SETTLED_PAYMENT_STATES = ("paid", "in_payment", "reversed")


class SaleOrder(models.Model):
    """Sales KPI accrues on full payment, so the order has to be able to say
    *when* it was fully collected — not merely that it was."""

    _inherit = "sale.order"

    cst_kpi_paid_date = fields.Date(
        string="KPI Date (fully paid)",
        compute="_compute_cst_kpi_paid_date",
        help="Тулик тулов тушган кун.  Сотув KPI шу кун кирадиган ойлик "
             "даврида хисобланади.  Буш булса — хали тулик тулов булмаган.")

    @api.depends(
        "state",
        "invoice_status",
        "invoice_ids.state",
        "invoice_ids.payment_state",
        "invoice_ids.move_type",
        "invoice_ids.matched_payment_ids.state",
        "invoice_ids.matched_payment_ids.date",
    )
    def _compute_cst_kpi_paid_date(self):
        for order in self:
            order.cst_kpi_paid_date = order._cst_kpi_paid_date()

    def _cst_kpi_paid_date(self):
        """The day this order became fully collected, or ``False``.

        Everything must be settled: the order fully invoiced, every invoice
        posted, and every one of them paid.  The date is the last payment that
        closed it — not today — so recomputing a period never moves a KPI line
        into a different month.
        """
        self.ensure_one()
        if self.state != "sale" or self.invoice_status != "invoiced":
            return False
        invoices = self.invoice_ids.filtered(
            lambda move: move.move_type in ("out_invoice", "out_refund")
            and move.state != "cancel")
        if not invoices or any(move.state != "posted" for move in invoices):
            return False
        if any(move.payment_state not in SETTLED_PAYMENT_STATES for move in invoices):
            return False

        dates = invoices.matched_payment_ids.filtered(
            lambda payment: payment.state in ("paid", "in_process")
        ).mapped("date")
        if not dates:
            # Settled without a payment record — written off, or reconciled
            # against a credit note.  The last invoice date is the honest date.
            dates = [move.invoice_date or move.date for move in invoices]
        return max(date for date in dates if date)
