from odoo import api, fields, models


class CstProductionFactWizard(models.TransientModel):
    _name = "cst.production.fact.wizard"
    _description = "Ishlab chiqarish fakti"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_production_fact"

    product_ids = fields.Many2many("product.product", string="Mahsulotlar")

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "title": "Ishlab chiqarilgan mahsulotlar hisoboti",
            "date_from": self.date_from, "date_to": self.date_to,
            "companies": self.env["cst.production.fact.report"].build(
                self.date_from, self.date_to, company_ids=self.company_ids.ids or None,
                product_ids=self.product_ids.ids or None),
        }


class CstAssetReportWizard(models.TransientModel):
    _name = "cst.asset.report.wizard"
    _description = "Asosiy vositalar"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_assets"

    include_closed = fields.Boolean(string="Hisobdan chiqarilganlarni ham")

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "title": "Asosiy vositalar qoldiq summalari bilan",
            "date_from": self.date_to, "date_to": self.date_to,
            "companies": self.env["cst.asset.report"].build(
                company_ids=self.company_ids.ids or None, include_closed=self.include_closed),
        }


class CstTaxMovementWizard(models.TransientModel):
    _name = "cst.tax.movement.wizard"
    _description = "Soliqlar harakati"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_tax_movement"

    account_ids = fields.Many2many(
        "account.account", string="Soliq hisoblari",
        default=lambda self: self.env["cst.tax.report"].default_accounts(self.env.companies),
        help="Soliq turlari — hisob raqamlari. Standart ro'yxat soliq sozlamalari, oylik "
             "soliq komponentlari va 64xx/65xx hisoblaridan yig'iladi; o'zgartirish mumkin.")

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "title": "Hisoblangan va to'langan soliqlar bo'yicha batafsil hisobot",
            "date_from": self.date_from, "date_to": self.date_to,
            "companies": self.env["cst.tax.report"].movement(
                self.date_from, self.date_to, account_ids=self.account_ids.ids or None,
                company_ids=self.company_ids.ids or None),
        }


class CstTaxStatementWizard(models.TransientModel):
    _name = "cst.tax.statement.wizard"
    _description = "Soliq akt sverkasi"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_tax_statement"

    account_id = fields.Many2one(
        "account.account", string="Soliq turi (hisob)", required=True,
        domain=lambda self: [("id", "in", self.env["cst.tax.report"].default_accounts(self.env.companies).ids)])
    date_from = fields.Date(
        default=lambda self: fields.Date.start_of(fields.Date.context_today(self), "year"))

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "title": "%s bo'yicha batafsil hisobot" % self.account_id.name,
            "date_from": self.date_from, "date_to": self.date_to,
            "companies": self.env["cst.tax.report"].statement(
                self.account_id, self.date_from, self.date_to,
                company_ids=self.company_ids.ids or None),
        }


class CstUtilityStatementWizard(models.TransientModel):
    """«Kommunal xizmatlar akt sverkasi» — the counterparty card of a utility.

    Utilities are ordinary suppliers: their invoices are vendor bills, their
    payments are registered payments. The wizard only narrows the partner list
    to the ones tagged «Kommunal xizmatlar» and prints the same card.
    """

    _name = "cst.utility.statement.wizard"
    _description = "Kommunal xizmatlar akt sverkasi"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_utility_statement"

    partner_id = fields.Many2one(
        "res.partner", string="Kommunal xizmat ta'minotchisi", required=True,
        domain=lambda self: self._partner_domain())
    date_from = fields.Date(
        default=lambda self: fields.Date.start_of(fields.Date.context_today(self), "year"))

    @api.model
    def _partner_domain(self):
        tag = self.env.ref("cst_kerama_reports.partner_category_utilities", raise_if_not_found=False)
        if tag and self.env["res.partner"].search_count([("category_id", "in", tag.ids)]):
            return [("category_id", "in", tag.ids)]
        return [("supplier_rank", ">", 0)]

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "partner": self.partner_id,
            "title": "Kommunal xizmatlar akt sverkasi: %s" % self.partner_id.display_name,
            "date_from": self.date_from, "date_to": self.date_to,
            "companies": self.env["cst.partner.statement"].statement_rows(
                self.partner_id, self.date_from, self.date_to,
                company_ids=self.company_ids.ids or None),
        }


class CstCardPaymentsWizard(models.TransientModel):
    _name = "cst.card.payments.wizard"
    _description = "Plastik kartaga o'tkazmalar"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_card_payments"

    component_ids = fields.Many2many(
        "cst.payroll.component", string="Komponentlar",
        default=lambda self: self.env["cst.card.payments.report"].default_components(),
        help="Standart: kodida PLASTIK / KARTA bo'lgan ushlanmalar.")
    employee_ids = fields.Many2many("hr.employee", string="Xodimlar")
    include_draft = fields.Boolean(string="Qoralama yozuvlar bilan")

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "title": "Xodimlar plastik kartasiga tashlangan pullar",
            "date_from": self.date_from, "date_to": self.date_to,
            "data": self.env["cst.card.payments.report"].build(
                self.date_from, self.date_to, component_ids=self.component_ids.ids or None,
                employee_ids=self.employee_ids.ids or None,
                company_ids=self.company_ids.ids or None, include_draft=self.include_draft),
        }


class CstBankFeeWizard(models.TransientModel):
    _name = "cst.bank.fee.wizard"
    _description = "Bank xarajatlari"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_bank_fees"

    journal_ids = fields.Many2many("account.journal", string="Bank jurnallari",
                                   domain="[('type', '=', 'bank')]")
    date_from = fields.Date(
        default=lambda self: fields.Date.start_of(fields.Date.context_today(self), "year"))

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "title": "Bank xarajatlari hisoboti",
            "date_from": self.date_from, "date_to": self.date_to,
            "companies": self.env["cst.bank.fee.report"].build(
                self.date_from, self.date_to, journal_ids=self.journal_ids.ids or None,
                company_ids=self.company_ids.ids or None),
        }
