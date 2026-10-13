from odoo import _, api, fields, models


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    cst_operator_ids = fields.Many2many(
        "hr.employee", "cst_workorder_operator_rel", "workorder_id", "employee_id",
        string="Operatorlar", compute="_compute_cst_operator_ids", store=True,
        help="Bu ish buyurtmasi kimning ishi: biriktirilganlar, ishlayotganlar va "
             "smena qatoridagi xodimlar. Shop Floor'da operator faqat shu ro'yxatda "
             "bo'lgan buyurtmalarni ko'radi.")

    @api.depends("employee_assigned_ids", "employee_ids",
                 "cst_shift_line_ids.employee_ids", "cst_shift_line_ids.state",
                 "cst_shift_line_ids.shift_id.employee_ids")
    def _compute_cst_operator_ids(self):
        for workorder in self:
            employees = workorder.employee_assigned_ids | workorder.employee_ids
            for line in workorder.cst_shift_line_ids.filtered(lambda l: l.state != "carried"):
                employees |= line.employee_ids or line.shift_id.employee_ids
            workorder.cst_operator_ids = [(6, 0, employees.ids)]
