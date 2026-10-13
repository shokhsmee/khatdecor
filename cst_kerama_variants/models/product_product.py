from odoo import api, fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    # The characteristic as one text — «Глянцевый, 70 гр, 183 см, 277 см» — so a
    # storekeeper can search it, group by it and read it in a list without
    # opening the variant. Stored: it only changes when the combination does.
    cst_characteristic = fields.Char(
        string="Xarakteristika", compute="_compute_cst_characteristic", store=True,
        index="trigram")

    @api.depends("product_template_attribute_value_ids.name",
                 "product_template_attribute_value_ids.attribute_id.sequence")
    def _compute_cst_characteristic(self):
        for product in self:
            values = product.product_template_attribute_value_ids.sorted(
                lambda v: (v.attribute_id.sequence, v.attribute_id.id, v.product_attribute_value_id.sequence))
            product.cst_characteristic = ", ".join(values.mapped("name"))

    def cst_base_name(self):
        """«[00011749] Кашмир (115076) ЛДСП» — the product without its
        characteristic, for sheets that print the characteristic in its own
        column."""
        self.ensure_one()
        name = self.product_tmpl_id.name or ""
        return "[%s] %s" % (self.default_code, name) if self.default_code else name


class StockQuant(models.Model):
    _inherit = "stock.quant"

    cst_characteristic = fields.Char(related="product_id.cst_characteristic", string="Xarakteristika")


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    cst_characteristic = fields.Char(related="product_id.cst_characteristic", string="Xarakteristika")
