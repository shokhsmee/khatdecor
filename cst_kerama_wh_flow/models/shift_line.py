from odoo import api, models


class CstProductionShiftLine(models.Model):
    _inherit = "cst.production.shift.line"

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        # the department that takes the order's last operation is where it is
        # made: an order raised elsewhere (Preslash 1 in the bill, run on an
        # automatic line of Янги пресс) follows it while nothing has moved yet
        for line in lines.filtered(lambda l: l.is_final_operation and l.production_id):
            department = line.department_id
            production = line.production_id
            if department.warehouse_id and production.cst_flow_department_id != department:
                production._cst_align_warehouse(department)
        return lines

    def _post_output(self):
        result = super()._post_output()
        if self.is_final_operation:
            self.production_id._cst_forward_output()
        return result
