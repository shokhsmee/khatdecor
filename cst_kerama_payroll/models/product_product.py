from odoo import api, fields, models


class ProductProduct(models.Model):
    """The sales KPI rate, per variant when the variants differ.

    The template keeps the rate every variant inherits; a variant may take its
    own — a premium finish may pay the manager more per sheet than the plain
    one. The switch is explicit so a variant can also be given *no* KPI while
    its siblings have one (a zero on its own would be read as "not set").
    Whatever applies is copied onto the KPI line at calculation time, as
    before, so closed months never move.
    """

    _inherit = "product.product"

    cst_kpi_use_variant = fields.Boolean(
        string="Variant stavkasi alohida",
        help="Belgilansa, shu variant uchun pastdagi stavka qo'llanadi (nol bo'lsa ham). "
             "Belgilanmasa, mahsulotning umumiy stavkasi olinadi.")
    cst_kpi_rate_variant = fields.Monetary(
        string="Sotuv KPI (shu variant uchun)", currency_field="currency_id")
    cst_kpi_rate_effective = fields.Monetary(
        string="Amaldagi sotuv KPI", currency_field="currency_id",
        compute="_compute_cst_kpi_rate_effective", store=True,
        help="Hisoblashda ishlatiladigan stavka: variantniki (belgilangan bo'lsa) yoki "
             "mahsulotning umumiy stavkasi.")

    @api.depends("cst_kpi_use_variant", "cst_kpi_rate_variant", "product_tmpl_id.cst_kpi_rate")
    def _compute_cst_kpi_rate_effective(self):
        for product in self:
            product.cst_kpi_rate_effective = (
                product.cst_kpi_rate_variant if product.cst_kpi_use_variant
                else product.product_tmpl_id.cst_kpi_rate)
