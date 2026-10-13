from odoo import api, fields, models


class KassaCategory(models.Model):
    _name = "cst.kassa.category"
    _description = "Cash In / Out Category"
    _order = "direction, sequence, name"
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    direction = fields.Selection([("in", "Cash in"), ("out", "Cash out")], required=True, default="out")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    account_id = fields.Many2one(
        "account.account", string="Account", required=True, check_company=True,
        default=lambda self: self._default_account(),
        help="Expense (cash out) or income (cash in) account the money is booked to.",
    )

    @api.model
    def _default_account(self):
        """Expense account for a cash-out category, income account for cash in."""
        company = self.env["res.company"].browse(self.env.context.get("default_company_id")) \
            or self.env.company
        Account = self.env["account.account"]
        domain = Account._check_company_domain(company)
        if self.env.context.get("default_direction") == "in":
            return Account.search(domain + [("account_type", "=", "income_other")], order="code", limit=1) \
                or Account.search(domain + [("account_type", "=", "income")], order="code", limit=1)
        return Account.search(domain + [("account_type", "=", "expense")], order="code", limit=1)
