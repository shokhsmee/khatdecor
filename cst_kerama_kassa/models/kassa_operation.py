from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import formatLang

from ..tools import uz_amount_words

TYPES_IN = [
    ("customer_in", "Payment from a client"),
    ("supplier_in", "Refund from a supplier"),
    ("other_in", "Other income"),
    ("transfer_in", "From another kassa"),
]
TYPES_OUT = [
    ("customer_out", "Refund to a client"),
    ("supplier_out", "Payment to a supplier"),
    ("expense", "Expense"),
    ("employee_advance", "Advance to an employee"),
    ("transfer_out", "To another kassa"),
]
PARTNER_TYPES = ("customer_in", "supplier_in", "customer_out", "supplier_out")
CATEGORY_TYPES = ("other_in", "expense")
TRANSFER_TYPES = ("transfer_in", "transfer_out")


class KassaOperation(models.Model):
    _name = "cst.kassa.operation"
    _description = "Cash Operation"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char(readonly=True, copy=False, default="/")
    day_id = fields.Many2one(
        "cst.kassa.day", string="Cash day", required=True, index=True, ondelete="restrict",
        domain="[('state', '=', 'open')]",
    )
    kassa_id = fields.Many2one(related="day_id.kassa_id", store=True, precompute=True)
    journal_id = fields.Many2one(related="day_id.journal_id", store=True)
    company_id = fields.Many2one(related="day_id.company_id", store=True, precompute=True)
    currency_id = fields.Many2one(related="day_id.currency_id", store=True, precompute=True)
    company_currency_id = fields.Many2one(related="company_id.currency_id", string="Company currency")
    date = fields.Date(related="day_id.date", store=True)
    direction = fields.Selection([("in", "Cash in"), ("out", "Cash out")], required=True, default="in",
                                 tracking=True)
    type_in = fields.Selection(TYPES_IN, string="Cash in type", default="customer_in")
    type_out = fields.Selection(TYPES_OUT, string="Cash out type", default="expense")
    operation_type = fields.Selection(TYPES_IN + TYPES_OUT, string="Type",
                                      compute="_compute_operation_type", store=True, precompute=True)
    partner_id = fields.Many2one("res.partner", string="Partner", tracking=True, index=True,
                                 check_company=True)
    commercial_partner_id = fields.Many2one(related="partner_id.commercial_partner_id", store=True)
    employee_id = fields.Many2one(
        "hr.employee", string="Employee", tracking=True, index="btree_not_null", check_company=True,
        domain="[('company_id', '=', company_id)]",
        help="The advance is deducted from this employee's salary in the payroll period of its date.")
    payroll_line_id = fields.Many2one("cst.payroll.line", string="Payroll line", readonly=True, copy=False)
    partner_tag_ids = fields.Many2many(
        "res.partner.category", compute="_compute_partner_tag_ids", string="Allowed tags",
        help="Contacts offered for this operation type (Kassa settings: client / supplier tags).")
    employee_tag_ids = fields.Many2many(
        "res.partner.category", compute="_compute_partner_tag_ids", string="Allowed employee tags")
    partner_tag_warning = fields.Char(compute="_compute_partner_tag_ids", string="Tag warning")
    payroll_period_id = fields.Many2one(related="payroll_line_id.period_id", string="Payroll period")
    employee_balance = fields.Monetary(
        compute="_compute_employee_balance", currency_field="company_currency_id",
        string="Salary balance", groups="cst_kerama_payroll.group_payroll_user",
        help="What the company still owes the employee (accrued - withheld). Negative: overdrawn.")
    amount = fields.Monetary(required=True, tracking=True, currency_field="currency_id")
    is_foreign = fields.Boolean(compute="_compute_is_foreign",
                                help="The kassa's currency is not the company currency (a so'm kassa).")
    rate = fields.Float(
        string="Dollar rate", digits=(16, 2), tracking=True,
        compute="_compute_rate", store=True, readonly=False, precompute=True,
        help="Units of the kassa currency per dollar for this operation. Taken from the day's rate; "
             "change it here if this client pays at another rate. The ledger and the settlement use it.")
    settle_hint = fields.Char(compute="_compute_settle_hint", string="In dollars")
    amount_company = fields.Monetary(
        compute="_compute_amount_company", store=True, currency_field="company_currency_id",
        string="Amount (company currency)",
        help="What the ledger booked, in the company currency — the figure to add up across "
             "cash desks in different currencies.")
    category_id = fields.Many2one(
        "cst.kassa.category", string="Category", check_company=True,
        domain="[('direction', '=', direction), ('company_id', '=', company_id)]",
    )
    sale_order_ids = fields.Many2many(
        "sale.order", string="Sales orders", check_company=True,
        domain="[('partner_id', 'child_of', commercial_partner_id), ('state', '=', 'sale'), "
               "('company_id', '=', company_id)] + ([('currency_id', '=', debt_currency_id)] "
               "if debt_currency_id else [])",
        help="Optional. The money is applied to these orders first.",
    )
    debt_currency_ids = fields.Many2many(
        "res.currency", compute="_compute_partner_figures", string="Debt currencies")
    debt_currency_count = fields.Integer(compute="_compute_partner_figures", string="Debt currency count")
    debt_currency_id = fields.Many2one(
        "res.currency", string="Pay the debt in",
        domain="[('id', 'in', debt_currency_ids)]",
        help="The client owes separately in several currencies: choose which debt this money pays. "
             "A so'm payment can close a dollar debt — it counts at the dollar rate above. "
             "Empty: the oldest debts, whatever their currency.")
    allocation_mode = fields.Selection(
        [("auto", "Settle the oldest debts automatically"),
         ("orders", "Settle only the selected orders"),
         ("none", "Keep as advance")],
        string="Settlement", default="auto", required=True,
        help="What happens to the client's money: it always lowers the client's balance; "
             "here you choose which sales orders it pays.",
    )
    transfer_kassa_id = fields.Many2one(
        "cst.kassa", string="Other kassa", check_company=True, index="btree_not_null",
        domain="[('company_id', '=', company_id), ('id', '!=', kassa_id)]",
        help="The kassa the money goes to (cash out) or comes from (cash in). "
             "Both kassas need an open cash day on this date.")
    transfer_currency_id = fields.Many2one(related="transfer_kassa_id.currency_id", string="Other kassa currency")
    transfer_amount = fields.Monetary(
        string="Amount in the other kassa", currency_field="transfer_currency_id",
        compute="_compute_transfer_amount", store=True, readonly=False, precompute=True,
        help="What the other kassa receives (or gives). Filled from the dollar rate when the "
             "currencies differ; change it to the amount really exchanged.")
    transfer_op_id = fields.Many2one("cst.kassa.operation", string="Paired operation", readonly=True,
                                     copy=False, index="btree_not_null")
    transfer_day_note = fields.Char(compute="_compute_transfer_day_note", string="Other kassa day")
    transfer_day_blocking = fields.Boolean(compute="_compute_transfer_day_note")
    memo = fields.Char(string="Note")
    state = fields.Selection([("draft", "Draft"), ("done", "Posted"), ("cancel", "Cancelled")],
                             default="draft", required=True, readonly=True, tracking=True, copy=False)
    payment_id = fields.Many2one("account.payment", string="Payment", readonly=True, copy=False)
    move_id = fields.Many2one("account.move", string="Journal entry", readonly=True, copy=False)
    allocation_ids = fields.One2many("cst.kassa.allocation", "operation_id", string="Settlements")
    allocated_amount = fields.Monetary(compute="_compute_allocated", currency_field="company_currency_id",
                                       string="Settled")
    unallocated_amount = fields.Monetary(compute="_compute_allocated", currency_field="company_currency_id",
                                         string="Left as advance")
    partner_debt = fields.Monetary(compute="_compute_partner_figures", currency_field="company_currency_id",
                                   string="Client debt")
    partner_advance = fields.Monetary(compute="_compute_partner_figures",
                                      currency_field="company_currency_id", string="Client advance")
    partner_balance = fields.Monetary(compute="_compute_partner_figures",
                                      currency_field="company_currency_id", string="Client balance")
    partner_debt_detail = fields.Char(compute="_compute_partner_figures", string="Debt by currency",
                                      help="Each debt in its own currency.")
    day_state = fields.Selection(related="day_id.state", string="Day state")
    created_by_id = fields.Many2one("res.users", string="Cashier", readonly=True,
                                    default=lambda self: self.env.user)
    posted_at = fields.Datetime(string="Posted at", readonly=True, copy=False)

    @api.depends("direction", "type_in", "type_out")
    def _compute_operation_type(self):
        for op in self:
            op.operation_type = op.type_in if op.direction == "in" else op.type_out

    @api.depends("operation_type", "company_id", "partner_id.category_id", "employee_id")
    def _compute_partner_tag_ids(self):
        Tag = self.env["res.partner.category"]
        for op in self:
            company = op.company_id.sudo()
            if op.operation_type in ("customer_in", "customer_out"):
                tags, role = company.cst_kassa_client_tag_ids, _("client")
            elif op.operation_type in ("supplier_in", "supplier_out"):
                tags, role = company.cst_kassa_supplier_tag_ids, _("supplier")
            else:
                tags, role = Tag, ""
            op.partner_tag_ids = tags
            op.employee_tag_ids = company.cst_kassa_employee_tag_ids \
                if op.operation_type == "employee_advance" else Tag
            warning = False
            partner = op.partner_id.commercial_partner_id
            if tags and partner and not (partner.category_id | op.partner_id.category_id) & tags:
                warning = _("%(partner)s has no %(role)s tag (%(tags)s). Add the tag on the contact if this is right.",
                            partner=partner.display_name, role=role, tags=", ".join(tags.mapped("name")))
            op.partner_tag_warning = warning

    @api.depends("currency_id", "company_id")
    def _compute_is_foreign(self):
        for op in self:
            op.is_foreign = bool(op.currency_id and op.company_id
                                 and op.currency_id != op.company_id.currency_id)

    @api.depends("day_id.usd_rate")
    def _compute_rate(self):
        for op in self:
            if op.state == "draft":
                op.rate = op.day_id.usd_rate
            elif not op.rate and op.is_foreign and op.amount_company:
                # posted before rates existed: show the rate it was really booked at
                op.rate = op.amount / op.amount_company
            else:
                op.rate = op.rate

    def _cst_company_amount(self):
        """The amount in company currency: at the operation's own rate for a so'm
        kassa, at Odoo's rate when no rate was given."""
        self.ensure_one()
        company = self.company_id
        if not (self.currency_id and company):
            return 0.0
        if self.currency_id == company.currency_id:
            return self.amount
        if self.rate > 0:
            return company.currency_id.round(self.amount / self.rate)
        return self.currency_id._convert(self.amount, company.currency_id, company,
                                         self.date or fields.Date.context_today(self))

    @api.depends("amount", "rate", "is_foreign", "company_id")
    def _compute_settle_hint(self):
        for op in self:
            if op.is_foreign and op.amount and op.rate > 0:
                op.settle_hint = "%s ÷ %s = %s" % (
                    op.currency_id.format(op.amount), formatLang(op.env, op.rate, digits=2),
                    op.company_id.currency_id.format(op._cst_company_amount()))
            else:
                op.settle_hint = False

    @api.depends("amount", "currency_id", "date", "company_id", "state", "rate",
                 "payment_id.move_id.line_ids.balance", "move_id.line_ids.balance")
    def _compute_amount_company(self):
        for op in self:
            moves = op.sudo().payment_id.move_id | op.sudo().move_id
            kassa = op.sudo().kassa_id
            lines = moves.line_ids.filtered(kassa._cst_is_money_line) if kassa else moves.browse()
            if op.state == "done" and lines:
                op.amount_company = abs(sum(lines.mapped("balance")))
            else:
                op.amount_company = op._cst_company_amount()

    @api.depends("amount", "rate", "currency_id", "transfer_kassa_id", "operation_type")
    def _compute_transfer_amount(self):
        for op in self:
            if op.state != "draft":
                op.transfer_amount = op.transfer_amount
                continue
            other = op.transfer_kassa_id
            if op.operation_type not in TRANSFER_TYPES or not other or not op.amount:
                op.transfer_amount = 0.0
                continue
            if other.currency_id == op.currency_id:
                op.transfer_amount = op.amount
                continue
            company = op.company_id
            value = op._cst_company_amount()
            if other.currency_id == company.currency_id:
                op.transfer_amount = value
                continue
            other_day = op._cst_transfer_day(raise_if_missing=False)
            rate = other_day.usd_rate or op.rate
            if rate > 0:
                op.transfer_amount = other.currency_id.round(value * rate)
            else:
                op.transfer_amount = company.currency_id._convert(
                    value, other.currency_id, company, op.date or fields.Date.context_today(op))

    def _cst_transfer_day_status(self):
        """Where the other side of a transfer lands: (day, message, blocking).
        day is the other kassa's open day on this date, or empty when a new day
        will be opened for it at posting."""
        self.ensure_one()
        Day = self.env["cst.kassa.day"].sudo()
        other = self.transfer_kassa_id
        if not other or not self.date:
            return Day, False, False
        day = Day.search([("kassa_id", "=", other.id), ("date", "=", self.date)], limit=1)
        if day.state == "open":
            return day, _("The money is booked in %(day)s.", day=day.display_name), False
        states = dict(Day._fields["state"].selection)
        if day:
            return Day, _("The cash day %(day)s is already %(state)s. Reopen it first.",
                          day=day.display_name, state=states[day.state].lower()), True
        still_open = Day.search([("kassa_id", "=", other.id), ("state", "=", "open")], limit=1)
        if still_open:
            return Day, _("%(kassa)s still has an open cash day of %(date)s. Close it first, "
                          "or send the money on that date.",
                          kassa=other.name, date=still_open.date), True
        later = Day.search([("kassa_id", "=", other.id), ("date", ">", self.date)], limit=1)
        if later:
            return Day, _("%(kassa)s already has a cash day after %(date)s (%(later)s); "
                          "a transfer cannot be booked before it.",
                          kassa=other.name, date=self.date, later=later.date), True
        return Day, _("%(kassa)s has no cash day on %(date)s: it is opened automatically "
                      "when you post.", kassa=other.name, date=self.date), False

    def _cst_transfer_day(self, raise_if_missing=True, create=False):
        """The other kassa's open cash day on this operation's date; with create=True
        a missing day is opened at this day's dollar rate."""
        self.ensure_one()
        day, message, blocking = self._cst_transfer_day_status()
        if day:
            return day
        if blocking:
            if raise_if_missing:
                raise UserError(message)
            return day
        if create:
            day = self.env["cst.kassa.day"].sudo().create({
                "kassa_id": self.transfer_kassa_id.id,
                "date": self.date,
                "usd_rate": self.day_id.usd_rate or self.rate,
                "opened_by_id": self.env.uid,
                "note": _("Opened automatically by the transfer %(name)s from %(kassa)s.",
                          name=self.name, kassa=self.kassa_id.name),
            })
            return day
        if raise_if_missing:
            raise UserError(message)
        return day

    @api.depends("transfer_kassa_id", "date", "operation_type", "state")
    def _compute_transfer_day_note(self):
        for op in self:
            if op.operation_type in TRANSFER_TYPES and op.state == "draft" and op.transfer_kassa_id:
                day, message, blocking = op._cst_transfer_day_status()
                op.transfer_day_note = message
                op.transfer_day_blocking = blocking
            else:
                op.transfer_day_note = False
                op.transfer_day_blocking = False

    @api.depends("employee_id", "state")
    def _compute_employee_balance(self):
        for op in self:
            op.employee_balance = op.employee_id.sudo().cst_payroll_balance if op.employee_id else 0.0

    @api.depends("allocation_ids.amount", "allocation_ids.state", "payment_id", "state")
    def _compute_allocated(self):
        for op in self:
            allocated = sum(op.allocation_ids.filtered(lambda a: a.state == "done").mapped("amount"))
            op.allocated_amount = allocated
            left = 0.0
            if op.state == "done" and op.operation_type == "customer_in" and op.payment_id.move_id:
                lines = op.sudo().payment_id.move_id.line_ids.filtered(
                    lambda l: l.account_id.account_type == "asset_receivable")
                left = -sum(lines.mapped("amount_residual"))
            op.unallocated_amount = left

    @api.depends("partner_id", "company_id", "operation_type", "state")
    def _compute_partner_figures(self):
        Balance = self.env["cst.kassa.partner.balance"]
        Alloc = self.env["cst.kassa.allocation"]
        for op in self:
            if op.partner_id and op.operation_type in ("customer_in", "customer_out") and op.company_id:
                partner = op.partner_id.commercial_partner_id
                fig = Balance._cst_figures(partner, op.company_id)
                op.partner_debt = fig["total_debt"]
                op.partner_advance = fig["advance"]
                op.partner_balance = fig["balance"]
                debts = Alloc._cst_debt_by_currency(partner, op.company_id)
                op.debt_currency_ids = [ccy.id for ccy, amount in debts.items() if amount > 0]
                op.debt_currency_count = len(op.debt_currency_ids)
                op.partner_debt_detail = fig["debt_detail"]
            else:
                op.partner_debt = op.partner_advance = op.partner_balance = 0.0
                op.debt_currency_ids = False
                op.debt_currency_count = 0
                op.partner_debt_detail = False

    @api.onchange("sale_order_ids")
    def _onchange_sale_order_ids(self):
        if self.sale_order_ids and self.allocation_mode == "auto":
            self.allocation_mode = "orders"

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        if self.employee_id:
            self.partner_id = self.employee_id.sudo().work_contact_id

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        if self.sale_order_ids and self.partner_id:
            self.sale_order_ids = self.sale_order_ids.filtered(
                lambda o: o.partner_id.commercial_partner_id == self.partner_id.commercial_partner_id)
        if self.debt_currency_id and self.debt_currency_id not in self.debt_currency_ids:
            self.debt_currency_id = False

    @api.onchange("debt_currency_id")
    def _onchange_debt_currency_id(self):
        if self.debt_currency_id and self.sale_order_ids:
            self.sale_order_ids = self.sale_order_ids.filtered(
                lambda o: o.currency_id == self.debt_currency_id)

    @api.constrains("amount")
    def _check_amount(self):
        for op in self:
            if op.amount <= 0:
                raise ValidationError(_("The amount must be greater than zero."))

    @api.model_create_multi
    def create(self, vals_list):
        ops = super().create(vals_list)
        for op in ops:
            if op.day_id.state != "open":
                raise UserError(_("Operations can only be added to an open cash day."))
            if not self.env.context.get("cst_kassa_transfer_pair"):
                op.day_id.kassa_id._cst_check_cashier()
            if op.name == "/":
                op.name = self.env["ir.sequence"].next_by_code("cst.kassa.operation") or "/"
        return ops

    def write(self, vals):
        protected = set(vals) - {"memo", "message_main_attachment_id"}
        if protected and not self.env.context.get("cst_kassa_internal"):
            for op in self:
                if op.state != "draft":
                    raise UserError(_("A posted or cancelled operation cannot be changed."))
        return super().write(vals)

    def unlink(self):
        if any(op.state == "done" for op in self):
            raise UserError(_("A posted operation cannot be deleted; cancel it instead."))
        return super().unlink()

    # ------------------------------------------------------------------
    # Posting
    # ------------------------------------------------------------------
    def action_done(self):
        for op in self:
            op._cst_post()
        if len(self) == 1:
            return self._cst_form_action()
        return True

    def action_done_new(self):
        self.action_done()
        return self.day_id._cst_new_operation_action(self.direction)

    def _cst_form_action(self):
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "current"}

    def _cst_post(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Only a draft operation can be posted."))
        if self.day_id.state != "open":
            raise UserError(_("The cash day %(day)s is not open.", day=self.day_id.display_name))
        self.day_id.kassa_id._cst_check_cashier()
        if self.operation_type in PARTNER_TYPES and not self.partner_id:
            raise UserError(_("Choose the partner."))
        if self.operation_type in CATEGORY_TYPES and not self.category_id:
            raise UserError(_("Choose the category."))
        if self.operation_type == "customer_in" and self.allocation_mode == "orders" \
                and not self.sale_order_ids:
            raise UserError(_("Choose the sales orders to settle, or pick another settlement option."))

        if self.operation_type in TRANSFER_TYPES:
            self._cst_post_transfer()
            return

        vals = {"state": "done", "posted_at": fields.Datetime.now()}
        if self.operation_type in PARTNER_TYPES:
            vals["payment_id"] = self._cst_create_payment().id
        elif self.operation_type == "employee_advance":
            payable, contact = self._cst_advance_accounts()
            vals["partner_id"] = contact.id
            vals["move_id"] = self._cst_create_move(payable, contact).id
        else:
            vals["move_id"] = self._cst_create_move().id
        self.with_context(cst_kassa_internal=True).write(vals)
        if self.operation_type == "employee_advance":
            self.with_context(cst_kassa_internal=True).payroll_line_id = self._cst_create_payroll_line()

        if self.operation_type == "customer_out":
            # money handed back to the client closes against his advance / credit note first
            self.env["cst.kassa.allocation"]._cst_allocate(
                self.partner_id.commercial_partner_id, self.company_id,
                targets=[(self.date, self.env["sale.order"], self.payment_id.move_id)])
        if self.operation_type == "customer_in" and self.allocation_mode != "none":
            orders = self.sale_order_ids if self.allocation_mode == "orders" else None
            self.env["cst.kassa.allocation"]._cst_allocate(
                self.partner_id.commercial_partner_id, self.company_id,
                orders=orders, operation=self, only_orders=bool(orders),
                currency=self.debt_currency_id or None)
        self.day_id._cst_refresh()
        if self.operation_type in ("customer_in", "customer_out"):
            self.env["cst.kassa.partner.balance"]._cst_refresh(self.partner_id.commercial_partner_id)

    # ------------------------------------------------------------------
    # Kassa to kassa
    # ------------------------------------------------------------------
    def _cst_post_transfer(self):
        """Money from one kassa to another: this operation and a paired one in the
        other kassa's open day, each with its own entry through the company's
        liquidity transfer account; a so'm↔dollar gap goes to exchange gain/loss."""
        self.ensure_one()
        other_kassa = self.transfer_kassa_id
        if not other_kassa:
            raise UserError(_("Choose the other kassa."))
        if other_kassa == self.kassa_id:
            raise UserError(_("Choose a different kassa: money cannot move to the same kassa."))
        if other_kassa.company_id != self.company_id:
            raise UserError(_("Both kassas must belong to the same company."))
        if self.transfer_amount <= 0:
            raise UserError(_("Enter the amount the other kassa receives."))
        company = self.company_id.sudo()
        transfer_account = company.transfer_account_id
        if not transfer_account:
            raise UserError(_("%(company)s has no internal transfer account (Accounting settings).",
                              company=company.name))
        other_day = self._cst_transfer_day(create=True)
        is_out = self.operation_type == "transfer_out"
        if not is_out:
            # money is taken out of the other kassa: its cashier rules apply
            other_kassa._cst_check_cashier()
        Op = self.env["cst.kassa.operation"].sudo().with_context(cst_kassa_transfer_pair=True)
        pair = Op.create({
            "day_id": other_day.id,
            "direction": "in" if is_out else "out",
            "type_in": "transfer_in",
            "type_out": "transfer_out",
            "amount": self.transfer_amount,
            "rate": other_day.usd_rate or self.rate,
            "transfer_kassa_id": self.kassa_id.id,
            "transfer_amount": self.amount,
            "transfer_op_id": self.id,
            "memo": self.memo,
            "created_by_id": self.env.uid,
        })
        out_op, in_op = (self, pair) if is_out else (pair.with_env(self.env), self)
        out_op, in_op = out_op.sudo(), in_op.sudo()
        out_value = out_op._cst_company_amount()
        in_value = in_op._cst_company_amount()
        ccy = company.currency_id
        label = _("%(src)s → %(dst)s", src=out_op.kassa_id.name, dst=in_op.kassa_id.name)
        if self.memo:
            label = f"{label} — {self.memo}"

        def line(account, currency, amount_currency, balance, name):
            return (0, 0, {"account_id": account.id, "currency_id": currency.id, "name": name,
                           "amount_currency": amount_currency,
                           "debit": max(balance, 0.0), "credit": max(-balance, 0.0)})

        Move = self.env["account.move"].sudo().with_company(company)
        out_move = Move.create({
            "move_type": "entry", "journal_id": out_op.journal_id.id, "date": out_op.date,
            "ref": f"{out_op.name} — {label}",
            "line_ids": [
                line(out_op.kassa_id._cst_money_account("out"), out_op.currency_id,
                     -out_op.amount, -out_value, label),
                line(transfer_account, ccy, out_value, out_value, label),
            ],
        })
        in_lines = [
            line(in_op.kassa_id._cst_money_account("in"), in_op.currency_id,
                 in_op.amount, in_value, label),
            line(transfer_account, ccy, -out_value, -out_value, label),
        ]
        diff = ccy.round(in_value - out_value)
        if not ccy.is_zero(diff):
            fx_account = company.income_currency_exchange_account_id if diff > 0 \
                else company.expense_currency_exchange_account_id
            in_lines.append(line(fx_account, ccy, -diff, -diff, _("Exchange difference: %s", label)))
        in_move = Move.create({
            "move_type": "entry", "journal_id": in_op.journal_id.id, "date": in_op.date,
            "ref": f"{in_op.name} — {label}",
            "line_ids": in_lines,
        })
        (out_move | in_move).with_context(cst_kassa_skip_guard=True).action_post()
        transfer_lines = (out_move | in_move).line_ids.filtered(lambda l: l.account_id == transfer_account)
        if transfer_account.reconcile:
            transfer_lines.reconcile()
        now = fields.Datetime.now()
        internal = dict(cst_kassa_internal=True)
        out_op.with_context(**internal).write({"state": "done", "posted_at": now, "move_id": out_move.id})
        in_op.with_context(**internal).write({"state": "done", "posted_at": now, "move_id": in_move.id})
        self.with_context(**internal).transfer_op_id = pair.id
        (self.day_id | other_day)._cst_refresh()

    def _cst_label(self):
        label = self.name
        if self.memo:
            label = f"{label} — {self.memo}"
        return label

    def _cst_create_payment(self):
        is_in = self.direction == "in"
        customer = self.operation_type in ("customer_in", "customer_out")
        vals = {
            "payment_type": "inbound" if is_in else "outbound",
            "partner_type": "customer" if customer else "supplier",
            "partner_id": self.partner_id.commercial_partner_id.id,
            "amount": self.amount,
            "currency_id": self.currency_id.id,
            "journal_id": self.journal_id.id,
            "date": self.date,
            "memo": self._cst_label(),
        }
        if self.is_foreign and self.rate > 0:
            # book the so'm at the kassa's dollar rate, not at the official one
            vals["force_balance"] = self._cst_company_amount()
        payment = self.env["account.payment"].sudo().with_company(self.company_id).create(vals)
        payment.with_context(cst_kassa_skip_guard=True).action_post()
        payment.filtered(lambda p: p.state == "in_process").action_validate()
        return payment

    def _cst_advance_accounts(self):
        """Salary payable account and the employee's contact, or a clear error."""
        employee = self.employee_id.sudo()
        if not employee:
            raise UserError(_("Choose the employee."))
        payable = self.company_id.sudo().cst_salary_payable_account_id
        if not payable:
            raise UserError(_(
                "%(company)s has no salary payable account. Set it in Settings ▸ Payroll "
                "before giving advances from the kassa.", company=self.company_id.name))
        if not employee.work_contact_id:
            raise UserError(_("%(employee)s has no work contact. Set it on the employee form.",
                              employee=employee.name))
        return payable, employee.work_contact_id

    def _cst_create_payroll_line(self):
        """«Накд аванс» deduction on the employee's salary account.

        The money has already been booked (salary payable / cash) by this kassa
        entry, so the line is posted and marked as booked elsewhere: the payroll
        period shows it and counts it, but never posts it a second time.
        """
        self.ensure_one()
        component = self.env.ref("cst_kerama_payroll.component_avans_naqd")
        period = self.env["cst.payroll.period"].sudo().search([
            ("company_id", "=", self.company_id.id),
            ("date_from", "<=", self.date),
            ("date_to", ">=", self.date),
            ("state", "!=", "closed"),
        ], order="date_from desc", limit=1)
        return self.env["cst.payroll.line"].sudo().create({
            "employee_id": self.employee_id.id,
            "component_id": component.id,
            "company_id": self.company_id.id,
            "date": self.date,
            "period_id": period.id or False,
            "amount": self.amount_company,
            "name": _("Kassa advance %(name)s", name=self.name),
            "note": self.memo or False,
            "is_manual": True,
            "is_external": True,
            "state": "posted",
            "move_id": self.move_id.id,
            "source_model": self._name,
            "source_id": self.id,
        })

    def _cst_create_move(self, counter_account=None, partner=None):
        company = self.company_id
        amount_company = self._cst_company_amount()
        is_in = self.direction == "in"
        partner = partner or self.partner_id
        common = {"currency_id": self.currency_id.id, "name": self._cst_label(),
                  "partner_id": partner.id or False}
        cash = dict(common, account_id=self.kassa_id._cst_money_account(self.direction).id,
                    amount_currency=self.amount if is_in else -self.amount,
                    debit=amount_company if is_in else 0.0,
                    credit=0.0 if is_in else amount_company)
        counter = dict(common, account_id=(counter_account or self.category_id.account_id).id,
                       amount_currency=-self.amount if is_in else self.amount,
                       debit=0.0 if is_in else amount_company,
                       credit=amount_company if is_in else 0.0)
        move = self.env["account.move"].sudo().with_company(company).create({
            "move_type": "entry",
            "journal_id": self.journal_id.id,
            "date": self.date,
            "ref": self._cst_label(),
            "line_ids": [(0, 0, cash), (0, 0, counter)],
        })
        move.with_context(cst_kassa_skip_guard=True).action_post()
        return move

    # ------------------------------------------------------------------
    def action_cancel(self):
        pairs = self.filtered(lambda o: o.operation_type in TRANSFER_TYPES).transfer_op_id.sudo()
        for op in pairs:
            if op.state == "done" and op.day_id.state == "confirmed":
                raise UserError(_("The paired operation %(name)s is on a confirmed cash day; "
                                  "the transfer cannot be cancelled.", name=op.name))
        self._cst_cancel_one_side()
        pairs.filtered(lambda o: o.state != "cancel")._cst_cancel_one_side()
        return True

    def _cst_cancel_one_side(self):
        for op in self:
            if op.state == "cancel":
                continue
            if op.state == "done":
                if op.day_id.state == "confirmed":
                    raise UserError(_("The cash day is confirmed; its operations cannot be cancelled."))
                if op.day_id.state == "closed" and not op.day_id._cst_is_manager():
                    raise UserError(_("The cash day is closed; only a kassa manager can cancel."))
                op.allocation_ids.filtered(lambda a: a.state == "done").action_undo()
                if op.payroll_line_id:
                    period = op.payroll_line_id.sudo().period_id
                    if period.state in ("posted", "closed"):
                        raise UserError(_(
                            "This advance is in the payroll period %(period)s, which is already "
                            "posted. Reset that period to draft first.", period=period.name))
                    op.payroll_line_id.sudo().with_context(cst_payroll_external_ok=True).unlink()
                if op.payment_id:
                    pay = op.payment_id.sudo().with_context(cst_kassa_skip_guard=True)
                    pay.move_id.line_ids.remove_move_reconcile()
                    pay.action_draft()
                    pay.action_cancel()
                if op.move_id:
                    move = op.move_id.sudo().with_context(cst_kassa_skip_guard=True)
                    move.line_ids.remove_move_reconcile()
                    move.button_draft()
                    move.button_cancel()
            op.with_context(cst_kassa_internal=True).write({"state": "cancel"})
            op.day_id._cst_refresh()
            if op.partner_id:
                self.env["cst.kassa.partner.balance"]._cst_refresh(op.partner_id.commercial_partner_id)
        return True

    def action_reconcile(self):
        self.ensure_one()
        return self.env["cst.kassa.reconcile.wizard"]._cst_open(
            self.partner_id.commercial_partner_id, self.company_id)

    def action_print(self):
        return self.env.ref("cst_kerama_kassa.action_report_kassa_order").report_action(self)

    def action_print_receipt(self):
        """80 mm check in a new tab; the page opens the print dialog itself."""
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": f"/kerama/kassa/receipt/{self.id}", "target": "new"}

    def _cst_amount_words(self, lang=None):
        self.ensure_one()
        lang = lang or self.env.lang or "en_US"
        if lang.startswith("uz"):
            return uz_amount_words(self.amount, self.currency_id)
        try:
            return self.currency_id.with_context(lang=lang).amount_to_text(self.amount)
        except Exception:  # num2words missing a language
            return ""
