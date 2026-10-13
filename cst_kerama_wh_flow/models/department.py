from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CstProductionDepartment(models.Model):
    _inherit = "cst.production.department"

    warehouse_id = fields.Many2one(
        "stock.warehouse", string="Ishlaydigan ombor", domain="[('company_id', '=', company_id)]",
        help="Bo'lim buyurtmalari shu omborda ochiladi: xomashyo shu ombordan olinadi, "
             "tayyor mahsulot shu omborga tushadi.")
    supply_warehouse_ids = fields.Many2many(
        "stock.warehouse", "cst_department_supply_wh_rel", "department_id", "warehouse_id",
        string="Xomashyo omborlari", domain="[('company_id', '=', company_id)]",
        help="Yetmagan xomashyo shu omborlardan so'raladi (qaysi birida bo'sh qoldiq bo'lsa).")
    output_warehouse_id = fields.Many2one(
        "stock.warehouse", string="Tayyor mahsulot ketadigan ombor",
        domain="[('company_id', '=', company_id)]",
        help="Natija kiritilganda 1-sort va 2-sort mahsulot shu omborga ko'chiriladi.")
    cst_auto_supply = fields.Boolean(
        string="Xomashyoni avtomatik so'rash", default=False,
        help="Buyurtma tasdiqlanganda yetmagan xomashyo uchun ichki ko'chirish yaratiladi.")
    cst_auto_forward = fields.Boolean(
        string="Tayyor mahsulotni avtomatik yuborish", default=True,
        help="Natija omborga tushishi bilan keyingi omborga ichki ko'chirish yaratiladi.")

    @api.constrains("warehouse_id", "output_warehouse_id", "supply_warehouse_ids")
    def _check_cst_flow(self):
        for department in self:
            if department.warehouse_id and department.output_warehouse_id == department.warehouse_id:
                raise ValidationError(_("«%s»: tayyor mahsulot ketadigan ombor ishlaydigan ombordan farq qilishi kerak.",
                                        department.name))
            if department.warehouse_id and department.warehouse_id in department.supply_warehouse_ids:
                raise ValidationError(_("«%s»: xomashyo omborlari ichida bo'limning o'z ombori bo'lmasin.",
                                        department.name))

    def _cst_warehouse(self):
        """The warehouse the department's stock questions are answered against."""
        self.ensure_one()
        return self.warehouse_id or self.env["stock.warehouse"].search(
            [("company_id", "=", self.company_id.id)], limit=1)
