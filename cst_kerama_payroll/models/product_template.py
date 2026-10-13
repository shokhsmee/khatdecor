from odoo import fields, models


class ProductTemplate(models.Model):
    """Products carry the sales KPI rate the manager earns per unit sold."""

    _inherit = "product.template"

    cst_kpi_rate = fields.Monetary(
        string="Sotuv KPI (1 dona uchun)",
        currency_field="currency_id",
        help="Сотув менежери шу махсулотнинг бир бирлигини сотиб, пули тулик "
             "тушганда оладиган сумма.  Ноль булса — бу махсулот учун KPI "
             "хисобланмайди.\n\n"
             "Ставка узгартирилса, факат кейинги хисоблашларга таъсир килади: "
             "хар бир KPI катори узи хисобланган ставкани саклаб колади, "
             "шунинг учун ёпилган ойлар узгармайди.")
