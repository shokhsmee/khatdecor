from odoo import _, api, fields, models
from odoo.exceptions import UserError


class KassaPartnerBalance(models.Model):
    """Client account per company: order debts, free money (advance), balance.

    Rows are rebuilt from the sales orders and the receivable ledger every time
    the list is opened and after every cash operation / settlement, so they are
    a snapshot, never a source of truth.
    """
    _name = "cst.kassa.partner.balance"
    _description = "Client Account"
    _order = "balance desc, partner_id"
    _rec_name = "partner_id"

    partner_id = fields.Many2one("res.partner", string="Client", required=True, readonly=True,
                                 index=True, ondelete="cascade")
    phone = fields.Char(related="partner_id.phone")
    company_id = fields.Many2one("res.company", required=True, readonly=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    order_count = fields.Integer(string="Orders", readonly=True)
    order_total = fields.Monetary(string="Orders total", readonly=True)
    order_debt = fields.Monetary(string="Order debt", readonly=True)
    invoice_debt = fields.Monetary(string="Other invoices debt", readonly=True)
    total_debt = fields.Monetary(string="Total debt", readonly=True)
    debt_detail = fields.Char(string="Debt by currency", readonly=True,
                              help="Each debt in its own currency: so'm orders in so'm, dollar orders in dollars.")
    advance = fields.Monetary(string="Advance (not settled)", readonly=True,
                              help="Money received from the client that is not applied to any order yet.")
    balance = fields.Monetary(string="Balance", readonly=True,
                              help="Total debt - advance. Positive: the client owes us; "
                                   "negative: we owe the client.")
    paid_total = fields.Monetary(string="Paid total", readonly=True)
    last_payment_date = fields.Date(string="Last payment", readonly=True)
    status = fields.Selection([("debt", "Owes"), ("advance", "Has advance"), ("clear", "Settled")],
                              readonly=True)
    can_reconcile = fields.Boolean(readonly=True, help="Has both free money and open debts.")

    order_ids = fields.Many2many("sale.order", compute="_compute_details", string="Sales orders")
    payment_ids = fields.Many2many("account.payment", compute="_compute_details", string="Payments")
    operation_ids = fields.Many2many("cst.kassa.operation", compute="_compute_details",
                                     string="Cash operations")
    allocation_ids = fields.Many2many("cst.kassa.allocation", compute="_compute_details",
                                      string="Settlements")
    invoice_ids = fields.Many2many("account.move", compute="_compute_details", string="Open invoices")

    _partner_company_uniq = models.Constraint("unique(partner_id, company_id)",
                                              "One client account per company.")

    def _compute_details(self):
        Alloc = self.env["cst.kassa.allocation"]
        for row in self:
            partner, company = row.partner_id, row.company_id
            row.order_ids = self.env["sale.order"].search([
                ("partner_id", "child_of", partner.id), ("company_id", "=", company.id),
                ("state", "=", "sale")], order="date_order desc")
            row.payment_ids = self.env["account.payment"].search([
                ("partner_id", "child_of", partner.id), ("company_id", "=", company.id),
                ("partner_type", "=", "customer"), ("state", "not in", ("draft", "canceled"))],
                order="date desc, id desc")
            row.operation_ids = self.env["cst.kassa.operation"].search([
                ("commercial_partner_id", "=", partner.id), ("company_id", "=", company.id)],
                order="date desc, id desc")
            row.allocation_ids = Alloc.search([
                ("partner_id", "=", partner.id), ("company_id", "=", company.id)])
            row.invoice_ids = Alloc._cst_open_invoices(partner, company)

    # ------------------------------------------------------------------
    @api.model
    def _cst_figures(self, partner, company):
        Alloc = self.env["cst.kassa.allocation"]
        partner = partner.commercial_partner_id
        ccy = company.currency_id
        today = fields.Date.context_today(self)
        orders = self.env["sale.order"].sudo().search([
            ("partner_id", "child_of", partner.id), ("company_id", "=", company.id), ("state", "=", "sale")])
        order_total = sum(o.currency_id._convert(o.amount_total, ccy, company, today) for o in orders)
        order_debt = sum(Alloc._cst_order_debt(o) for o in orders if o.payment_amount_due > 0)
        # standalone invoices + refunds paid out that no advance has absorbed yet
        invoice_debt = sum(Alloc._cst_open_invoices(partner, company).mapped("amount_residual_signed")) \
            + sum(Alloc._cst_open_debit_lines(partner, company).mapped("amount_residual"))
        advance = -sum(Alloc._cst_credit_lines(partner, company).mapped("amount_residual"))
        payments = self.env["account.payment"].sudo().search([
            ("partner_id", "child_of", partner.id), ("company_id", "=", company.id),
            ("partner_type", "=", "customer"), ("state", "not in", ("draft", "canceled"))],
            order="date desc")
        total_debt = order_debt + invoice_debt
        balance = total_debt - advance
        return {
            "order_count": len(orders),
            "order_total": order_total,
            "order_debt": order_debt,
            "invoice_debt": invoice_debt,
            "total_debt": total_debt,
            "debt_detail": Alloc._cst_debt_text(partner, company),
            "advance": advance,
            "balance": balance,
            "paid_total": sum(payments.mapped("amount_company_currency_signed")),
            "last_payment_date": payments[:1].date or False,
            "status": "clear" if ccy.is_zero(balance) else ("debt" if balance > 0 else "advance"),
            "can_reconcile": not ccy.is_zero(advance) and advance > 0
                             and not ccy.is_zero(total_debt) and total_debt > 0,
        }

    @api.model
    def _cst_refresh(self, partners=None):
        """Rebuild the rows of these clients (all clients when None)."""
        self = self.sudo()
        companies = self.env["res.company"].search([])
        if partners is None:
            order_partners = self.env["sale.order"].search([("state", "=", "sale")]).partner_id
            line_partners = self.env["account.move.line"].search([
                ("account_id.account_type", "=", "asset_receivable"),
                ("parent_state", "=", "posted")]).partner_id
            partners = (order_partners | line_partners).commercial_partner_id
            stale = self.search([("partner_id", "not in", partners.ids)])
            stale.unlink()
        for partner in partners.commercial_partner_id:
            for company in companies:
                fig = self._cst_figures(partner, company)
                row = self.search([("partner_id", "=", partner.id), ("company_id", "=", company.id)])
                empty = not fig["order_count"] and not fig["paid_total"] \
                    and company.currency_id.is_zero(fig["balance"]) \
                    and company.currency_id.is_zero(fig["advance"])
                if empty:
                    row.unlink()
                elif row:
                    row.write(fig)
                else:
                    self.create(dict(fig, partner_id=partner.id, company_id=company.id))
        return True

    @api.model
    def cst_action_open(self):
        self._cst_refresh()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "cst_kerama_kassa.action_kassa_partner_balance_window")
        return action

    @api.model
    def cst_open_for_partner(self, partner, company=None):
        partner = partner.commercial_partner_id
        self._cst_refresh(partner)
        domain = [("partner_id", "=", partner.id)]
        rows = self.search(domain + [("company_id", "=", (company or self.env.company).id)]) \
            or self.search(domain)
        if not rows:
            raise UserError(_("%(partner)s has no sales orders or payments yet.", partner=partner.display_name))
        if len(rows) == 1:
            return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": rows.id,
                    "view_mode": "form", "target": "current", "name": partner.display_name}
        return {"type": "ir.actions.act_window", "res_model": self._name, "view_mode": "list,form",
                "domain": [("id", "in", rows.ids)], "name": partner.display_name}

    # ------------------------------------------------------------------
    def action_refresh(self):
        self._cst_refresh(self.partner_id)
        return True

    def action_reconcile(self):
        self.ensure_one()
        return self.env["cst.kassa.reconcile.wizard"]._cst_open(self.partner_id, self.company_id)

    def action_receive(self):
        """New client payment on an open cash day of this company."""
        self.ensure_one()
        days = self.env["cst.kassa.day"].search([("state", "=", "open"), ("company_id", "=", self.company_id.id)])
        days = days.filtered(lambda d: not d.kassa_id.user_ids or self.env.user in d.kassa_id.user_ids)
        if not days:
            raise UserError(_("No cash day is open in %(company)s. Open the day from the Kassa screen first.",
                              company=self.company_id.name))
        ctx = {"default_direction": "in", "default_type_in": "customer_in",
               "default_partner_id": self.partner_id.id}
        if len(days) == 1:
            ctx["default_day_id"] = days.id
        return {"type": "ir.actions.act_window", "name": _("Payment from a client"),
                "res_model": "cst.kassa.operation", "view_mode": "form", "target": "current",
                "context": ctx}
