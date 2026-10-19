from odoo import models


class CstProductionFloor(models.AbstractModel):
    _inherit = "cst.production.floor"

    def _queue(self, department, shift):
        rows = super()._queue(department, shift)
        productions = self.env["mrp.production"].browse({row["mo_id"] for row in rows})
        info = {mo.id: mo for mo in productions}
        for row in rows:
            mo = info.get(row["mo_id"])
            row["urgent"] = bool(mo and mo.priority == "1")
            row["request"] = mo.cst_request_id.name if mo and mo.cst_request_id else ""
            row["partner"] = (mo.cst_request_id.partner_id.name or "") if mo and mo.cst_request_id else ""
        return rows
