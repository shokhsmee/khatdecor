from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Invoice payment states that mean nothing is left to collect.
_SETTLED_STATES = ("paid", "in_payment", "reversed")


class SaleFullPaymentWizard(models.TransientModel):
    _name = "cst.sale.full.payment.wizard"
    _description = "Sales Order Full Payment"

    order_id = fields.Many2one(
        "sale.order",
        string="Sales Order",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(related="order_id.company_id")
    partner_id = fields.Many2one(related="order_id.partner_id", string="Customer")

    order_currency_id = fields.Many2one(
        related="order_id.currency_id", string="Order Currency"
    )
    order_total = fields.Monetary(
        related="order_id.amount_total",
        string="Order Total",
        currency_field="order_currency_id",
    )

    payment_date = fields.Date(
        string="Payment Date",
        required=True,
        default=fields.Date.context_today,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Payment Currency",
        required=True,
        compute="_compute_currency_id",
        store=True,
        precompute=True,
        readonly=False,
    )
    amount = fields.Monetary(
        string="Amount",
        compute="_compute_amount",
        currency_field="currency_id",
        help="Full amount to pay, expressed in the selected payment currency.",
    )

    available_journal_ids = fields.Many2many(
        "account.journal",
        compute="_compute_available_journal_ids",
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Payment Journal",
        required=True,
        compute="_compute_journal_id",
        store=True,
        precompute=True,
        readonly=False,
        domain="[('id', 'in', available_journal_ids)]",
    )
    communication = fields.Char(string="Memo")

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    def _get_available_journals(self, company):
        return self.env["account.journal"].search(
            [
                *self.env["account.journal"]._check_company_domain(company),
                ("type", "in", ("bank", "cash")),
            ]
        )

    @api.depends("order_id")
    def _compute_available_journal_ids(self):
        for wizard in self:
            company = wizard.order_id.company_id or self.env.company
            wizard.available_journal_ids = wizard._get_available_journals(company)

    @api.depends("order_id")
    def _compute_journal_id(self):
        for wizard in self:
            company = wizard.order_id.company_id or self.env.company
            available = wizard._get_available_journals(company)
            if wizard.journal_id and wizard.journal_id in available:
                continue
            wizard.journal_id = available[:1]

    @api.depends("journal_id", "order_currency_id")
    def _compute_currency_id(self):
        for wizard in self:
            wizard.currency_id = (
                wizard.journal_id.currency_id
                or wizard.order_currency_id
                or wizard.company_id.currency_id
            )

    @api.depends("currency_id", "payment_date", "order_total", "order_currency_id")
    def _compute_amount(self):
        for wizard in self:
            order_ccy = wizard.order_currency_id
            pay_ccy = wizard.currency_id
            amount = wizard.order_total
            if order_ccy and pay_ccy and order_ccy != pay_ccy:
                amount = order_ccy._convert(
                    amount,
                    pay_ccy,
                    wizard.company_id,
                    wizard.payment_date or fields.Date.context_today(wizard),
                )
            wizard.amount = amount

    # ------------------------------------------------------------------
    # Action
    # ------------------------------------------------------------------
    def action_pay(self):
        """Create + post the invoice, register the full payment and confirm it."""
        self.ensure_one()
        if not self.journal_id:
            raise UserError(_("Please select a payment journal."))

        order = self.order_id
        invoices = self._get_invoices_to_pay(order)

        # Make sure every invoice we are about to pay is posted.
        invoices.filtered(lambda m: m.state == "draft").action_post()

        to_pay = invoices.filtered(
            lambda m: m.state == "posted"
            and m.payment_state not in _SETTLED_STATES
        )
        if not to_pay:
            raise UserError(_("There is nothing left to pay on this order."))

        payments = self._register_payment(to_pay)

        # "Tasdiqlangan": force the payment out of the *In Process* (waiting
        # approval) state so it is confirmed straight away.
        payments.filtered(lambda p: p.state == "in_process").action_validate()

        return {"type": "ir.actions.act_window_close"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_invoices_to_pay(self, order):
        """Return the order invoices to settle, creating one if needed."""
        invoices = order.invoice_ids.filtered(
            lambda m: m.move_type in ("out_invoice", "out_refund")
            and m.state != "cancel"
        )
        open_invoices = invoices.filtered(
            lambda m: m.state == "draft"
            or (m.state == "posted" and m.payment_state not in _SETTLED_STATES)
        )
        if open_invoices:
            return open_invoices

        if order.invoice_status != "to invoice":
            raise UserError(
                _(
                    "This order has nothing left to invoice, so a full payment "
                    "cannot be registered."
                )
            )
        return order._create_invoices()

    def _register_payment(self, invoices):
        """Drive the standard Register Payment wizard for the given invoices."""
        register = (
            self.env["account.payment.register"]
            .with_context(
                active_model="account.move",
                active_ids=invoices.ids,
            )
            .create(
                {
                    "journal_id": self.journal_id.id,
                    "currency_id": self.currency_id.id,
                    "payment_date": self.payment_date,
                    "group_payment": True,
                    "communication": self.communication or False,
                }
            )
        )
        # Let the wizard recompute the full residual in the chosen currency so
        # the invoice is paid in full with no payment difference.
        return register._create_payments()
