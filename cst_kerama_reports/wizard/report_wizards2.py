from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CstPeriodWizard(models.AbstractModel):
    """Date range + companies, shared by every sheet wizard below."""

    _name = "cst.period.wizard"
    _description = "Period wizard base"

    date_from = fields.Date(
        string="Davr boshi", required=True,
        default=lambda self: fields.Date.start_of(fields.Date.context_today(self), "month"))
    date_to = fields.Date(
        string="Davr oxiri", required=True,
        default=lambda self: fields.Date.context_today(self))
    company_ids = fields.Many2many(
        "res.company", string="Kompaniyalar",
        default=lambda self: self.env.companies)

    @api.constrains("date_from", "date_to")
    def _check_period(self):
        for wizard in self:
            if wizard.date_to < wizard.date_from:
                raise UserError(_("Davr oxiri boshidan oldin bo'lishi mumkin emas."))

    def _report(self, suffix=""):
        self.ensure_one()
        return self.env.ref("cst_kerama_reports.%s%s" % (self._report_xmlid, suffix)).report_action(self)

    def action_print(self):
        return self._report()

    def action_view(self):
        return self._report("_html")


# ---------------------------------------------------------------- Oylik
class CstEmployeeCardWizard(models.TransientModel):
    _name = "cst.employee.card.wizard"
    _description = "Xodim oyligi kartochkasi"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_employee_card"

    employee_id = fields.Many2one("hr.employee", string="Xodim", required=True)
    include_draft = fields.Boolean(string="Qoralama yozuvlar bilan")
    date_from = fields.Date(
        default=lambda self: fields.Date.start_of(fields.Date.context_today(self), "year"))

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "title": "Xodim oyligi: %s" % self.employee_id.display_name,
            "date_from": self.date_from, "date_to": self.date_to,
            "data": self.env["cst.employee.card.report"].build(
                self.employee_id, self.date_from, self.date_to,
                include_draft=self.include_draft, company_ids=self.company_ids.ids or None),
        }


class CstBonusPenaltyWizard(models.TransientModel):
    _name = "cst.bonus.penalty.wizard"
    _description = "Jarimalar va bonuslar"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_bonus_penalty"

    employee_ids = fields.Many2many("hr.employee", string="Xodimlar")
    include_draft = fields.Boolean(string="Qoralama yozuvlar bilan")

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "title": "Jarimalar va bonuslar hisoboti",
            "date_from": self.date_from, "date_to": self.date_to,
            "data": self.env["cst.bonus.penalty.report"].build(
                self.date_from, self.date_to, employee_ids=self.employee_ids.ids or None,
                company_ids=self.company_ids.ids or None, include_draft=self.include_draft),
        }


class CstKpiReportWizard(models.TransientModel):
    _name = "cst.kpi.report.wizard"
    _description = "KPI hisoboti"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_kpi"

    computation = fields.Selection(
        [("kpi_sales", "Sotuv KPI"), ("kpi_production", "Ishbay KPI"),
         ("kpi_unloading", "Yuk tushirish KPI")],
        string="KPI turi", required=True, default="kpi_sales")
    employee_ids = fields.Many2many("hr.employee", string="Xodimlar")
    include_draft = fields.Boolean(string="Qoralama yozuvlar bilan")

    def _report_values(self):
        self.ensure_one()
        label = dict(self._fields["computation"].selection)[self.computation]
        return {
            "wizard": self, "title": "%s hisoboti" % label,
            "date_from": self.date_from, "date_to": self.date_to,
            "data": self.env["cst.kpi.report"].build(
                self.date_from, self.date_to, computation=self.computation,
                employee_ids=self.employee_ids.ids or None,
                company_ids=self.company_ids.ids or None, include_draft=self.include_draft),
        }


# ---------------------------------------------------------------- Kassa
class CstCashReportWizard(models.TransientModel):
    _name = "cst.cash.report.wizard"
    _description = "Pullar harakati"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_cash"

    journal_ids = fields.Many2many(
        "account.journal", string="Kassa / bank",
        domain="[('type', 'in', ('cash', 'bank'))]",
        help="Bo'sh qoldirilsa, barcha kassa va bank jurnallari chiqadi.")
    detail = fields.Boolean(string="Har bir harakat bilan", default=True)

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "title": "Pullar harakati hisoboti",
            "date_from": self.date_from, "date_to": self.date_to, "detail": self.detail,
            "companies": self.env["cst.cash.report"].build(
                self.date_from, self.date_to, journal_ids=self.journal_ids.ids or None,
                company_ids=self.company_ids.ids or None, detail=self.detail),
        }


class CstExpenseReportWizard(models.TransientModel):
    _name = "cst.expense.report.wizard"
    _description = "Xarajatlar hisoboti"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_expense"

    scope = fields.Selection(
        [("cash", "Faqat kassa orqali"), ("cash_bank", "Kassa va bank orqali"),
         ("all", "Barcha xarajatlar")],
        string="Qamrov", required=True, default="all")
    display_currency_id = fields.Many2one(
        "res.currency", string="Valyuta",
        default=lambda self: self.env.company.currency_id,
        help="Har bir yozuv o'z sanasidagi kurs bo'yicha o'giriladi.")
    include_direct_cost = fields.Boolean(
        string="Tannarxni ham qo'shish",
        help="Sotilgan mahsulot tannarxi (direct cost) hisoblarini ham ko'rsatish.")
    detail = fields.Boolean(string="Har bir yozuv bilan")

    def _report_values(self):
        self.ensure_one()
        types = {"cash": ("cash",), "cash_bank": ("cash", "bank"), "all": None}[self.scope]
        title = {"cash": "Kassa orqali xarajatlar hisoboti",
                 "cash_bank": "Kassa va bank orqali xarajatlar",
                 "all": "Xarajat harakati hisoboti"}[self.scope]
        return {
            "wizard": self, "title": title,
            "date_from": self.date_from, "date_to": self.date_to, "detail": self.detail,
            "companies": self.env["cst.expense.report"].build(
                self.date_from, self.date_to, company_ids=self.company_ids.ids or None,
                journal_types=types, display_currency=self.display_currency_id,
                include_direct_cost=self.include_direct_cost, detail=self.detail),
        }


# ---------------------------------------------------------------- Ombor
class CstWriteoffReportWizard(models.TransientModel):
    _name = "cst.writeoff.report.wizard"
    _description = "Hisobdan chiqarilganlar"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_writeoff"

    warehouse_ids = fields.Many2many("stock.warehouse", string="Omborlar")

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "title": "Hisobdan chiqarilgan xomashyo va mahsulotlar",
            "date_from": self.date_from, "date_to": self.date_to,
            "companies": self.env["cst.writeoff.report"].build(
                self.date_from, self.date_to, warehouse_ids=self.warehouse_ids.ids or None,
                company_ids=self.company_ids.ids or None),
        }


class CstInventoryCountWizard(models.TransientModel):
    _name = "cst.inventory.count.wizard"
    _description = "Reviziya hisoboti"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_inventory_count"

    warehouse_ids = fields.Many2many("stock.warehouse", string="Omborlar")

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "title": "Reviziya hisoboti",
            "date_from": self.date_from, "date_to": self.date_to,
            "companies": self.env["cst.inventory.count.report"].build(
                self.date_from, self.date_to, warehouse_ids=self.warehouse_ids.ids or None,
                company_ids=self.company_ids.ids or None),
        }


class CstConsumptionReportWizard(models.TransientModel):
    _name = "cst.consumption.report.wizard"
    _description = "Norma va fakt sarfi"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_consumption"

    product_ids = fields.Many2many("product.product", string="Tayyor mahsulotlar")
    only_deviations = fields.Boolean(
        string="Faqat farqi borlar", default=True,
        help="Normadan farq qilmagan komponentlar ko'rsatilmaydi.")

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "title": "Normadan kam yoki ko'p sarflangan mahsulotlar",
            "date_from": self.date_from, "date_to": self.date_to,
            "orders": self.env["cst.consumption.report"].build(
                self.date_from, self.date_to, company_ids=self.company_ids.ids or None,
                product_ids=self.product_ids.ids or None, only_deviations=self.only_deviations),
        }


class CstStockLedgerWizard(models.TransientModel):
    _name = "cst.stock.ledger.wizard"
    _description = "Ombor batafsil hisoboti"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_stock_ledger"

    warehouse_ids = fields.Many2many("stock.warehouse", string="Omborlar")
    category_ids = fields.Many2many("product.category", string="Kategoriyalar")
    product_ids = fields.Many2many("product.product", string="Mahsulotlar")
    hide_zero = fields.Boolean(string="Harakatsiz qatorlarni yashirish", default=True)

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "title": "Omborlar bo'yicha tovar va xom ashyolar harakati",
            "date_from": self.date_from, "date_to": self.date_to,
            "data": self.env["cst.stock.ledger.report"].build(
                self.date_from, self.date_to, warehouse_ids=self.warehouse_ids.ids or None,
                category_ids=self.category_ids.ids or None,
                product_ids=self.product_ids.ids or None,
                company_ids=self.company_ids.ids or None, hide_zero=self.hide_zero),
        }

    def action_xlsx(self):
        """The workbook — 31 columns read far better in Excel than on paper."""
        self.ensure_one()
        return {"type": "ir.actions.act_url", "target": "self",
                "url": "/cst_reports/stock_ledger/xlsx/%d" % self.id}

    def action_print(self):
        return self.action_view()


class CstMinMaxReportWizard(models.TransientModel):
    _name = "cst.minmax.report.wizard"
    _description = "Min-max bo'yicha qoldiqlar"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_minmax"

    warehouse_ids = fields.Many2many("stock.warehouse", string="Omborlar")
    category_ids = fields.Many2many("product.category", string="Kategoriyalar")
    only_deviations = fields.Boolean(
        string="Faqat kam yoki ko'p turganlar", default=True,
        help="Min va max oralig'ida turgan mahsulotlar ko'rsatilmaydi.")
    include_without_rule = fields.Boolean(
        string="Qoidasi yo'q mahsulotlarni ham",
        help="Min/max belgilanmagan, lekin qoldig'i bor mahsulotlar ham chiqadi — "
             "nimaga chegara qo'yish kerakligini ko'rish uchun.")

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "title": "Kam yoki ko'p miqdorda turgan mahsulot va xomashyolar",
            "date_from": fields.Date.context_today(self), "date_to": fields.Date.context_today(self),
            "warehouses": self.env["cst.minmax.report"].build(
                warehouse_ids=self.warehouse_ids.ids or None,
                category_ids=self.category_ids.ids or None,
                company_ids=self.company_ids.ids or None,
                only_deviations=self.only_deviations,
                include_without_rule=self.include_without_rule),
        }

    def action_xlsx(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "target": "self",
                "url": "/cst_reports/minmax/xlsx/%d" % self.id}
