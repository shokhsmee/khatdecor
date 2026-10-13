from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# How a component's amount arrives on a payroll line.  Only "manual" and
# "monthly_wage" and the three tax rules are wired up so far; the KPI sources
# are declared here so later phases only add a handler, never a new selection.
COMPUTATION = [
    ("manual", "Entered by hand"),
    ("monthly_wage", "Monthly wage"),
    ("kpi_sales", "KPI — sales"),
    ("kpi_production", "KPI — manufacturing"),
    ("kpi_unloading", "KPI — unloading"),
    ("tax_income", "Tax — income tax"),
    ("tax_pension", "Tax — pension (INPS)"),
    ("tax_social", "Tax — social (employer)"),
]


class CstPayrollComponent(models.Model):
    """One column of the salary report: an accrual, a deduction, or an
    employer-only cost that never touches the employee's balance."""

    _name = "cst.payroll.component"
    _description = "Payroll Component"
    _order = "kind, sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True,
        help="Short identifier used by the report and by the KPI engine.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    kind = fields.Selection(
        [
            ("accrual", "Accrual"),
            ("deduction", "Deduction"),
            ("employer", "Employer cost"),
        ],
        required=True, default="accrual",
        help="Accruals increase what the company owes the employee, deductions "
             "reduce it.  An employer cost (social tax) reaches the ledger but "
             "never the employee's balance.")
    computation = fields.Selection(
        COMPUTATION, required=True, default="manual",
        help="Where the amount comes from when a period is computed.")

    is_official = fields.Boolean(
        string="Official",
        help="Part of the declared payroll.  Unticked components form the cash "
             "stream and are posted to a separate expense account.")
    is_taxable = fields.Boolean(
        string="Taxable",
        help="Enters the base for income tax, pension and social tax.")

    # Optional overrides.  Left empty, a line resolves its accounts from the
    # company's payroll settings, so only the components that genuinely differ
    # (a cash advance leaves the till, a card advance leaves the bank) need one.
    account_debit_id = fields.Many2one(
        "account.account", string="Debit Account",
        company_dependent=True, ondelete="restrict")
    account_credit_id = fields.Many2one(
        "account.account", string="Credit Account",
        company_dependent=True, ondelete="restrict")

    note = fields.Text(translate=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "A payroll component code must be unique.",
    )

    @api.constrains("is_taxable", "is_official")
    def _check_taxable_is_official(self):
        for component in self:
            if component.is_taxable and not component.is_official:
                raise ValidationError(_(
                    "%s is marked taxable but not official.  Only the official "
                    "stream is taxed — untick one of the two.", component.name))

    @api.depends("code", "name")
    def _compute_display_name(self):
        for component in self:
            component.display_name = f"[{component.code}] {component.name}"

