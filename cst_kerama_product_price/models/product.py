from odoo import api, fields, models


class ProductProduct(models.Model):
    """A sale price per characteristic.

    Odoo prices the variants of one product with additive attribute extras
    only, while the shop prices «Кашмир ЛДСП Глянцевый» and «… Гладкий» on
    their own. A variant may carry its own price, in its own currency (dollar
    or so'm); when it does, ``price_extra`` is made to bridge the template's
    base price to it, so ``lst_price``, sale order lines and pricelists based
    on the sales price all see the variant's price without further hooks.
    """

    _inherit = "product.product"

    cst_sale_price = fields.Float(
        string="Sotish narxi (xarakteristika)", digits="Product Price",
        help="Shu xarakteristikaning o'z sotish narxi. 0 — mahsulotning umumiy narxi ishlaydi.")
    cst_sale_currency_id = fields.Many2one(
        "res.currency", string="Narx valyutasi",
        help="Xarakteristika narxi qaysi valyutada. Bo'sh — kompaniya valyutasi.")

    def _cst_own_price(self):
        """The variant's own price in the product's currency, or None."""
        self.ensure_one()
        if not self.cst_sale_price:
            return None
        currency = self.cst_sale_currency_id or self.currency_id
        if currency == self.currency_id:
            return self.cst_sale_price
        company = self.company_id or self.env.company
        return currency._convert(self.cst_sale_price, self.currency_id, company, fields.Date.context_today(self))

    @api.depends("product_template_attribute_value_ids.price_extra", "cst_sale_price",
                 "cst_sale_currency_id", "list_price")
    def _compute_product_price_extra(self):
        super()._compute_product_price_extra()
        for product in self:
            own = product._cst_own_price()
            if own is not None:
                product.price_extra = own - product.list_price

    def _set_product_lst_price(self):
        """Typing a price on a variant that has its own price changes that price,
        not the template's base price shared by its siblings."""
        own = self.filtered(lambda p: p.cst_sale_price)
        for product in own:
            value = product.lst_price
            if self.env.context.get("uom"):
                value = self.env["uom.uom"].browse(self.env.context["uom"])._compute_price(value, product.uom_id)
            currency = product.cst_sale_currency_id or product.currency_id
            if currency != product.currency_id:
                company = product.company_id or self.env.company
                value = product.currency_id._convert(value, currency, company, fields.Date.context_today(product))
            product.cst_sale_price = value
        return super(ProductProduct, self - own)._set_product_lst_price()


class ProductTemplate(models.Model):
    _inherit = "product.template"

    cst_variant_price_count = fields.Integer(compute="_compute_cst_variant_price_count")

    @api.depends("product_variant_ids.cst_sale_price")
    def _compute_cst_variant_price_count(self):
        for template in self:
            template.cst_variant_price_count = len(template.product_variant_ids.filtered("cst_sale_price"))
