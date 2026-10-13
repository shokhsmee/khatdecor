from odoo import api, models


def _copy_plain_names(records, plain):
    """Carry names computed in the code-less context back onto `records`.

    The compute has to run on a recordset that carries `display_default_code`,
    and a value computed in one environment never lands in another one's cache,
    so the two recordsets are walked side by side.
    """
    for record, twin in zip(records, plain):
        record.display_name = twin.display_name


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _compute_display_name(self):
        plain = self.with_context(display_default_code=False)
        super(ProductTemplate, plain)._compute_display_name()
        _copy_plain_names(self, plain)


class ProductTemplateAttributeValue(models.Model):
    _inherit = "product.template.attribute.value"

    def _get_combination_name(self):
        # Odoo appends «(65 гр)» to a variant's name only when its template
        # has several variants, so half the lines of an order carried the
        # characteristic in the name and half did not — while every document
        # already has its own «Xarakteristika» column.  The name stays plain.
        if self.env.context.get("cst_plain_variant_name"):
            return ""
        return super()._get_combination_name()


class ProductProduct(models.Model):
    _inherit = "product.product"

    # stated again so the dropdown flavour can never land in the plain cache
    @api.depends_context("display_default_code", "seller_id", "company_id",
                         "partner_id", "formatted_display_name", "lang")
    def _compute_display_name(self):
        plain = self.with_context(display_default_code=False, cst_plain_variant_name=True)
        super(ProductProduct, plain)._compute_display_name()
        _copy_plain_names(self, plain)
        if self.env.context.get("formatted_display_name"):
            # the many2one dropdown asks for this flavour: there the variants of
            # one product must still be told apart, so the characteristic is
            # added as the muted «--…--» suffix Odoo uses for codes
            for product in self:
                values = product.product_template_attribute_value_ids.mapped("name")
                if values and product.display_name:
                    product.display_name = "%s\t--%s--" % (
                        product.display_name, ", ".join(values))
