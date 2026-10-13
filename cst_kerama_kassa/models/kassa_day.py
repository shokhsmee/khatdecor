from odoo import _, api, fields, models
from odoo.exceptions import UserError


class KassaDay(models.Model):
    _name = "cst.kassa.day"
    _description = "Cash Day"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char(readonly=True, copy=False, default="/")
    kassa_id = fields.Many2one("cst.kassa", string="Kassa", required=True, readonly=True,
                               ondelete="restrict", index=True)
    journal_id = fields.Many2one(related="kassa_id.journal_id", store=True)
    company_id = fields.Many2one(related="kassa_id.company_id", store=True, precompute=True)
    currency_id = fields.Many2one(related="kassa_id.currency_id", store=True)
    date = fields.Date(required=True, readonly=True, default=fields.Date.context_today, index=True)
    state = fields.Selection(
        [("open", "Open"), ("closed", "Closed"), ("confirmed", "Confirmed")],
        default="open", required=True, readonly=True, tracking=True, copy=False,
    )
    opened_by_id = fields.Many2one("res.users", string="Opened by", readonly=True,
                                   default=lambda self: self.env.user)
    opened_at = fields.Datetime(string="Opened at", readonly=True, default=fields.Datetime.now)
    closed_by_id = fields.Many2one("res.users", string="Closed by", readonly=True, copy=False)
    closed_at = fields.Datetime(string="Closed at", readonly=True, copy=False)
    confirmed_by_id = fields.Many2one("res.users", string="Confirmed by", readonly=True, copy=False)
    confirmed_at = fields.Datetime(string="Confirmed at", readonly=True, copy=False)

    opening_balance = fields.Monetary(string="Opening balance", readonly=True,
                                      currency_field="currency_id")
    total_in = fields.Monetary(string="Cash in", readonly=True, currency_field="currency_id")
    total_out = fields.Monetary(string="Cash out", readonly=True, currency_field="currency_id")
    expected_balance = fields.Monetary(string="Expected balance", readonly=True,
                                       currency_field="currency_id",
                                       help="Opening balance + cash in - cash out.")
    counted_balance = fields.Monetary(string="Counted cash", readonly=True, tracking=True,
                                      currency_field="currency_id",
                                      help="Money actually counted in the till when the day was closed.")
    difference = fields.Monetary(compute="_compute_difference", store=True,
                                 currency_field="currency_id",
                                 help="Counted cash - expected balance. Negative = shortage.")
    difference_move_id = fields.Many2one("account.move", string="Difference entry", readonly=True,
                                         copy=False)
    old_difference_move_ids = fields.Many2many(
        "account.move", "cst_kassa_day_old_diff_rel", "day_id", "move_id", readonly=True, copy=False,
        string="Cancelled difference entries",
        help="Difference entries of an earlier confirmation and their reversals; kept out of the day's totals.")
    usd_rate = fields.Float(
        string="Dollar rate", digits=(16, 2), tracking=True,
        help="The day's rate: how many units of this kassa's currency make one dollar. "
             "New operations of the day take it; each operation can still change its own rate.")
    allow_reopen = fields.Boolean(related="company_id.cst_kassa_allow_reopen")
    is_last_day = fields.Boolean(compute="_compute_is_last_day")
    note = fields.Text(string="Note")

    operation_ids = fields.One2many("cst.kassa.operation", "day_id", string="Operations")
    operation_count = fields.Integer(compute="_compute_operation_count")
    move_line_ids = fields.Many2many("account.move.line", compute="_compute_move_line_ids",
                                     string="All cash movements")
    outside_count = fields.Integer(compute="_compute_move_line_ids")

    _kassa_date_uniq = models.Constraint("unique(kassa_id, date)",
                                         "This kassa already has a cash day for this date.")

    def _compute_is_last_day(self):
        for day in self:
            day.is_last_day = not self.search_count([("kassa_id", "=", day.kassa_id.id), ("date", ">", day.date)])

    @api.depends("counted_balance", "expected_balance", "state")
    def _compute_difference(self):
        for day in self:
            day.difference = (day.counted_balance - day.expected_balance) \
                if day.state in ("closed", "confirmed") else 0.0

    def _compute_operation_count(self):
        for day in self:
            day.operation_count = len(day.operation_ids.filtered(lambda o: o.state == "done"))

    def _compute_move_line_ids(self):
        for day in self:
            if not day.kassa_id.journal_id.default_account_id:
                day.move_line_ids = False
                day.outside_count = 0
                continue
            lines = self.env["account.move.line"].sudo().search(
                day.kassa_id._cst_balance_domain() + [("date", "=", day.date)], order="id")
            day.move_line_ids = lines
            own = day.operation_ids.filtered(lambda o: o.state == "done")
            own_moves = own.payment_id.move_id | own.move_id | day.difference_move_id | day.old_difference_move_ids
            day.outside_count = len(lines.filtered(lambda l: l.move_id not in own_moves))

    @api.model_create_multi
    def create(self, vals_list):
        days = super().create(vals_list)
        for day in days:
            if day.name == "/":
                day.name = self.env["ir.sequence"].next_by_code("cst.kassa.day") or "/"
            day._cst_refresh()
        return days

    def _compute_display_name(self):
        for day in self:
            day.display_name = f"{day.kassa_id.name} — {day.date}" if day.date else day.name

    # ------------------------------------------------------------------
    def _cst_refresh(self):
        for day in self.filtered(lambda d: d.state != "confirmed"):
            kassa = day.kassa_id
            opening = kassa._cst_balance(before=day.date)
            total_in, total_out = kassa._cst_balance(on=day.date)
            for move in day.difference_move_id | day.old_difference_move_ids:
                for line in move.line_ids.filtered(kassa._cst_is_money_line):
                    amount = kassa._cst_line_amount(line)
                    total_in -= max(amount, 0.0)
                    total_out -= max(-amount, 0.0)
            day.write({
                "opening_balance": opening,
                "total_in": total_in,
                "total_out": total_out,
                "expected_balance": opening + total_in - total_out,
            })

    def _cst_form_action(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "cst.kassa.day",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }

    def _cst_new_operation_action(self, direction):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Cash in") if direction == "in" else _("Cash out"),
            "res_model": "cst.kassa.operation",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_day_id": self.id,
                "default_direction": direction,
                "default_operation_type": "customer_in" if direction == "in" else "expense",
            },
        }

    def action_new_transfer(self):
        self.ensure_one()
        action = self._cst_new_operation_action("out")
        action["context"]["default_type_out"] = "transfer_out"
        action["name"] = _("To another kassa")
        return action

    def _cst_is_manager(self):
        return self.env.user.has_group("cst_kerama_kassa.group_kassa_manager")

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_refresh(self):
        self._cst_refresh()

    def action_new_in(self):
        self.ensure_one()
        if self.state != "open":
            raise UserError(_("The cash day is not open."))
        return self._cst_new_operation_action("in")

    def action_new_out(self):
        self.ensure_one()
        if self.state != "open":
            raise UserError(_("The cash day is not open."))
        return self._cst_new_operation_action("out")

    def action_close(self):
        self.ensure_one()
        if self.state != "open":
            raise UserError(_("Only an open cash day can be closed."))
        self.kassa_id._cst_check_cashier()
        if self.operation_ids.filtered(lambda o: o.state == "draft"):
            raise UserError(_("Some operations of this day are still drafts. "
                              "Post or delete them before closing the day."))
        self._cst_refresh()
        return {
            "type": "ir.actions.act_window",
            "name": _("Close the cash day"),
            "res_model": "cst.kassa.day.close",
            "view_mode": "form",
            "target": "new",
            "context": {"default_day_id": self.id, "default_counted_balance": self.expected_balance},
        }

    def _cst_do_close(self, counted, note=False):
        self.ensure_one()
        self._cst_refresh()
        vals = {
            "state": "closed",
            "counted_balance": counted,
            "closed_by_id": self.env.user.id,
            "closed_at": fields.Datetime.now(),
        }
        if note:
            vals["note"] = ((self.note + "\n") if self.note else "") + note
        self.write(vals)

    def action_reopen(self):
        """Closed day: any cashier of the kassa.  Confirmed day: a kassa manager;
        its difference entry is reversed.  Only the kassa's last day, and only when
        reopening is switched on in Kassa settings."""
        for day in self:
            if not day.company_id.cst_kassa_allow_reopen:
                raise UserError(_("Reopening cash days is switched off in Kassa ▸ Configuration ▸ Settings."))
            if day.state not in ("closed", "confirmed"):
                raise UserError(_("Only a closed or confirmed day can be reopened."))
            if not day.is_last_day:
                raise UserError(_("Only the last day of a kassa can be reopened — %(kassa)s already has a later day.",
                                  kassa=day.kassa_id.name))
            if day.state == "confirmed" and not day._cst_is_manager():
                raise UserError(_("Only a kassa manager can reopen a confirmed day."))
            day.kassa_id._cst_check_cashier()
            if self.search_count([("kassa_id", "=", day.kassa_id.id), ("state", "=", "open"), ("id", "!=", day.id)]):
                raise UserError(_("%(kassa)s already has an open day.", kassa=day.kassa_id.name))
            was = dict(day._fields["state"].selection)[day.state]
            vals = {"state": "open", "counted_balance": 0.0, "closed_by_id": False, "closed_at": False,
                    "confirmed_by_id": False, "confirmed_at": False}
            day.write(vals)
            if day.difference_move_id:
                move = day.difference_move_id.sudo().with_context(cst_kassa_skip_guard=True, cst_allow_negative=True)
                reversal = move._reverse_moves(default_values_list=[{"date": day.date}], cancel=True)
                day.write({"old_difference_move_ids": [(4, move.id), (4, reversal.id)],
                           "difference_move_id": False})
            day._cst_refresh()
            day.message_post(body=_("Day reopened (was: %(state)s).", state=was))
        return True

    def action_confirm(self):
        for day in self:
            if not day._cst_is_manager():
                raise UserError(_("Only a kassa manager can confirm a cash day."))
            if day.state != "closed":
                raise UserError(_("Close the day before confirming it."))
            day._cst_refresh()
            day.invalidate_recordset(["difference"])
            if not day.currency_id.is_zero(day.difference):
                day._cst_post_difference()
            day.write({
                "state": "confirmed",
                "confirmed_by_id": self.env.user.id,
                "confirmed_at": fields.Datetime.now(),
            })

    def _cst_post_difference(self):
        """Post counted - expected to the journal's cash difference account."""
        self.ensure_one()
        kassa = self.kassa_id
        journal = kassa.journal_id
        company = kassa.company_id
        diff = self.difference
        if diff > 0:
            account = journal.profit_account_id or company.default_cash_difference_income_account_id
        else:
            account = journal.loss_account_id or company.default_cash_difference_expense_account_id
        if not account:
            raise UserError(_(
                "Set the cash difference (profit / loss) accounts on journal %(journal)s "
                "before confirming a day with a difference.", journal=journal.display_name))
        amount_company = kassa.currency_id._convert(abs(diff), company.currency_id, company, self.date)
        sign = 1 if diff > 0 else -1
        common = {"currency_id": kassa.currency_id.id, "name": _("Cash difference %(day)s", day=self.name)}
        cash_line = dict(common, account_id=kassa._cst_money_account("in" if diff > 0 else "out").id,
                         amount_currency=sign * abs(diff),
                         debit=amount_company if sign > 0 else 0.0,
                         credit=amount_company if sign < 0 else 0.0)
        counter_line = dict(common, account_id=account.id,
                            amount_currency=-sign * abs(diff),
                            debit=amount_company if sign < 0 else 0.0,
                            credit=amount_company if sign > 0 else 0.0)
        move = self.env["account.move"].sudo().with_company(company).create({
            "move_type": "entry",
            "journal_id": journal.id,
            "date": self.date,
            "ref": _("Cash difference %(day)s", day=self.name),
            "line_ids": [(0, 0, cash_line), (0, 0, counter_line)],
        })
        move.with_context(cst_allow_negative=True, cst_kassa_skip_guard=True).action_post()
        self.difference_move_id = move

    def action_view_outside(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Cash movements"),
            "res_model": "account.move.line",
            "view_mode": "list",
            "domain": [("id", "in", self.move_line_ids.ids)],
        }

    def unlink(self):
        for day in self:
            if day.state == "confirmed" or day.operation_ids.filtered(lambda o: o.state == "done"):
                raise UserError(_("A confirmed day or a day with posted operations cannot be deleted."))
        return super().unlink()
