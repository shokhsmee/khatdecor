from odoo import _, api, fields, models


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
    hide_zero = fields.Boolean(
        string="Harakatsiz qatorlarni yashirish", default=True,
        help="Davrda kirim ham, chiqim ham bo'lmagan mahsulotlar ko'rsatilmaydi (faqat qoldig'i turganlar). "
             "Ekranda mahsulot nomini bossangiz — uning sanama-sana harakati va hozirgi qoldig'i ochiladi.")

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


class CstProductCardWizard(models.TransientModel):
    """«Mahsulot kartochkasi» — a product's movements date by date, with the
    running balance and the stock on hand now per warehouse."""

    _name = "cst.product.card.wizard"
    _description = "Mahsulot kartochkasi"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_product_card"

    product_ids = fields.Many2many("product.product", string="Mahsulotlar", required=True)
    warehouse_ids = fields.Many2many(
        "stock.warehouse", string="Omborlar",
        help="Bo'sh qoldirilsa, ruxsat etilgan barcha omborlar chiqadi.")
    together = fields.Boolean(
        string="Omborlarni birlashtirish",
        help="Tanlangan omborlar bitta ombor deb ko'riladi: ular orasidagi ko'chirishlar ko'rsatilmaydi.")
    daily = fields.Boolean(string="Kunlik jamlash", help="Har kun bitta qator: kirim, chiqim, kun oxiridagi qoldiq.")

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "title": "Mahsulot kartochkasi (sanama-sana harakat)",
            "date_from": self.date_from, "date_to": self.date_to,
            "products": self.env["cst.product.card.report"].build(
                self.product_ids.ids, self.date_from, self.date_to,
                warehouse_ids=self.warehouse_ids.ids or None,
                company_ids=self.company_ids.ids or None,
                together=self.together, daily=self.daily),
        }

    def action_xlsx(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "target": "self",
                "url": "/cst_reports/product_card/xlsx/%d" % self.id}

    @api.model
    def action_open_card(self, product_id, date_from=None, date_to=None, warehouse_ids=None,
                         company_ids=None, together=False):
        """Opened from a «Tovar harakati» row: the same period and warehouses."""
        values = {"product_ids": [(6, 0, [int(product_id)])], "together": bool(together)}
        if date_from:
            values["date_from"] = date_from
        if date_to:
            values["date_to"] = date_to
        if warehouse_ids:
            values["warehouse_ids"] = [(6, 0, [int(w) for w in warehouse_ids])]
        if company_ids:
            values["company_ids"] = [(6, 0, [int(c) for c in company_ids])]
        return self.create(values).action_view()

    @api.model
    def action_from_products(self, product_ids):
        return {
            "type": "ir.actions.act_window", "name": _("Mahsulot kartochkasi"),
            "res_model": self._name, "view_mode": "form", "target": "new",
            "context": {"default_product_ids": [(6, 0, list(product_ids))]},
        }
