from odoo import fields, models


class CstGoodsMovementWizard(models.TransientModel):
    """«Tovar harakati» — period, warehouses, categories, products."""

    _name = "cst.goods.movement.wizard"
    _description = "Tovar harakati"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_goods_movement"

    warehouse_ids = fields.Many2many(
        "stock.warehouse", string="Omborlar",
        help="Bo'sh qoldirilsa, ruxsat etilgan barcha omborlar chiqadi.")
    category_ids = fields.Many2many("product.category", string="Kategoriyalar")
    product_ids = fields.Many2many("product.product", string="Mahsulotlar")
    together = fields.Boolean(
        string="Omborlarni birlashtirish",
        help="Tanlangan omborlar bitta ombor deb ko'riladi: ular orasidagi ko'chirishlar ko'rsatilmaydi.")
    hide_zero = fields.Boolean(string="Harakatsiz qatorlarni yashirish", default=True)

    def _report_values(self):
        self.ensure_one()
        engine = self.env["cst.goods.movement.report"]
        return {
            "wizard": self, "title": "Tovar harakati (Товарнинг ҳаракати)",
            "date_from": self.date_from, "date_to": self.date_to,
            "columns": engine.columns(),
            "data": engine.build(
                self.date_from, self.date_to,
                warehouse_ids=self.warehouse_ids.ids or None,
                category_ids=self.category_ids.ids or None,
                product_ids=self.product_ids.ids or None,
                company_ids=self.company_ids.ids or None,
                together=self.together, hide_zero=self.hide_zero),
        }

    def action_xlsx(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "target": "self",
                "url": "/cst_reports/goods_movement/xlsx/%d" % self.id}
