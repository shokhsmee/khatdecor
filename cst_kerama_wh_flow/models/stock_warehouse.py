from collections import Counter

from odoo import api, fields, models

# the operation names every warehouse uses: «<code> - <name>», one string in every language
OPERATION_NAMES = {
    "IN": "Qabul qilish", "OUT": "Yetkazib berish", "INT": "Ichki ko‘chirish", "MO": "Ishlab chiqarish",
    "PICK": "Tanlash", "PACK": "O‘rash", "QC": "Sifat nazorati", "STOR": "Saqlash", "XD": "Kross-dok",
    "PC": "Komponentlarni tanlash", "SFP": "Tayyor mahsulotni saqlash", "POS": "PoS buyurtmalari",
}


class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    cst_receiver_id = fields.Many2one(
        "res.users", string="Qabul qiluvchi", domain=[("share", "=", False)],
        help="Shu omborga keladigan ichki ko'chirishlarga avtomatik yoziladi; faqat u "
             "(yoki ombor nazoratchisi) tasdiqlay oladi.")
    cst_department_ids = fields.One2many(
        "cst.production.department", "warehouse_id", string="Ishlaydigan bo'limlar")
    cst_color = fields.Integer(
        string="Rang", help="Omborning barcha operatsiyalari Ombor sharhida shu rangda ko'rinadi.")

    def _cst_picking_types(self):
        return self.env["stock.picking.type"].with_context(active_test=False).search(
            [("warehouse_id", "in", self.ids)])

    def _cst_free_color(self, company):
        used = Counter(self.search([("company_id", "=", company.id)]).mapped("cst_color"))
        # 1..11 is Odoo's kanban palette; 0 is «no colour»
        return min(range(1, 12), key=lambda c: (used[c], c))

    def _get_picking_type_create_values(self, max_sequence):
        values, max_sequence = super()._get_picking_type_create_values(max_sequence)
        for vals in values.values():
            name = OPERATION_NAMES.get(vals.get("sequence_code"))
            if name:
                vals["name"] = "%s - %s" % (self.code, name)
        return values, max_sequence

    def _cst_sync_view_location_name(self):
        """Locations read «Обой цехи/Zaxira», not «ОЦ/Zaxira»: Odoo names a
        warehouse's top location after its short code, the shop wants the name."""
        for warehouse in self:
            view = warehouse.view_location_id
            if view and warehouse.name and view.name != warehouse.name:
                view.name = warehouse.name

    @api.model_create_multi
    def create(self, vals_list):
        warehouses = super().create(vals_list)
        warehouses._cst_sync_view_location_name()
        for warehouse, vals in zip(warehouses, vals_list):
            if not vals.get("cst_color"):
                warehouse.cst_color = warehouse._cst_free_color(warehouse.company_id)
            else:
                warehouse._cst_picking_types().write({"color": warehouse.cst_color})
        return warehouses

    def write(self, vals):
        result = super().write(vals)
        if {"name", "code"} & set(vals):
            self._cst_sync_view_location_name()
        if "cst_color" in vals:
            self._cst_picking_types().write({"color": vals["cst_color"]})
        return result
