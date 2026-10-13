"""2-sort (second grade) products.

The shop's press turns out boards that are sellable but not first grade. The
client wants them counted as a product of their own -- sellable, never bought,
kept out of the ordinary product and stock lists and reached from the scrap
area instead -- while the first-grade product shows how much of its 2-sort
twin is lying in the warehouse.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    cst_is_second_grade = fields.Boolean(
        string="2-sort mahsulot", index=True,
        help="Asosiy mahsulotning 2-sort (brak toifasi) egizagi. Mahsulotlar va ombor "
             "ro'yxatlarida ko'rinmaydi, brak bo'limidagi «2-sort mahsulotlar» menyusidan "
             "ochiladi; sotiladi, xarid qilinmaydi.")
    cst_grade_tmpl_of_id = fields.Many2one(
        "product.template", string="Asosiy mahsulot (shablon)", index="btree_not_null", ondelete="set null",
        help="Bu 2-sort shablon qaysi asosiy mahsulotning variantlari uchun.")

    def _cst_ensure_values(self, ptavs):
        """Give this 2-sort template the attribute values of a first-grade variant."""
        self.ensure_one()
        for ptav in ptavs:
            line = self.attribute_line_ids.filtered(lambda l: l.attribute_id == ptav.attribute_id)
            value = ptav.product_attribute_value_id
            if not line:
                self.attribute_line_ids = [(0, 0, {"attribute_id": ptav.attribute_id.id,
                                                   "value_ids": [(6, 0, value.ids)]})]
            elif value not in line.value_ids:
                line.value_ids = [(4, value.id)]


class ProductProduct(models.Model):
    _inherit = "product.product"

    cst_is_second_grade = fields.Boolean(related="product_tmpl_id.cst_is_second_grade", store=True)
    cst_grade_of_id = fields.Many2one(
        "product.product", string="Asosiy mahsuloti", index="btree_not_null", ondelete="restrict",
        help="Bu 2-sort mahsulot qaysi asosiy mahsulot (variant)ning egizagi.")
    cst_second_grade_id = fields.Many2one(
        "product.product", string="2-sort egizagi", compute="_compute_cst_second_grade",
        help="Shu variantning 2-sort mahsuloti, bo'lsa.")
    cst_second_grade_qty = fields.Float(
        string="2-sort qoldig'i", compute="_compute_cst_second_grade", digits="Product Unit of Measure",
        help="Egizak 2-sort mahsulotning ombordagi miqdori (scrap qiymati).")
    cst_second_grade_value = fields.Monetary(
        string="2-sort qiymati", compute="_compute_cst_second_grade",
        currency_field="cst_grade_currency_id",
        help="Egizak 2-sort mahsulot qoldig'ining tannarx bo'yicha qiymati.")
    cst_grade_currency_id = fields.Many2one(
        "res.currency", compute="_compute_cst_second_grade")

    @api.depends("cst_is_second_grade")
    def _compute_cst_second_grade(self):
        twins = {}
        mains = self.filtered(lambda p: not p.cst_is_second_grade)
        if mains:
            for twin in self.search([("cst_grade_of_id", "in", mains.ids), ("cst_is_second_grade", "=", True)]):
                twins.setdefault(twin.cst_grade_of_id.id, twin)
        for product in self:
            twin = twins.get(product.id)
            company = product.company_id or self.env.company
            product.cst_grade_currency_id = company.currency_id
            product.cst_second_grade_id = twin
            product.cst_second_grade_qty = twin.qty_available if twin else 0.0
            product.cst_second_grade_value = (
                twin.qty_available * twin.with_company(company).standard_price) if twin else 0.0

    def cst_get_or_create_second_grade(self):
        """The 2-sort twin of this variant, created on first use.

        A variant with a characteristic gets its twin as a variant of the same
        characteristic: all variants of one product share one «<product> — 2-sort»
        template carrying the same attribute, so the characteristic shows in its
        own column (and filters) like on any other product. A product without
        attributes gets a plain «<product> — 2-sort» product.
        """
        self.ensure_one()
        if self.cst_is_second_grade:
            return self
        twin = self.cst_second_grade_id
        if twin:
            return twin
        main = self
        company = main.company_id or self.env.company
        ptavs = main.product_template_attribute_value_ids
        if ptavs:
            twin_tmpl = main._cst_second_grade_template()
            twin_tmpl._cst_ensure_values(ptavs)
            wanted = ptavs.product_attribute_value_id
            twin = twin_tmpl.with_context(active_test=False).product_variant_ids.filtered(
                lambda v: v.product_template_attribute_value_ids.product_attribute_value_id == wanted)[:1]
            if not twin:
                raise UserError(_("%s uchun 2-sort variantini yaratib bo'lmadi.", main.display_name))
            if not twin.active:
                twin.active = True
        else:
            twin = self.env["product.template"].create(
                main._cst_second_grade_template_values()).product_variant_id
        vals = {"cst_grade_of_id": main.id}
        if main.default_code:
            code = "%s-2S" % main.default_code
            holder = self.with_context(active_test=False).search([("default_code", "=", code), ("id", "!=", twin.id)])
            # an archived old-style twin hands its code over; any other holder keeps it
            holder.filtered(lambda p: not p.active and p.cst_is_second_grade).write({"default_code": False})
            if not holder.filtered(lambda p: p.active or not p.cst_is_second_grade):
                vals["default_code"] = code
        twin.write(vals)
        twin.with_company(company).standard_price = main.with_company(company).standard_price
        self.invalidate_recordset(["cst_second_grade_id", "cst_second_grade_qty", "cst_second_grade_value"])
        return twin

    def _cst_second_grade_template_values(self):
        template = self.product_tmpl_id
        return {
            "name": _("%s — 2-sort", template.name),
            "cst_is_second_grade": True,
            "cst_grade_tmpl_of_id": template.id,
            "sale_ok": True,
            "purchase_ok": False,
            "type": template.type,
            "is_storable": True,
            "categ_id": template.categ_id.id,
            "uom_id": template.uom_id.id,
            "list_price": template.list_price,
            "company_id": template.company_id.id,
            "taxes_id": [(6, 0, template.taxes_id.ids)],
        }

    def _cst_second_grade_template(self):
        """The shared 2-sort template of this variant's product (with attributes)."""
        self.ensure_one()
        template = self.product_tmpl_id
        Template = self.env["product.template"].with_context(active_test=False)
        twin_tmpl = Template.search([("cst_grade_tmpl_of_id", "=", template.id),
                                     ("cst_is_second_grade", "=", True),
                                     ("attribute_line_ids", "!=", False)], order="active desc, id", limit=1)
        if twin_tmpl:
            if not twin_tmpl.active:
                twin_tmpl.active = True
            return twin_tmpl
        vals = self._cst_second_grade_template_values()
        vals["attribute_line_ids"] = [
            (0, 0, {"attribute_id": ptav.attribute_id.id,
                    "value_ids": [(6, 0, ptav.product_attribute_value_id.ids)]})
            for ptav in self.product_template_attribute_value_ids]
        return Template.create(vals)

    def action_cst_open_second_grade(self):
        """Open (creating if needed) this variant's 2-sort twin."""
        self.ensure_one()
        twin = self.cst_get_or_create_second_grade()
        return {
            "type": "ir.actions.act_window", "res_model": "product.product",
            "res_id": twin.id, "view_mode": "form", "target": "current",
        }
