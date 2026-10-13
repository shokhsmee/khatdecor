from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CstWarehouseReportWizard(models.TransientModel):
    """«Omborlar hisoboti» — period, warehouses, and whether to print photos."""

    _name = "cst.warehouse.report.wizard"
    _description = "Omborlar hisoboti"

    date_from = fields.Date(
        string="Davr boshi", required=True,
        default=lambda self: fields.Date.start_of(fields.Date.context_today(self), "month"))
    date_to = fields.Date(
        string="Davr oxiri", required=True,
        default=lambda self: fields.Date.context_today(self))
    warehouse_ids = fields.Many2many(
        "stock.warehouse", string="Omborlar",
        help="Bo'sh qoldirilsa, ruxsat etilgan barcha omborlar chiqadi.")
    category_ids = fields.Many2many("product.category", string="Kategoriyalar")
    product_ids = fields.Many2many("product.product", string="Mahsulotlar")
    hide_zero = fields.Boolean(
        string="Harakatsiz qatorlarni yashirish", default=True)
    show_image = fields.Boolean(string="Suratlari bilan", default=True)

    @api.constrains("date_from", "date_to")
    def _check_period(self):
        for wizard in self:
            if wizard.date_to < wizard.date_from:
                raise UserError(_("Davr oxiri boshidan oldin bo'lishi mumkin emas."))

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "show_image": self.show_image,
            "title": "Omborlar hisoboti",
            "warehouses": self.env["cst.warehouse.report"].build(
                self.date_from, self.date_to,
                warehouse_ids=self.warehouse_ids.ids or None,
                category_ids=self.category_ids.ids or None,
                product_ids=self.product_ids.ids or None,
                hide_zero=self.hide_zero,
                show_image=self.show_image,
            ),
        }

    def action_print(self):
        return self.env.ref(
            "cst_kerama_reports.action_report_warehouse").report_action(self)

    def action_view(self):
        return self.env.ref(
            "cst_kerama_reports.action_report_warehouse_html").report_action(self)
