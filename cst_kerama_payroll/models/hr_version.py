from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrVersion(models.Model):
    """Odoo 19 keeps employment terms on dated versions instead of contracts,
    so the pay scheme and the official/cash split get change history for free."""

    _inherit = "hr.version"

    cst_salary_scheme = fields.Selection(
        [
            ("fixed", "Salary only"),
            ("kpi", "KPI only"),
            ("mixed", "Salary + KPI"),
        ],
        string="Pay Scheme", default="fixed", required=True, tracking=True,
        groups="hr.group_hr_manager",
        help="Salary only — a fixed monthly wage.  KPI only — paid per action "
             "(piece rate, sales, unloading).  Salary + KPI — both.")
    cst_official_wage = fields.Monetary(
        string="Official Wage", tracking=True, groups="hr.group_hr_manager",
        help="The declared part of the monthly wage.  Income tax, pension and "
             "social tax are computed on this amount; the remainder is booked "
             "to the cash expense account and is not taxed.")

    @api.constrains("wage", "cst_official_wage")
    def _check_official_wage(self):
        for version in self:
            if version.cst_official_wage and version.cst_official_wage > version.wage:
                raise ValidationError(_(
                    "The official wage cannot be more than the total wage for %s.",
                    version.employee_id.display_name or version.display_name))
