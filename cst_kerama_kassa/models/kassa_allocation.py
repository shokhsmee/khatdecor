from odoo import _, api, fields, models
from odoo.exceptions import UserError

SETTLED = ("paid", "in_payment", "reversed")


class KassaAllocation(models.Model):
    """One piece of client money applied to one sales order / invoice."""
    _name = "cst.kassa.allocation"
    _description = "Client Payment Settlement"
    _order = "date desc, id desc"

    date = fields.Date(default=fields.Date.context_today, readonly=True)
    partner_id = fields.Many2one("res.partner", string="Client", required=True, readonly=True, index=True)
    company_id = fields.Many2one("res.company", required=True, readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    operation_id = fields.Many2one("cst.kassa.operation", string="Cash operation", readonly=True,
                                   index=True, ondelete="set null")
    payment_id = fields.Many2one("account.payment", string="Payment", readonly=True)
    source_name = fields.Char(string="Money from", readonly=True)
    order_id = fields.Many2one("sale.order", string="Sales order", readonly=True, index=True)
    invoice_id = fields.Many2one("account.move", string="Invoice", readonly=True)
    credit_line_id = fields.Many2one("account.move.line", readonly=True)
    debit_line_id = fields.Many2one("account.move.line", readonly=True)
    amount = fields.Monetary(readonly=True, currency_field="currency_id")
    state = fields.Selection([("done", "Settled"), ("undone", "Undone")], default="done", readonly=True)
    user_id = fields.Many2one("res.users", string="By", readonly=True, default=lambda self: self.env.user)

    # ------------------------------------------------------------------
    # Engine
    # ------------------------------------------------------------------
    @api.model
    def _cst_credit_lines(self, partner, company, operation=None):
        """Receivable lines of the client still holding unused money, oldest first.

        With an operation, its own money comes first and the client's older free
        money (earlier prepayments) follows — a client who prepaid must not be
        shown owing on an order while his advance sits unused.
        """
        domain = [
            ("partner_id", "child_of", partner.id),
            ("company_id", "=", company.id),
            ("account_id.account_type", "=", "asset_receivable"),
            ("parent_state", "=", "posted"),
            ("reconciled", "=", False),
            ("amount_residual", "<", 0),
        ]
        lines = self.env["account.move.line"].sudo().search(domain, order="date, id")
        if operation is not None:
            own = lines.filtered(lambda l: l.move_id == operation.sudo().payment_id.move_id)
            lines = own + (lines - own)
        return lines

    @api.model
    def _cst_order_debt(self, order):
        company = order.company_id
        return order.currency_id._convert(order.payment_amount_due, company.currency_id, company,
                                          fields.Date.context_today(self))

    @api.model
    def _cst_open_orders(self, partner, company):
        orders = self.env["sale.order"].sudo().search([
            ("partner_id", "child_of", partner.id),
            ("company_id", "=", company.id),
            ("state", "=", "sale"),
        ], order="date_order, id")
        return orders.filtered(lambda o: not o.currency_id.is_zero(o.payment_amount_due)
                               and o.payment_amount_due > 0)

    @api.model
    def _cst_open_invoices(self, partner, company):
        """Posted client invoices that belong to no sales order."""
        moves = self.env["account.move"].sudo().search([
            ("partner_id", "child_of", partner.id),
            ("company_id", "=", company.id),
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "not in", SETTLED),
            ("amount_residual", ">", 0),
        ], order="invoice_date, id")
        return moves.filtered(lambda m: not m.line_ids.sale_line_ids)

    @api.model
    def _cst_open_debit_lines(self, partner, company):
        """Client receivable debits that are not invoices — money we paid out to the
        client (a refund) that no advance or credit note has absorbed yet."""
        return self.env["account.move.line"].sudo().search([
            ("partner_id", "child_of", partner.id),
            ("company_id", "=", company.id),
            ("account_id.account_type", "=", "asset_receivable"),
            ("parent_state", "=", "posted"),
            ("move_id.move_type", "=", "entry"),
            ("reconciled", "=", False),
            ("amount_residual", ">", 0),
        ], order="date, id")

    @api.model
    def _cst_targets(self, partner, company, currency=None):
        """Every open debt of the client, oldest first: [(date, order, invoice)].

        With a currency, only the debts kept in that currency (a so'm order, a
        dollar order) — a client may owe separately in both.
        """
        orders = self._cst_open_orders(partner, company)
        debit_lines = self._cst_open_debit_lines(partner, company)
        invoices = self._cst_open_invoices(partner, company)
        if currency:
            orders = orders.filtered(lambda o: o.currency_id == currency)
            debit_lines = debit_lines.filtered(lambda l: l.currency_id == currency)
            invoices = invoices.filtered(lambda m: m.currency_id == currency)
        targets = [(o.date_order.date(), o, self.env["account.move"]) for o in orders]
        targets += [(line.date, self.env["sale.order"], line.move_id) for line in debit_lines]
        targets += [(m.invoice_date or m.date, self.env["sale.order"], m) for m in invoices]
        targets.sort(key=lambda t: (t[0], t[1].id or 0, t[2].id or 0))
        return targets

    @api.model
    def _cst_debt_by_currency(self, partner, company):
        """{currency: amount owed in that currency} — each debt in its own currency."""
        debts = {}
        for order in self._cst_open_orders(partner, company):
            debts[order.currency_id] = debts.get(order.currency_id, 0.0) + order.payment_amount_due
        for line in self._cst_open_debit_lines(partner, company):
            debts[line.currency_id] = debts.get(line.currency_id, 0.0) + line.amount_residual_currency
        for move in self._cst_open_invoices(partner, company):
            debts[move.currency_id] = debts.get(move.currency_id, 0.0) + move.amount_residual
        return {ccy: amount for ccy, amount in debts.items() if not ccy.is_zero(amount)}

    @api.model
    def _cst_debt_text(self, partner, company):
        """«5 000 000 so'm + 2 697 $» — the client's debts, each in its own currency."""
        debts = self._cst_debt_by_currency(partner, company)
        ordered = sorted(debts.items(), key=lambda kv: (kv[0] != company.currency_id, kv[0].name))
        return " + ".join(ccy.format(amount) for ccy, amount in ordered) or False

    @api.model
    def _cst_order_invoices(self, order):
        """Open invoices of the order; invoices it when nothing is invoiced yet."""
        invoices = order.invoice_ids.filtered(lambda m: m.move_type == "out_invoice" and m.state != "cancel")
        drafts = invoices.filtered(lambda m: m.state == "draft")
        if drafts:
            drafts.action_post()
        open_inv = invoices.filtered(lambda m: m.state == "posted" and m.payment_state not in SETTLED)
        if not open_inv and order.invoice_status == "to invoice":
            new = order._create_invoices()
            new.action_post()
            open_inv = new.filtered(lambda m: m.move_type == "out_invoice")
        return open_inv

    @api.model
    def _cst_allocate(self, partner, company, orders=None, invoices=None, operation=None,
                      only_orders=False, credit_lines=None, targets=None, currency=None):
        """Apply the client's free money to his debts, oldest first.

        orders / invoices  — restrict to these debts (in this order);
        operation          — use only the money of that cash operation;
        credit_lines       — use only these receivable lines;
        currency           — only the debts kept in this currency.
        Returns the allocation records created.
        """
        partner = partner.commercial_partner_id
        company = company.sudo()
        if credit_lines is None:
            credit_lines = self._cst_credit_lines(partner, company, operation)
        credit_lines = credit_lines.sudo()
        if not credit_lines:
            return self.browse()
        if targets is not None:
            pass
        elif orders is not None or invoices is not None:
            targets = [(False, o, self.env["account.move"]) for o in (orders or [])]
            targets += [(False, self.env["sale.order"], m) for m in (invoices or [])]
        else:
            targets = self._cst_targets(partner, company, currency)

        Operation = self.env["cst.kassa.operation"].sudo()
        created = self.browse()
        env = self.sudo().with_company(company).with_context(cst_kassa_skip_guard=True)
        ctx_env = env.env
        for _date, order, invoice in targets:
            if all(cl.reconciled for cl in credit_lines):
                break
            order = order.with_env(ctx_env)
            if order:
                if order.state != "sale" or order.payment_amount_due <= 0:
                    continue
                inv = env._cst_order_invoices(order)
            else:
                inv = invoice.with_env(ctx_env)
            debit_lines = inv.line_ids.filtered(
                lambda l: l.account_id.account_type == "asset_receivable" and not l.reconciled
                and l.amount_residual > 0 and l.partner_id.commercial_partner_id == partner)
            for dl in debit_lines:
                for cl in credit_lines:
                    if cl.reconciled or dl.reconciled:
                        continue
                    before = cl.amount_residual
                    (cl + dl).reconcile()
                    used = cl.amount_residual - before
                    if company.currency_id.is_zero(used):
                        continue
                    pay = cl.move_id.origin_payment_id
                    # the operation whose money this line is — not necessarily the one being posted
                    op = Operation.search([("payment_id", "=", pay.id)], limit=1) if pay \
                        else Operation.search([("move_id", "=", cl.move_id.id)], limit=1)
                    created |= env.create({
                        "partner_id": partner.id,
                        "company_id": company.id,
                        "operation_id": op.id if op else False,
                        "payment_id": pay.id or False,
                        "source_name": pay.name or cl.move_id.name,
                        "order_id": order.id or False,
                        "invoice_id": dl.move_id.id,
                        "credit_line_id": cl.id,
                        "debit_line_id": dl.id,
                        "amount": used,
                        "user_id": self.env.uid,
                    })
        return created.with_env(self.env)

    def action_undo(self):
        """Take the money back off the order: it becomes an advance again."""
        for alloc in self.sudo():
            if alloc.state != "done":
                continue
            partials = self.env["account.partial.reconcile"].sudo().search([
                ("debit_move_id", "=", alloc.debit_line_id.id),
                ("credit_move_id", "=", alloc.credit_line_id.id),
            ])
            partials.with_context(cst_kassa_skip_guard=True).unlink()
            self.sudo().search([
                ("debit_line_id", "=", alloc.debit_line_id.id),
                ("credit_line_id", "=", alloc.credit_line_id.id),
                ("state", "=", "done"),
            ]).write({"state": "undone"})
        for partner in self.partner_id:
            self.env["cst.kassa.partner.balance"]._cst_refresh(partner)
        return True
