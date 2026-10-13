from odoo import _, api, fields, models
from odoo.exceptions import UserError


class KassaReconcileWizard(models.TransientModel):
    _name = "cst.kassa.reconcile.wizard"
    _description = "Settle Client Money Against Debts"

    partner_id = fields.Many2one("res.partner", string="Client", required=True,
                                 domain="[('parent_id', '=', False)]")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    credit_ids = fields.One2many("cst.kassa.reconcile.credit", "wizard_id", string="Free money lines")
    debt_ids = fields.One2many("cst.kassa.reconcile.debt", "wizard_id", string="Debt lines")
    available = fields.Monetary(compute="_compute_totals", string="Free money")
    selected_debt = fields.Monetary(compute="_compute_totals", string="Selected debts")
    to_settle = fields.Monetary(compute="_compute_totals", string="Will be settled")
    advance_left = fields.Monetary(compute="_compute_totals", string="Stays as advance")
    debt_left = fields.Monetary(compute="_compute_totals", string="Debt left")

    @api.model
    def _cst_open(self, partner, company):
        if not partner:
            raise UserError(_("Choose the client."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Settle client account"),
            "res_model": self._name,
            "view_mode": "form",
            "target": "new",
            "context": {"default_partner_id": partner.commercial_partner_id.id,
                        "default_company_id": company.id},
        }

    @api.depends("credit_ids.use", "credit_ids.amount", "debt_ids.selected", "debt_ids.debt")
    def _compute_totals(self):
        for wiz in self:
            wiz.available = sum(wiz.credit_ids.filtered("use").mapped("amount"))
            wiz.selected_debt = sum(wiz.debt_ids.filtered("selected").mapped("debt"))
            wiz.to_settle = min(wiz.available, wiz.selected_debt)
            wiz.advance_left = wiz.available - wiz.to_settle
            wiz.debt_left = wiz.selected_debt - wiz.to_settle

    @api.onchange("partner_id", "company_id")
    def _onchange_partner(self):
        Alloc = self.env["cst.kassa.allocation"]
        credits = [fields.Command.clear()]
        debts = [fields.Command.clear()]
        if self.partner_id and self.company_id:
            partner = self.partner_id.commercial_partner_id
            for line in Alloc._cst_credit_lines(partner, self.company_id):
                pay = line.move_id.origin_payment_id
                foreign = line.currency_id and line.currency_id != self.company_id.currency_id
                credits.append(fields.Command.create({
                    "line_id": line.id,
                    "date": line.date,
                    "name": pay.name or line.move_id.name,
                    "memo": pay.memo or line.name,
                    "amount": -line.amount_residual,
                    "orig_currency_id": line.currency_id.id if foreign else False,
                    "orig_amount": -line.amount_residual_currency if foreign else 0.0,
                    "rate": abs(line.amount_currency / line.balance) if foreign and line.balance else 0.0,
                    "use": True,
                }))
            for seq, (date, order, invoice) in enumerate(Alloc._cst_targets(partner, self.company_id)):
                if order:
                    company = order.company_id
                    total = order.currency_id._convert(order.amount_total, company.currency_id, company, date)
                    debts.append(fields.Command.create({
                        "sequence": seq, "order_id": order.id, "date": date, "name": order.name,
                        "total": total, "debt": Alloc._cst_order_debt(order), "selected": True}))
                elif invoice.move_type == "entry":
                    # a refund paid out to the client: its open receivable debit
                    lines = invoice.line_ids.filtered(
                        lambda l: l.account_id.account_type == "asset_receivable" and l.debit > 0
                        and l.partner_id.commercial_partner_id == partner)
                    debts.append(fields.Command.create({
                        "sequence": seq, "invoice_id": invoice.id, "date": date, "name": invoice.name,
                        "total": sum(lines.mapped("balance")),
                        "debt": sum(lines.filtered(lambda l: not l.reconciled).mapped("amount_residual")),
                        "selected": True}))
                else:
                    debts.append(fields.Command.create({
                        "sequence": seq, "invoice_id": invoice.id, "date": date, "name": invoice.name,
                        "total": invoice.amount_total_signed, "debt": invoice.amount_residual_signed,
                        "selected": True}))
        self.credit_ids = credits
        self.debt_ids = debts

    def action_reconcile(self):
        self.ensure_one()
        credits = self.credit_ids.filtered("use").line_id
        debts = self.debt_ids.filtered("selected").sorted(lambda d: (d.sequence, d.id))
        if not credits:
            raise UserError(_("The client has no free money to settle."))
        if not debts:
            raise UserError(_("Select at least one debt."))
        targets = [(d.date, d.order_id, d.invoice_id) for d in debts]
        allocations = self.env["cst.kassa.allocation"]._cst_allocate(
            self.partner_id, self.company_id, credit_lines=credits, targets=targets)
        balance = self.env["cst.kassa.partner.balance"]
        balance._cst_refresh(self.partner_id.commercial_partner_id)
        next_action = balance.cst_open_for_partner(self.partner_id, self.company_id)
        total = sum(allocations.mapped("amount"))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Settled"),
                "message": _("%(amount)s applied to %(count)s debt(s).",
                             amount=self.currency_id.format(total),
                             count=len(set(allocations.mapped(lambda a: (a.order_id.id, a.invoice_id.id))))),
                "type": "success",
                "sticky": False,
                "next": next_action,
            },
        }


class KassaReconcileCredit(models.TransientModel):
    _name = "cst.kassa.reconcile.credit"
    _description = "Settlement: Free Money Line"
    _order = "date, id"

    wizard_id = fields.Many2one("cst.kassa.reconcile.wizard", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    line_id = fields.Many2one("account.move.line", required=True)
    date = fields.Date()
    name = fields.Char(string="Payment")
    memo = fields.Char(string="Note")
    amount = fields.Monetary(string="Free amount")
    orig_currency_id = fields.Many2one("res.currency", string="Paid in")
    orig_amount = fields.Monetary(string="Free amount (paid currency)", currency_field="orig_currency_id")
    rate = fields.Float(string="Dollar rate", digits=(16, 2),
                        help="The rate this payment was booked at in the kassa.")
    use = fields.Boolean(string="Use", default=True)


class KassaReconcileDebt(models.TransientModel):
    _name = "cst.kassa.reconcile.debt"
    _description = "Settlement: Debt Line"
    _order = "sequence, id"

    wizard_id = fields.Many2one("cst.kassa.reconcile.wizard", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    sequence = fields.Integer()
    order_id = fields.Many2one("sale.order", string="Sales order")
    invoice_id = fields.Many2one("account.move", string="Invoice")
    date = fields.Date()
    name = fields.Char(string="Document")
    total = fields.Monetary(string="Total")
    debt = fields.Monetary(string="Debt")
    selected = fields.Boolean(string="Settle", default=True)
    preview = fields.Monetary(compute="_compute_preview", string="Will be paid")
    debt_after = fields.Monetary(compute="_compute_preview", string="Debt after")

    @api.depends("selected", "debt", "sequence", "wizard_id.available",
                 "wizard_id.debt_ids.selected", "wizard_id.debt_ids.debt")
    def _compute_preview(self):
        for line in self:
            wiz = line.wizard_id
            left = wiz.available
            paid = 0.0
            for other in wiz.debt_ids:
                amount = min(other.debt, max(left, 0.0)) if other.selected else 0.0
                left -= amount
                if other == line or other.id == line.id:
                    paid = amount
                    break
            line.preview = paid
            line.debt_after = line.debt - paid
