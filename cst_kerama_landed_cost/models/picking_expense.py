from odoo import _, api, fields, models
from odoo.exceptions import UserError

# The split methods that make sense on a receipt, in the order warehouse staff
# reach for them.  The technical keys are the ones `stock.landed.cost` knows.
SPLIT_METHOD = [
    ("by_current_cost_price", "By Value"),
    ("by_quantity", "By Quantity"),
    ("equal", "Equally"),
    ("by_weight", "By Weight"),
    ("by_volume", "By Volume"),
]


class CstPickingExpense(models.Model):
    _name = "cst.picking.expense"
    _description = "Receipt Expense"
    _order = "picking_id, date, id"

    picking_id = fields.Many2one(
        "stock.picking", string="Receipt",
        required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(
        "res.company", related="picking_id.company_id",
        store=True, precompute=True, index=True)
    # Not a plain related field: a line being typed into the receipt has no
    # picking yet, and a Monetary column with no currency renders blank.
    company_currency_id = fields.Many2one(
        "res.currency", string="Company Currency",
        compute="_compute_company_currency_id", store=True, precompute=True)

    date = fields.Date(
        string="Date", required=True, default=fields.Date.context_today)
    partner_id = fields.Many2one(
        "res.partner", string="Service Provider", required=True,
        index="btree_not_null",
        help="Who is owed for this expense.  A vendor bill is raised in this "
             "partner's name when the expense is added to the cost.")
    product_id = fields.Many2one(
        "product.product", string="Expense Type", required=True,
        domain=[("landed_cost_ok", "=", True)],
        help="A service product flagged as a landed cost.  It carries the "
             "expense account the bill posts to.")
    name = fields.Char(string="Description")

    currency_id = fields.Many2one(
        "res.currency", string="Currency", required=True,
        default=lambda self: self.env.company.currency_id)
    quantity = fields.Float(string="Quantity", default=1.0, required=True)
    price_unit = fields.Monetary(string="Unit Price", currency_field="currency_id")
    amount = fields.Monetary(
        string="Amount", currency_field="currency_id",
        compute="_compute_amount", store=True, readonly=False, precompute=True,
        help="Amount in the currency of the expense.  Overwrite it when the "
             "invoice is not exactly quantity times unit price.")
    currency_rate = fields.Float(
        string="Rate", digits=(16, 6),
        compute="_compute_currency_rate", store=True, readonly=False, precompute=True,
        help="How many units of the company currency one unit of the expense "
             "currency is worth.  Taken from the rate table on the expense "
             "date, but you can type the rate on the invoice instead.")
    amount_company = fields.Monetary(
        string="Amount in Company Currency", currency_field="company_currency_id",
        compute="_compute_amount_company", store=True, readonly=False, precompute=True)

    tax_ids = fields.Many2many(
        "account.tax", string="Taxes",
        domain=[("type_tax_use", "=", "purchase")],
        compute="_compute_tax_ids", store=True, readonly=False, precompute=True,
        help="Taxes added on top of the amount when the vendor bill is raised. "
             "The amount itself - without tax - is what lands on the goods.")

    split_method = fields.Selection(
        SPLIT_METHOD, string="Split Method",
        required=True, default="by_current_cost_price",
        compute="_compute_split_method", store=True, readonly=False, precompute=True,
        help="By Value: goods carry the expense in proportion to what they cost.\n"
             "By Quantity: every unit received carries the same share.\n"
             "Equally: every product line carries the same share.\n"
             "By Weight / By Volume: in proportion to the weight or volume received.")
    account_id = fields.Many2one(
        "account.account", string="Expense Account",
        compute="_compute_account_id", store=True, readonly=False, precompute=True,
        domain="[('deprecated', '=', False), ('company_ids', 'in', company_id)]",
        help="Debited by the vendor bill and credited again when the expense "
             "moves onto the goods, so it nets to zero.")
    create_bill = fields.Boolean(
        string="Bill It", default=True,
        help="Raise a vendor bill for this expense so it shows as a debt to the "
             "service provider.  Untick for expenses already paid and booked "
             "somewhere else.")

    landed_cost_id = fields.Many2one(
        "stock.landed.cost", string="Landed Cost",
        copy=False, readonly=True, ondelete="set null", index="btree_not_null")
    bill_id = fields.Many2one(
        "account.move", string="Vendor Bill",
        copy=False, readonly=True, ondelete="set null", index="btree_not_null")
    applied = fields.Boolean(
        string="Added to Cost", compute="_compute_applied", store=True)

    picking_state = fields.Selection(related="picking_id.state")

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends("company_id")
    def _compute_company_currency_id(self):
        for expense in self:
            expense.company_currency_id = (
                expense.company_id or self.env.company).currency_id

    @api.depends("quantity", "price_unit")
    def _compute_amount(self):
        for expense in self:
            expense.amount = expense.quantity * expense.price_unit

    @api.depends("currency_id", "date", "company_id")
    def _compute_currency_rate(self):
        for expense in self:
            company = expense.company_id or self.env.company
            company_currency = company.currency_id
            if not expense.currency_id or expense.currency_id == company_currency:
                expense.currency_rate = 1.0
                continue
            expense.currency_rate = expense.currency_id._convert(
                1.0, company_currency, company,
                expense.date or fields.Date.context_today(self), round=False)

    @api.depends("amount", "currency_rate", "company_currency_id")
    def _compute_amount_company(self):
        for expense in self:
            company_currency = expense.company_currency_id or self.env.company.currency_id
            expense.amount_company = company_currency.round(
                expense.amount * (expense.currency_rate or 1.0))

    @api.depends("product_id", "company_id")
    def _compute_tax_ids(self):
        for expense in self:
            company = expense.company_id or self.env.company
            taxes = expense.product_id.supplier_taxes_id.filtered(
                lambda tax: tax.company_id == company.root_id or tax.company_id == company)
            expense.tax_ids = [fields.Command.set(taxes.ids)]

    @api.depends("product_id")
    def _compute_split_method(self):
        for expense in self:
            expense.split_method = (
                expense.product_id.split_method_landed_cost
                or expense.split_method
                or "by_current_cost_price")

    @api.depends("product_id", "company_id")
    def _compute_account_id(self):
        for expense in self:
            if not expense.product_id:
                expense.account_id = False
                continue
            company = expense.company_id or self.env.company
            accounts = expense.product_id.product_tmpl_id.with_company(
                company).get_product_accounts()
            expense.account_id = accounts.get("expense")

    @api.depends("landed_cost_id", "landed_cost_id.state")
    def _compute_applied(self):
        for expense in self:
            expense.applied = expense.landed_cost_id.state == "done"

    @api.onchange("product_id")
    def _onchange_product_id_name(self):
        if self.product_id and not self.name:
            self.name = self.product_id.name

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------
    def write(self, vals):
        protected = set(vals) - {"landed_cost_id", "bill_id", "applied"}
        if protected and any(expense.applied for expense in self):
            raise UserError(_(
                "An expense that has already been added to the cost of the "
                "goods can no longer be changed.  Add a correcting expense "
                "line with a negative amount instead."))
        return super().write(vals)

    def unlink(self):
        if any(expense.applied for expense in self):
            raise UserError(_(
                "An expense that has already been added to the cost of the "
                "goods can no longer be deleted.  Add a correcting expense "
                "line with a negative amount instead."))
        return super().unlink()

    # ------------------------------------------------------------------
    # Helpers used when the expenses are pushed onto the goods
    # ------------------------------------------------------------------
    def _prepare_landed_cost_line(self):
        self.ensure_one()
        return {
            "product_id": self.product_id.id,
            "name": self.name or self.product_id.name,
            "account_id": self.account_id.id,
            "price_unit": self.amount_company,
            "split_method": self.split_method,
        }

    def _prepare_bill_line(self):
        self.ensure_one()
        return {
            "product_id": self.product_id.id,
            "name": self.name or self.product_id.name,
            "quantity": 1.0,
            "price_unit": self.amount,
            "account_id": self.account_id.id,
            "tax_ids": [fields.Command.set(self.tax_ids.ids)],
            "is_landed_costs_line": True,
        }
