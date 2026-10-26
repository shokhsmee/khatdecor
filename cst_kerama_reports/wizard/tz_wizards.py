from odoo import fields, models


class CstPurchasedGoodsWizard(models.TransientModel):
    _name = "cst.purchased.goods.wizard"
    _description = "Sotib olingan mahsulotlar"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_purchased_goods"

    partner_ids = fields.Many2many("res.partner", string="Ta'minotchilar", domain=[("supplier_rank", ">", 0)])
    category_ids = fields.Many2many("product.category", string="Kategoriyalar")
    layout = fields.Selection(
        [("dated", "Ta'minotchi → valyuta → sana bo'yicha"), ("summary", "Mahsulot bo'yicha jamlama")],
        string="Ko'rinish", default="dated", required=True)
    by_supplier = fields.Boolean(string="Ta'minotchi bo'yicha guruhlash")

    def _report_values(self):
        self.ensure_one()
        values = {
            "wizard": self, "title": "Sotib olingan mahsulot va xom ashyo (soni va tannarxi)",
            "date_from": self.date_from, "date_to": self.date_to, "layout": self.layout or "summary",
        }
        if self.layout == "dated":
            values["companies"] = self.env["cst.purchased.goods.report"].build_dated(
                self.date_from, self.date_to, partner_ids=self.partner_ids.ids or None,
                category_ids=self.category_ids.ids or None, company_ids=self.company_ids.ids or None)
            return values
        return dict(values, **{
            "companies": self.env["cst.purchased.goods.report"].build(
                self.date_from, self.date_to, partner_ids=self.partner_ids.ids or None,
                category_ids=self.category_ids.ids or None, company_ids=self.company_ids.ids or None,
                by_supplier=self.by_supplier),
        })


class CstEmployeesWizard(models.TransientModel):
    _name = "cst.employees.wizard"
    _description = "Ishlayotgan xodimlar"

    day = fields.Date(string="Sana", required=True, default=fields.Date.context_today)
    company_ids = fields.Many2many("res.company", string="Kompaniyalar", default=lambda self: self.env.companies)
    department_ids = fields.Many2many("hr.department", string="Bo'limlar")
    presence = fields.Selection([("all", "Hammasi"), ("present", "Faqat kelganlar"), ("absent", "Faqat kelmaganlar")],
                                string="Ko'rsatish", default="all", required=True)

    def _report_values(self):
        self.ensure_one()
        data = self.env["cst.employees.report"].build(
            self.day, company_ids=self.company_ids.ids or None,
            department_ids=self.department_ids.ids or None, presence=self.presence)
        return dict(data, wizard=self, title="Ishlayotgan xodimlar")

    def action_print(self):
        return self.env.ref("cst_kerama_reports.action_report_employees").report_action(self)

    def action_view(self):
        return self.env.ref("cst_kerama_reports.action_report_employees_html").report_action(self)
