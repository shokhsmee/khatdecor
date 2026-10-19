from odoo import api, fields, models


class CstProductTasnif(models.Model):
    """Tasnif — the condition a product is sold in (1-sort, 2-sort, brak ...).
    Printed on the receipt once its layout is agreed."""

    _name = "cst.product.tasnif"
    _description = "Mahsulot tasnifi"
    _order = "sequence, id"

    name = fields.Char(string="Tasnif", required=True, translate=True)
    code = fields.Char(string="Kod")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    cst_tasnif_id = fields.Many2one(
        "cst.product.tasnif", string="Tasnif",
        help="Mahsulot holati (masalan 1-sort, 2-sort, brak). Sotuv qatoriga avtomatik o'tadi.")


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    cst_tasnif_id = fields.Many2one(
        "cst.product.tasnif", string="Tasnif", compute="_compute_cst_tasnif_id",
        store=True, readonly=False, precompute=True,
        help="Mahsulotdan olinadi, qatorda o'zgartirish mumkin. Chekda chiqariladi.")

    @api.depends("product_id")
    def _compute_cst_tasnif_id(self):
        second = self.env.ref("cst_kerama_sale_receipt.tasnif_second", raise_if_not_found=False)
        for line in self:
            product = line.product_id
            tasnif = product.product_tmpl_id.cst_tasnif_id
            # the 2-sort twins (cst_kerama_variants) say what they are
            if not tasnif and second and product.product_tmpl_id._fields.get("cst_is_second_grade") \
                    and product.product_tmpl_id.cst_is_second_grade:
                tasnif = second
            line.cst_tasnif_id = tasnif
