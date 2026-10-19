from odoo import models


class CstProductionDepartment(models.Model):
    _inherit = "cst.production.department"

    def _pending_workorders(self):
        """Urgent («Tezkor») orders head the queue; the rest keep their order."""
        workorders = super()._pending_workorders()
        return workorders.sorted(lambda w: w.production_id.priority != "1")
