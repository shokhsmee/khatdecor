from odoo import _, api, fields, models
from odoo.exceptions import UserError

VALUED_COST_METHODS = ("fifo", "average")


class StockPicking(models.Model):
    _inherit = "stock.picking"

    cst_expense_ids = fields.One2many(
        "cst.picking.expense", "picking_id", string="Expenses", copy=False)
    cst_expense_visible = fields.Boolean(
        string="Expenses Apply Here", compute="_compute_cst_expense_visible")
    cst_company_currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", string="Company Currency")

    cst_expense_total = fields.Monetary(
        string="Total Expenses", currency_field="cst_company_currency_id",
        compute="_compute_cst_expense_amounts")
    cst_expense_applied = fields.Monetary(
        string="Already in Cost", currency_field="cst_company_currency_id",
        compute="_compute_cst_expense_amounts")
    cst_expense_pending = fields.Monetary(
        string="Not Yet in Cost", currency_field="cst_company_currency_id",
        compute="_compute_cst_expense_amounts")
    cst_expense_ready = fields.Boolean(
        string="Expenses Ready to Add", compute="_compute_cst_expense_amounts")

    cst_valuation_ok = fields.Boolean(
        string="Cost Can Be Corrected", compute="_compute_cst_valuation_ok",
        help="Whether any of the goods on this receipt is valued at average "
             "cost or FIFO.  Goods at standard price keep the price on their "
             "form whatever they cost to bring in, so expenses cannot land "
             "on them.")

    cst_landed_cost_ids = fields.Many2many(
        "stock.landed.cost", string="Landed Costs",
        compute="_compute_cst_landed_cost_ids")
    cst_landed_cost_count = fields.Integer(
        string="Landed Cost Count", compute="_compute_cst_landed_cost_ids")
    cst_expense_bill_ids = fields.Many2many(
        "account.move", string="Expense Bills",
        compute="_compute_cst_expense_bill_ids")
    cst_expense_bill_count = fields.Integer(
        string="Expense Bill Count", compute="_compute_cst_expense_bill_ids")
    cst_preview_landed_cost_id = fields.Many2one(
        "stock.landed.cost", string="Draft Landed Cost",
        copy=False, readonly=True, ondelete="set null", index="btree_not_null")

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends("picking_type_code")
    def _compute_cst_expense_visible(self):
        for picking in self:
            picking.cst_expense_visible = picking.picking_type_code == "incoming"

    @api.depends("cst_expense_ids.amount_company", "cst_expense_ids.applied", "state")
    def _compute_cst_expense_amounts(self):
        for picking in self:
            applied = sum(
                expense.amount_company
                for expense in picking.cst_expense_ids if expense.applied)
            total = sum(picking.cst_expense_ids.mapped("amount_company"))
            picking.cst_expense_total = total
            picking.cst_expense_applied = applied
            picking.cst_expense_pending = total - applied
            picking.cst_expense_ready = bool(
                picking.state == "done"
                and any(not expense.applied for expense in picking.cst_expense_ids))

    @api.depends("move_ids.product_id")
    def _compute_cst_valuation_ok(self):
        for picking in self:
            picking.cst_valuation_ok = any(
                move.product_id.with_company(picking.company_id).cost_method
                in VALUED_COST_METHODS
                for move in picking.move_ids)

    @api.depends("cst_expense_ids.landed_cost_id")
    def _compute_cst_landed_cost_ids(self):
        for picking in self:
            costs = picking.cst_expense_ids.landed_cost_id
            picking.cst_landed_cost_ids = costs
            picking.cst_landed_cost_count = len(costs)

    @api.depends("cst_expense_ids.bill_id")
    def _compute_cst_expense_bill_ids(self):
        for picking in self:
            bills = picking.cst_expense_ids.bill_id
            picking.cst_expense_bill_ids = bills
            picking.cst_expense_bill_count = len(bills)

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_cst_preview_expenses(self):
        """Work out the split without touching anything, and show it."""
        self.ensure_one()
        expenses = self._cst_pending_expenses()
        self._cst_check_can_apply(expenses)
        if self.cst_preview_landed_cost_id.state == "draft":
            self.cst_preview_landed_cost_id.sudo().unlink()
        cost = self._cst_create_landed_cost(expenses)
        cost.compute_landed_cost()
        self.cst_preview_landed_cost_id = cost
        return self._cst_open_landed_cost(cost)

    def action_cst_apply_expenses(self):
        """Bill the providers, spread the expenses and correct the cost."""
        self.ensure_one()
        expenses = self._cst_pending_expenses()
        self._cst_check_can_apply(expenses)

        # A draft left over from a preview would otherwise linger for ever.
        if self.cst_preview_landed_cost_id.state == "draft":
            self.cst_preview_landed_cost_id.sudo().unlink()

        bills = self._cst_create_bills(expenses)
        cost = self._cst_create_landed_cost(expenses, bills=bills)
        cost.compute_landed_cost()
        cost.button_validate()
        expenses.write({"landed_cost_id": cost.id})
        return self._cst_open_landed_cost(cost)

    def action_cst_view_landed_costs(self):
        self.ensure_one()
        return self.cst_landed_cost_ids._get_records_action(name=_("Landed Costs"))

    def action_cst_view_expense_bills(self):
        self.ensure_one()
        return self.cst_expense_bill_ids._get_records_action(name=_("Expense Bills"))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _cst_pending_expenses(self):
        self.ensure_one()
        return self.cst_expense_ids.filtered(lambda expense: not expense.applied)

    def _cst_check_can_apply(self, expenses):
        self.ensure_one()
        if self.picking_type_code != "incoming":
            raise UserError(_("Expenses can only be added to the cost of a receipt."))
        if self.state != "done":
            raise UserError(_(
                "Validate the receipt first - there is nothing in stock to "
                "carry the expenses yet."))
        if not expenses:
            raise UserError(_("Every expense on this receipt is already in the cost."))
        currency = self.company_id.currency_id
        if currency.is_zero(sum(expenses.mapped("amount_company"))):
            raise UserError(_("The expenses add up to nothing, so there is nothing to spread."))
        missing_account = expenses.filtered(lambda expense: not expense.account_id)
        if missing_account:
            raise UserError(_(
                "These expenses have no expense account, so they cannot be "
                "booked:\n%s",
                "\n".join("- %s" % expense.product_id.display_name
                          for expense in missing_account)))
        if not self._cst_valued_moves():
            raise UserError(_(
                "None of the goods on this receipt is valued at average cost "
                "or FIFO, so there is no cost to correct.  Set the costing "
                "method of their product category to Average Cost (AVCO) or "
                "First In First Out (FIFO) first."))

    def _cst_valued_moves(self):
        self.ensure_one()
        return self.move_ids.filtered(
            lambda move: (
                move.state != "cancel"
                and move.quantity
                and move.product_id.with_company(self.company_id).cost_method
                in VALUED_COST_METHODS))

    def _cst_create_bills(self, expenses):
        """One posted vendor bill per provider, currency and rate."""
        self.ensure_one()
        to_bill = expenses.filtered("create_bill")
        if not to_bill:
            return self.env["account.move"]

        company = self.company_id
        journal = self.env["account.journal"].search([
            ("type", "=", "purchase"),
            ("company_id", "=", company.id),
        ], limit=1)
        if not journal:
            raise UserError(_(
                "%s has no purchase journal, so the expenses cannot be billed.",
                company.display_name))

        groups = {}
        for expense in to_bill:
            key = (
                expense.partner_id.id,
                expense.currency_id.id,
                float_repr_rate(expense.currency_rate),
            )
            groups.setdefault(key, self.env["cst.picking.expense"])
            groups[key] |= expense

        bills = self.env["account.move"]
        for group in groups.values():
            first = group[0]
            date = max(group.mapped("date"))
            vals = {
                "move_type": "in_invoice",
                "company_id": company.id,
                "journal_id": journal.id,
                "partner_id": first.partner_id.id,
                "currency_id": first.currency_id.id,
                "invoice_date": date,
                "date": date,
                "ref": _("Expenses of %s", self.name),
                "invoice_origin": self.name,
                "invoice_line_ids": [
                    fields.Command.create(expense._prepare_bill_line())
                    for expense in group
                ],
            }
            # Honour the rate the user typed rather than today's table, so the
            # expense account nets to exactly zero against the landed cost.
            if first.currency_id != company.currency_id and first.currency_rate:
                vals["invoice_currency_rate"] = 1.0 / first.currency_rate
            bill = self.env["account.move"].with_company(company).create(vals)
            bill.action_post()
            group.write({"bill_id": bill.id})
            bills |= bill
        return bills

    def _cst_create_landed_cost(self, expenses, bills=None):
        self.ensure_one()
        bills = bills or self.env["account.move"]
        return self.env["stock.landed.cost"].with_company(self.company_id).create({
            "date": max(expenses.mapped("date")),
            "target_model": "picking",
            "picking_ids": [fields.Command.set(self.ids)],
            "vendor_bill_id": bills.id if len(bills) == 1 else False,
            "description": _("Expenses of %s", self.name),
            "cost_lines": [
                fields.Command.create(expense._prepare_landed_cost_line())
                for expense in expenses
            ],
        })

    def _cst_open_landed_cost(self, cost):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock_landed_costs.action_stock_landed_cost")
        return dict(action, view_mode="form", res_id=cost.id, views=[(False, "form")])


def float_repr_rate(rate):
    """Group rates that only differ below the sixth decimal."""
    return round(rate or 1.0, 6)
