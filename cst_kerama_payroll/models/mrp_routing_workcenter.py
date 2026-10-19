from odoo import api, fields, models


class MrpRoutingWorkcenter(models.Model):
    """A BOM operation *is* the product × operation pair, so the piece rate
    belongs here: one rate per finished product per operation, with no second
    table to keep in step with the routings."""

    _inherit = "mrp.routing.workcenter"

    cst_kpi_rate = fields.Monetary(
        string="Ishbay KPI (1 dona uchun)",
        currency_field="cst_currency_id",
        help="Шу операцияни шу махсулот учун бажарган ходим бир дона тайёр "
             "махсулот учун оладиган сумма.  Ноль булса — бу операция учун "
             "ишбай хисобланмайди.\n\n"
             "Ставка узгартирилса, факат кейинги хисоблашларга таъсир килади: "
             "хисобланган хар бир катор уз ставкасини саклаб колади.")
    cst_currency_id = fields.Many2one(
        "res.currency", compute="_compute_cst_currency_id", string="Currency")

    @api.depends("company_id")
    @api.depends_context("company")
    def _compute_cst_currency_id(self):
        # A BOM shared across companies has no company_id, and a Monetary with
        # no currency renders blank — fall back to the company in context.
        # The piece rate is paid with the salary — in the payroll currency.
        for operation in self:
            operation.cst_currency_id = (operation.company_id or self.env.company)._cst_payroll_currency()
