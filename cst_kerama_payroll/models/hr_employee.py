from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    cst_personnel_no = fields.Char(
        string="Personnel No.", copy=False, index="btree_not_null", tracking=True,
        groups="hr.group_hr_user",
        help="Табель рақами.  The key for payroll imports and reports — names "
             "repeat, this must not.\n\n"
             "HR-only on purpose: a stored employee field without `groups=` is "
             "fetched for every user who so much as reads an employee name, and "
             "`hr.employee.public` has no column for it — which made every "
             "employee many2many (Shop Floor operators, chatter avatars) raise "
             "an access error for non-HR users.")
    cst_pinfl = fields.Char(
        string="JSHSHIR (PINFL)", size=14, copy=False, index="btree_not_null",
        tracking=True, groups="hr.group_hr_user",
        help="Жисмоний шахснинг шахсий идентификация раками — 14 та ракам.  "
             "Банк карталарига утказилган пулларни Excel'дан юклашда ходим "
             "айнан шу буйича топилади.")
    cst_payroll_balance = fields.Monetary(
        string="Salary Balance", compute="_compute_cst_payroll_balance",
        currency_field="currency_id", groups="hr.group_hr_manager",
        help="What the company still owes this employee.  Negative means the "
             "employee has drawn more than has been accrued.")
    cst_payroll_line_count = fields.Integer(
        compute="_compute_cst_payroll_balance", groups="hr.group_hr_manager")

    # A version field carrying a `groups=` must be re-declared here with
    # `inherited=True`, or the _inherits delegation silently drops it.
    cst_salary_scheme = fields.Selection(
        readonly=False, related="version_id.cst_salary_scheme",
        inherited=True, groups="hr.group_hr_manager")
    cst_official_wage = fields.Monetary(
        readonly=False, related="version_id.cst_official_wage",
        inherited=True, groups="hr.group_hr_manager")

    _personnel_no_uniq = models.Constraint(
        "unique(cst_personnel_no, company_id)",
        "That personnel number is already used by another employee.",
    )
    _pinfl_uniq = models.Constraint(
        "unique(cst_pinfl)",
        "That PINFL already belongs to another employee.",
    )

    @api.constrains("cst_pinfl")
    def _check_cst_pinfl(self):
        for employee in self:
            pinfl = employee.cst_pinfl
            if pinfl and (len(pinfl) != 14 or not pinfl.isdigit()):
                raise ValidationError(_(
                    "ЖШШИР 14 та ракамдан иборат булиши керак — «%s» тугри келмайди.",
                    pinfl))

    def _compute_cst_payroll_balance(self):
        groups = self.env["cst.payroll.line"]._read_group(
            [
                ("employee_id", "in", self.ids),
                ("state", "in", ("confirmed", "posted")),
            ],
            groupby=["employee_id"],
            aggregates=["signed_amount:sum", "__count"],
        )
        totals = {
            employee.id: (balance, count) for employee, balance, count in groups
        }
        for employee in self:
            balance, count = totals.get(employee.id, (0.0, 0))
            employee.cst_payroll_balance = balance
            employee.cst_payroll_line_count = count

    def action_open_payroll_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Salary Account — %s", self.display_name),
            "res_model": "cst.payroll.line",
            "view_mode": "list,form",
            "domain": [("employee_id", "=", self.id)],
            "context": {"default_employee_id": self.id},
        }
