from odoo import _, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _cst_ensure_project_analytic(self, project):
        """Make sure the project carries an analytic account.

        Reuses the native ``project._create_analytic_account`` which resolves the
        default analytic plan via ``account.analytic.plan._get_all_plans()``.
        Analytic accounts are greenfield on this DB, so this bootstraps them.
        """
        if project and not project.account_id:
            project._create_analytic_account()
        return project

    def action_cst_create_project(self):
        """Create a project for this sale order (or open the linked one)."""
        self.ensure_one()
        if not self.project_id:
            project = self.env["project.project"].create({
                "name": self.name or (self.partner_id.name or _("Project")),
                "partner_id": self.partner_id.id,
                "company_id": self.company_id.id,
                "allow_billable": True,
            })
            self._cst_ensure_project_analytic(project)
            self.project_id = project.id
        else:
            self._cst_ensure_project_analytic(self.project_id)
        return self.action_cst_open_project()

    def action_cst_open_project(self):
        self.ensure_one()
        if not self.project_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": self.project_id.display_name,
            "res_model": "project.project",
            "res_id": self.project_id.id,
            "view_mode": "form",
            "target": "current",
        }
