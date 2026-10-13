from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CstPayrollLine(models.Model):
    """One movement on an employee's salary account.

    Everything else in the module — the report, the KPI engine, the journal
    entry — is either a producer or a consumer of these lines.
    """

    _name = "cst.payroll.line"
    _description = "Payroll Line"
    _order = "date desc, employee_id, id desc"
    _check_company_auto = True

    name = fields.Char(string="Description")
    employee_id = fields.Many2one(
        "hr.employee", required=True, index=True, ondelete="restrict",
        check_company=True)
    partner_id = fields.Many2one(
        "res.partner", string="Contact",
        related="employee_id.work_contact_id", store=True,
        help="Carried onto the payable journal item so the partner ledger and "
             "this report show the same balance.")
    date = fields.Date(required=True, index=True, default=fields.Date.context_today)
    period_id = fields.Many2one(
        "cst.payroll.period", index=True, ondelete="restrict", check_company=True)

    component_id = fields.Many2one(
        "cst.payroll.component", required=True, index=True, ondelete="restrict")
    kind = fields.Selection(related="component_id.kind", store=True, index=True)
    is_official = fields.Boolean(
        compute="_compute_is_official", store=True, readonly=False,
        help="Declared payroll.  Defaults from the component but can be set per "
             "line, because the same column (Ойлик суммаси) usually carries an "
             "official part and a cash part for the same employee.")
    is_taxable = fields.Boolean(
        compute="_compute_is_taxable", store=True,
        help="Counts towards the income tax, pension and social tax base.")

    company_id = fields.Many2one(
        "res.company", required=True, index=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    amount = fields.Monetary(required=True, currency_field="currency_id")
    signed_amount = fields.Monetary(
        compute="_compute_signed_amount", store=True, currency_field="currency_id",
        help="Positive for an accrual, negative for a deduction.  Employer "
             "costs are zero here — they never move the employee's balance.")

    # Traceability back to whatever produced the line.
    source_model = fields.Char(index=True)
    source_id = fields.Integer(string="Source ID", index=True)
    source_ref = fields.Char(compute="_compute_source_ref", string="Source")
    product_id = fields.Many2one("product.product", ondelete="restrict")
    product_categ_id = fields.Many2one(
        "product.category", string="Product Category",
        related="product_id.categ_id", store=True, index="btree_not_null",
        help="Kept on the line so the sales-KPI report can group manager -> "
             "category -> product without joining through the product.")
    quantity = fields.Float(digits="Product Unit of Measure")
    rate = fields.Monetary(currency_field="currency_id", string="KPI Rate")

    # Report #22 reads по участку и смене, so both have to survive on the line
    # itself — the work order it came from may be edited or deleted later.
    cst_operation_name = fields.Char(
        string="Operation", index="btree_not_null",
        help="Printer / Kesish / Preslash.  Copied from the work order, so the "
             "piece-rate report can group by it.")
    cst_workcenter_id = fields.Many2one(
        "mrp.workcenter", string="Work Center", ondelete="restrict",
        index="btree_not_null")
    cst_shift = fields.Selection(
        [("1", "1-smena"), ("2", "2-smena")], string="Smena",
        index="btree_not_null")

    move_id = fields.Many2one(
        "account.move", string="Journal Entry", readonly=True, copy=False,
        index="btree_not_null", ondelete="restrict")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("posted", "Posted"),
            ("cancel", "Cancelled"),
        ],
        default="draft", required=True, index=True, readonly=True, copy=False)
    is_manual = fields.Boolean(
        string="Qo'lda kiritilgan", default=False, copy=False,
        help="Одам узи ёзган катор.  Давр кайта хисобланганда учирилмайди — "
             "акс холда кулда ёзилган «Юк тушириш» ёки «Ишбай» бонуси "
             "жимгина йуколарди.")
    note = fields.Text()
    is_external = fields.Boolean(
        string="Booked elsewhere", readonly=True, copy=False, index=True,
        help="The journal entry of this line was made by another document (a "
             "kassa advance).  The period shows it and counts it in the balance, "
             "but never posts, resets or deletes it — only the source document can.")

    # Fields an externally booked line may not change without its source document.
    _EXTERNAL_LOCKED = {"employee_id", "date", "component_id", "company_id", "amount",
                        "state", "move_id", "is_official", "is_external"}

    _amount_not_zero = models.Constraint(
        "CHECK(amount != 0)",
        "A payroll line of zero has nothing to record.",
    )

    @api.depends("component_id")
    def _compute_is_official(self):
        for line in self:
            line.is_official = line.component_id.is_official

    @api.depends("component_id.is_taxable", "is_official")
    def _compute_is_taxable(self):
        for line in self:
            line.is_taxable = line.component_id.is_taxable and line.is_official

    @api.depends("amount", "component_id.kind")
    def _compute_signed_amount(self):
        for line in self:
            if line.kind == "accrual":
                line.signed_amount = line.amount
            elif line.kind == "deduction":
                line.signed_amount = -line.amount
            else:
                line.signed_amount = 0.0

    @api.depends("source_model", "source_id")
    def _compute_source_ref(self):
        for line in self:
            ref = False
            if line.source_model and line.source_id:
                record = self.env[line.source_model].browse(line.source_id).exists()
                ref = record.display_name if record else False
            line.source_ref = ref

    def action_open_source(self):
        self.ensure_one()
        if not (self.source_model and self.source_id):
            raise UserError(_("This line was entered by hand — it has no source document."))
        record = self.env[self.source_model].browse(self.source_id)
        # A source that is only part of a document (one unloader on a receipt)
        # sends the user to the document instead of to its own bare form.
        if hasattr(record, "_cst_source_redirect"):
            record = record._cst_source_redirect()
        return {
            "type": "ir.actions.act_window",
            "res_model": record._name,
            "res_id": record.id,
            "view_mode": "form",
        }

    def write(self, vals):
        if not self.env.context.get("cst_payroll_external_ok") \
                and self._EXTERNAL_LOCKED.intersection(vals) and any(self.mapped("is_external")):
            raise UserError(_(
                "This line comes from a kassa document.  Change or cancel the kassa "
                "operation instead — the payroll line follows it."))
        return super().write(vals)

    def unlink(self):
        external = self.filtered("is_external")
        if external and not self.env.context.get("cst_payroll_external_ok"):
            raise UserError(_(
                "This line comes from a kassa document.  Cancel the kassa operation "
                "instead — the payroll line is removed with it."))
        posted = (self - external).filtered(lambda line: line.state == "posted")
        if posted:
            raise UserError(_(
                "%s posted line(s) cannot be deleted.  Reset the period to draft "
                "first — that cancels the journal entry.", len(posted)))
        return super().unlink()

    # ------------------------------------------------------------------
    # Accounting
    # ------------------------------------------------------------------
    def _account_for(self, side):
        """Resolve one side of this line's posting.

        The component may pin an account; otherwise it comes from the company's
        payroll settings, which is what makes fifteen components need only four
        pieces of configuration.
        """
        self.ensure_one()
        component = self.component_id.with_company(self.company_id)
        account = component.account_debit_id if side == "debit" else component.account_credit_id
        if not account:
            account = self._fallback_account(side)
        if not account:
            raise UserError(_(
                "Nothing tells me which account to %(side)s for “%(component)s” "
                "in %(company)s.\n\n"
                "Set it on the component (Payroll ▸ Configuration ▸ Components) "
                "or fill in the company's payroll accounts under "
                "Settings ▸ Payroll.",
                side=side, component=component.name,
                company=self.company_id.display_name))
        return account

    def _fallback_account(self, side):
        self.ensure_one()
        company = self.company_id
        expense = (
            company.cst_salary_expense_account_id if self.is_official
            else company.cst_salary_expense_cash_account_id
            or company.cst_salary_expense_account_id
        )
        if self.kind == "accrual":
            # Earning it costs the company and grows what it owes the employee.
            return expense if side == "debit" else company.cst_salary_payable_account_id
        if self.kind == "deduction":
            # Anything withheld clears part of that debt.
            if side == "debit":
                return company.cst_salary_payable_account_id
            if self.component_id.computation in ("tax_income", "tax_pension"):
                return company.cst_employee_tax_account_id
            # Advances and fines differ per component — no safe default.
            return False
        # Employer cost: an expense owed to the state, never to the employee.
        return expense if side == "debit" else company.cst_employer_tax_account_id

    def _move_line_vals(self, date=None):
        """Journal items for these lines, aggregated per account + partner +
        component so the entry stays readable but the partner ledger stays exact.

        An account pinned to another currency (the so'm till since the switch to
        dollars) also gets that currency's amount, or Odoo refuses the entry."""
        buckets = {}
        for line in self:
            debit_account = line._account_for("debit")
            credit_account = line._account_for("credit")
            for account, sign in ((debit_account, 1), (credit_account, -1)):
                # A payable/receivable account only reconciles if it carries the
                # partner; an expense account is cleaner without one.
                partner = False
                if account.account_type in ("liability_payable", "asset_receivable") or account.reconcile:
                    partner = line.partner_id
                    if not partner:
                        raise UserError(_(
                            "%s has no work contact, so the payable line cannot "
                            "name a partner.  Set one on the employee form.",
                            line.employee_id.display_name))
                key = (account.id, partner.id if partner else False, line.component_id.id)
                bucket = buckets.setdefault(key, {
                    "account": account,
                    "partner": partner,
                    "component": line.component_id,
                    "balance": 0.0,
                })
                bucket["balance"] += sign * line.amount

        vals = []
        for bucket in buckets.values():
            if self.env.company.currency_id.is_zero(bucket["balance"]):
                continue
            label = bucket["component"].name
            if bucket["partner"]:
                label = f"{label} — {bucket['partner'].display_name}"
            line_vals = {
                "account_id": bucket["account"].id,
                "partner_id": bucket["partner"].id if bucket["partner"] else False,
                "name": label,
                "balance": bucket["balance"],
            }
            company = self.company_id[:1] or self.env.company
            account_currency = bucket["account"].currency_id
            if account_currency and account_currency != company.currency_id:
                line_vals["currency_id"] = account_currency.id
                line_vals["amount_currency"] = company.currency_id._convert(
                    bucket["balance"], account_currency, company, date or fields.Date.context_today(self))
            vals.append((0, 0, line_vals))
        return vals

    # ------------------------------------------------------------------
    # Balances
    # ------------------------------------------------------------------
    @api.model
    def _balance_domain(self, company, date_to=None, date_from=None):
        domain = [
            ("company_id", "=", company.id),
            ("state", "in", ("confirmed", "posted")),
        ]
        if date_from:
            domain.append(("date", ">=", date_from))
        if date_to:
            domain.append(("date", "<=", date_to))
        return domain

    @api.model
    def _balances_by_employee(self, company, date_to=None, date_from=None):
        """{employee_id: signed balance} over the given window."""
        groups = self._read_group(
            self._balance_domain(company, date_to=date_to, date_from=date_from),
            groupby=["employee_id"],
            aggregates=["signed_amount:sum"],
        )
        return {employee.id: total for employee, total in groups}
