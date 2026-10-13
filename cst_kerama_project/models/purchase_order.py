from odoo import api, fields, models


def _distribution_has_account(distribution, account_id):
    """True if ``account_id`` already appears in an analytic distribution dict."""
    for key in (distribution or {}):
        for part in str(key).split(","):
            if part.isdigit() and int(part) == account_id:
                return True
    return False


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    project_id = fields.Many2one(
        "project.project", string="Project", index="btree_not_null", copy=False,
        help="Project this purchase is made for. Its analytic account is applied "
             "to the order lines so the cost appears on the project.",
    )

    def _cst_project_account_id(self):
        """Return the project's analytic account id, creating it if missing."""
        self.ensure_one()
        project = self.project_id
        if not project:
            return False
        if not project.account_id:
            project.sudo()._create_analytic_account()
        return project.account_id.id or False

    def _cst_apply_project_analytic(self):
        for order in self:
            account_id = order._cst_project_account_id()
            if not account_id:
                continue
            for line in order.order_line:
                current = dict(line.analytic_distribution or {})
                if not _distribution_has_account(current, account_id):
                    current[str(account_id)] = 100.0
                    line.analytic_distribution = current

    @api.onchange("project_id")
    def _onchange_cst_project_id(self):
        if self.project_id:
            self._cst_apply_project_analytic()

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders.filtered("project_id")._cst_apply_project_analytic()
        return orders

    def write(self, vals):
        res = super().write(vals)
        if "project_id" in vals or "order_line" in vals:
            self.filtered("project_id")._cst_apply_project_analytic()
        return res

    def button_confirm(self):
        res = super().button_confirm()
        self.filtered("project_id")._cst_apply_project_analytic()
        return res
