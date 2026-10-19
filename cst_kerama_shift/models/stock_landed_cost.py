from odoo import fields, models


class StockLandedCost(models.Model):
    _inherit = "stock.landed.cost"

    cst_kpi_pay_amount = fields.Float(
        string="Smena KPI (oylik valyutasida)", digits=(16, 2), readonly=True, copy=False,
        help="The shift KPI this cost carries, in so'm — the shift compares it with its KPI fund.")
