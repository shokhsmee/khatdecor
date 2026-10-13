from odoo import fields, models


class MrpWorkcenter(models.Model):
    _inherit = "mrp.workcenter"

    cst_department_id = fields.Many2one(
        "cst.production.department", string="Bo'lim", index=True,
        help="Bu liniya qaysi bo'limga tegishli. Bo'lim smenasi shu liniyaning ish buyurtmalarini oladi.")
