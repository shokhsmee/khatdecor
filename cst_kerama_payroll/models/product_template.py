from odoo import api, fields, models


class ProductTemplate(models.Model):
    """Products carry the sales KPI rate the manager earns per unit sold."""

    _inherit = "product.template"

    cst_pay_currency_id = fields.Many2one(
        "res.currency", compute="_compute_cst_pay_currency_id", string="Oylik valyutasi")
    cst_kpi_rate = fields.Monetary(
        string="Sotuv KPI (1 dona uchun)",
        currency_field="cst_pay_currency_id",
        help="Сотув менежери шу махсулотнинг бир бирлигини сотиб, пули тулик "
             "тушганда оладиган сумма.  Ноль булса — бу махсулот учун KPI "
             "хисобланмайди.\n\n"
             "Ставка узгартирилса, факат кейинги хисоблашларга таъсир килади: "
             "хар бир KPI катори узи хисобланган ставкани саклаб колади, "
             "шунинг учун ёпилган ойлар узгармайди.")

    @api.depends("company_id")
    @api.depends_context("company")
    def _compute_cst_pay_currency_id(self):
        # KPI is paid with the salary, so it is priced in the salary's currency
        for template in self:
            template.cst_pay_currency_id = (template.company_id or self.env.company)._cst_payroll_currency()
