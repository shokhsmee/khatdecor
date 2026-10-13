from odoo import models


class CstPayrollPeriod(models.Model):
    """Work paid through a shift fund is not paid again as piece rate."""

    _inherit = "cst.payroll.period"

    def _collect_kpi_production_lines(self):
        vals = super()._collect_kpi_production_lines()
        if not vals:
            return vals
        shift_workorder_ids = set(self.env["mrp.workorder"].search(
            [("cst_shift_id", "!=", False), ("company_id", "=", self.company_id.id)]).ids)
        if not shift_workorder_ids:
            return vals
        return [v for v in vals
                if not (v.get("source_model") == "mrp.workorder" and v.get("source_id") in shift_workorder_ids)]
