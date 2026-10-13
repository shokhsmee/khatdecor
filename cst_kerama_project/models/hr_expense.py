from odoo import api, fields, models

from .purchase_order import _distribution_has_account


class HrExpense(models.Model):
    _inherit = "hr.expense"

    project_id = fields.Many2one(
        "project.project", string="Project", index="btree_not_null",
        help="Project this expense (xarajat) belongs to. Its analytic account is "
             "applied so the cost appears on the project.",
    )

    def _cst_project_account_id(self):
        self.ensure_one()
        project = self.project_id
        if not project:
            return False
        if not project.account_id:
            project.sudo()._create_analytic_account()
        return project.account_id.id or False

    def _cst_apply_project_analytic(self):
        for expense in self:
            account_id = expense._cst_project_account_id()
            if not account_id:
                continue
            current = dict(expense.analytic_distribution or {})
            if not _distribution_has_account(current, account_id):
                current[str(account_id)] = 100.0
                expense.analytic_distribution = current

    @api.onchange("project_id")
    def _onchange_cst_project_id(self):
        if self.project_id:
            self._cst_apply_project_analytic()

    @api.model_create_multi
    def create(self, vals_list):
        expenses = super().create(vals_list)
        expenses.filtered("project_id")._cst_apply_project_analytic()
        return expenses

    def write(self, vals):
        res = super().write(vals)
        if "project_id" in vals:
            self.filtered("project_id")._cst_apply_project_analytic()
        return res
