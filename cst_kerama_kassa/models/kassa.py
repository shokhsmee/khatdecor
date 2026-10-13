from odoo import _, api, fields, models
from odoo.exceptions import UserError


class Kassa(models.Model):
    _name = "cst.kassa"
    _description = "Cash Desk"
    _order = "company_id, sequence, id"
    _check_company_auto = True

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer()
    journal_id = fields.Many2one(
        "account.journal", string="Cash Journal", required=True, check_company=True,
        domain="[('type', 'in', ('cash', 'bank'))]", ondelete="restrict",
        help="A cash journal (till) or a bank journal (settlement account, «hisob raqam»).",
    )
    journal_type = fields.Selection(related="journal_id.type", string="Journal type")
    company_id = fields.Many2one(
        related="journal_id.company_id", store=True, precompute=True, readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency", compute="_compute_currency_id", store=True, precompute=True,
    )
    account_id = fields.Many2one(related="journal_id.default_account_id", string="Cash Account")
    user_ids = fields.Many2many(
        "res.users", string="Cashiers",
        help="Users who work with this cash desk. Leave empty to allow every cashier.",
    )
    day_ids = fields.One2many("cst.kassa.day", "kassa_id", string="Cash Days")
    current_day_id = fields.Many2one("cst.kassa.day", compute="_compute_current_day")
    day_state = fields.Selection(
        [("none", "Day not opened"), ("open", "Day open"), ("closed", "Waiting for confirmation")],
        compute="_compute_current_day",
    )
    balance = fields.Monetary(compute="_compute_balance", currency_field="currency_id")
    today_in = fields.Monetary(compute="_compute_current_day", currency_field="currency_id")
    today_out = fields.Monetary(compute="_compute_current_day", currency_field="currency_id")
    today_rate = fields.Float(compute="_compute_current_day", digits=(16, 2), string="Today's dollar rate")

    _journal_uniq = models.Constraint("unique(journal_id)", "This journal already has a cash desk.")

    @api.depends("journal_id.currency_id", "journal_id.company_id.currency_id")
    def _compute_currency_id(self):
        for kassa in self:
            kassa.currency_id = kassa.journal_id.currency_id or kassa.journal_id.company_id.currency_id

    def _compute_current_day(self):
        Day = self.env["cst.kassa.day"]
        for kassa in self:
            day = Day.search([("kassa_id", "=", kassa.id), ("state", "in", ("open", "closed"))],
                             order="date desc, id desc", limit=1)
            kassa.current_day_id = day
            kassa.day_state = day.state or "none"
            kassa.today_in = day.total_in
            kassa.today_out = day.total_out
            kassa.today_rate = day.usd_rate

    def _compute_balance(self):
        for kassa in self:
            kassa.balance = kassa._cst_balance()

    # ------------------------------------------------------------------
    # Accounting helpers
    # ------------------------------------------------------------------
    def _cst_uses_foreign_currency(self):
        self.ensure_one()
        return self.currency_id != self.company_id.currency_id

    def _cst_outstanding_accounts(self):
        """Accounts a payment of this journal lands on before the statement clears
        it.  A till books straight to its own account, so for cash this is empty."""
        self.ensure_one()
        journal = self.journal_id
        method_lines = journal.inbound_payment_method_line_ids | journal.outbound_payment_method_line_ids
        return method_lines.payment_account_id - journal.default_account_id

    def _cst_money_accounts(self):
        self.ensure_one()
        return self.journal_id.default_account_id | self._cst_outstanding_accounts()

    def _cst_money_account(self, direction):
        """Account a kassa entry books the money on.  For a bank (hisob raqam) it is
        the outstanding account, so the bank statement later matches the entry
        instead of duplicating it."""
        self.ensure_one()
        journal = self.journal_id
        lines = journal.inbound_payment_method_line_ids if direction == "in" \
            else journal.outbound_payment_method_line_ids
        return lines.filtered("payment_account_id")[:1].payment_account_id or journal.default_account_id

    def _cst_is_money_line(self, line):
        self.ensure_one()
        if line.account_id == self.journal_id.default_account_id:
            return True
        return line.account_id in self._cst_outstanding_accounts() and line.journal_id == self.journal_id

    def _cst_balance_domain(self):
        self.ensure_one()
        domain = [
            ("company_id", "=", self.company_id.id),
            ("parent_state", "=", "posted"),
        ]
        outstanding = self._cst_outstanding_accounts()
        if outstanding:
            return domain + ["|", ("account_id", "=", self.journal_id.default_account_id.id),
                             "&", ("account_id", "in", outstanding.ids), ("journal_id", "=", self.journal_id.id)]
        return domain + [("account_id", "=", self.journal_id.default_account_id.id)]

    def _cst_line_amount(self, line):
        """Amount of a cash line in the kassa currency (debit = money in)."""
        return line.amount_currency if self._cst_uses_foreign_currency() else line.balance

    def _cst_balance(self, before=None, on=None):
        """Cash balance in the kassa currency.

        ``before`` — only lines dated strictly before that date,
        ``on`` — returns (in, out) for lines dated on that date.
        """
        self.ensure_one()
        if not self.journal_id.default_account_id:
            return (0.0, 0.0) if on else 0.0
        domain = self._cst_balance_domain()
        field = "amount_currency" if self._cst_uses_foreign_currency() else "balance"
        Line = self.env["account.move.line"].sudo()
        if on:
            amounts = [self._cst_line_amount(l) for l in Line.search(domain + [("date", "=", on)])]
            return sum(a for a in amounts if a > 0), -sum(a for a in amounts if a < 0)
        if before:
            domain = domain + [("date", "<", before)]
        groups = Line._read_group(domain, [], [f"{field}:sum"])
        return groups[0][0] if groups else 0.0

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _cst_check_cashier(self):
        self.ensure_one()
        user = self.env.user
        if self.user_ids and user not in self.user_ids \
                and not user.has_group("cst_kerama_kassa.group_kassa_manager"):
            raise UserError(_("You are not a cashier of %(kassa)s.", kassa=self.display_name))

    def action_open_day(self):
        """Open today's day — through the wizard that asks for the day's dollar rate."""
        self.ensure_one()
        self._cst_check_cashier()
        Day = self.env["cst.kassa.day"]
        today = fields.Date.context_today(self)
        still_open = Day.search([("kassa_id", "=", self.id), ("state", "=", "open")], limit=1)
        if still_open:
            if still_open.date == today:
                return still_open._cst_form_action()
            raise UserError(_(
                "The cash day of %(date)s is still open. Close it before opening a new day.",
                date=still_open.date,
            ))
        existing = Day.search([("kassa_id", "=", self.id), ("date", "=", today)], limit=1)
        if existing:
            if existing.allow_reopen:
                # closed or confirmed today: the day form carries the Reopen button
                return existing._cst_form_action()
            raise UserError(_("Today's cash day is already %(state)s.",
                              state=dict(existing._fields["state"].selection)[existing.state]))
        return {
            "type": "ir.actions.act_window",
            "name": _("Open the day — %(kassa)s", kassa=self.name),
            "res_model": "cst.kassa.day.open",
            "view_mode": "form",
            "target": "new",
            "context": {"default_kassa_id": self.id},
        }

    def action_reopen_day(self):
        self.ensure_one()
        if not self.current_day_id:
            raise UserError(_("There is no closed cash day to reopen."))
        self.current_day_id.action_reopen()
        return self.current_day_id._cst_form_action()

    @api.model
    def _cst_ensure_kassas(self):
        """One kassa per cash journal and per «HR» bank journal (hisob raqam).
        Runs on every upgrade; archived kassas count as existing."""
        Kassa = self.with_context(active_test=False).sudo()
        several = self.env["res.company"].sudo().search_count([]) > 1
        journals = self.env["account.journal"].sudo().search([("type", "in", ("cash", "bank"))])
        for journal in journals:
            if journal.type == "bank" and not (journal.name or "").upper().startswith("HR"):
                continue
            if Kassa.search_count([("journal_id", "=", journal.id)]):
                continue
            name = f"{journal.name} · {journal.company_id.name}" if several else journal.name
            Kassa.create({"name": name, "journal_id": journal.id})

    def _cst_operation_action(self, direction):
        self.ensure_one()
        self._cst_check_cashier()
        day = self.current_day_id
        if not day or day.state != "open":
            raise UserError(_("Open the cash day first."))
        return day._cst_new_operation_action(direction)

    def action_new_in(self):
        return self._cst_operation_action("in")

    def action_new_out(self):
        return self._cst_operation_action("out")

    def action_new_transfer(self):
        action = self._cst_operation_action("out")
        action["context"]["default_type_out"] = "transfer_out"
        action["name"] = _("To another kassa")
        return action

    def action_close_day(self):
        self.ensure_one()
        if not self.current_day_id or self.current_day_id.state != "open":
            raise UserError(_("There is no open cash day."))
        return self.current_day_id.action_close()

    def action_current_day(self):
        self.ensure_one()
        if not self.current_day_id:
            raise UserError(_("There is no open cash day."))
        return self.current_day_id._cst_form_action()

    def action_view_days(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("cst_kerama_kassa.action_kassa_day")
        action["domain"] = [("kassa_id", "=", self.id)]
        action["context"] = {"default_kassa_id": self.id}
        return action

    def action_view_operations(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("cst_kerama_kassa.action_kassa_operation")
        action["domain"] = [("kassa_id", "=", self.id)]
        action["context"] = {"search_default_filter_done": 1}
        return action
