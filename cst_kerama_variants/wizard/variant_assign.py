from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CstVariantAssignWizard(models.TransientModel):
    """«Xarakteristika biriktirish» — give existing products their attributes
    without losing them.

    For every selected product the wizard first adds each attribute with the
    *one* value the physical product on the shelf carries. Odoo writes a
    single-value line straight onto the existing variant, so the product keeps
    its id, code, barcode, stock and history and simply becomes, say,
    «Глянцевый · 70 гр · 183 см, 277 см». Only then are the other values the
    product comes in added to the lines — and in instant mode each of them is a
    variant of its own from that moment, one line each in every list.
    """

    _name = "cst.variant.assign.wizard"
    _description = "Xarakteristika biriktirish"

    product_tmpl_ids = fields.Many2many(
        "product.template", string="Mahsulotlar", required=True,
        default=lambda self: self._default_templates())

    surface_id = fields.Many2one(
        "product.attribute.value", string="Ustki qismi (hozirgi)",
        domain=lambda self: self._value_domain("attribute_surface"))
    surface_extra_ids = fields.Many2many(
        "product.attribute.value", "cst_va_surface_extra_rel", string="Boshqa ustki qismlari",
        domain=lambda self: self._value_domain("attribute_surface"))
    density_id = fields.Many2one(
        "product.attribute.value", string="Zichligi (hozirgi)",
        domain=lambda self: self._value_domain("attribute_density"))
    density_extra_ids = fields.Many2many(
        "product.attribute.value", "cst_va_density_extra_rel", string="Boshqa zichliklari",
        domain=lambda self: self._value_domain("attribute_density"))
    size_id = fields.Many2one(
        "product.attribute.value", string="Uzunligi va eni (hozirgi)",
        domain=lambda self: self._value_domain("attribute_size"))
    size_extra_ids = fields.Many2many(
        "product.attribute.value", "cst_va_size_extra_rel", string="Boshqa o'lchamlari",
        domain=lambda self: self._value_domain("attribute_size"))

    summary = fields.Text(string="Natija", readonly=True)

    # ------------------------------------------------------------------
    @api.model
    def _default_templates(self):
        if self.env.context.get("active_model") == "product.template":
            return self.env.context.get("active_ids", [])
        if self.env.context.get("active_model") == "product.product":
            return self.env["product.product"].browse(
                self.env.context.get("active_ids", [])).product_tmpl_id.ids
        return []

    @api.model
    def _value_domain(self, attribute_xmlid):
        attribute = self.env.ref("cst_kerama_variants.%s" % attribute_xmlid, raise_if_not_found=False)
        return [("attribute_id", "=", attribute.id)] if attribute else []

    def _attribute_plan(self):
        """[(attribute, current value or empty, extra values)] for the three attributes."""
        plan = []
        for xmlid, current, extra in (
                ("attribute_surface", self.surface_id, self.surface_extra_ids),
                ("attribute_density", self.density_id, self.density_extra_ids),
                ("attribute_size", self.size_id, self.size_extra_ids)):
            attribute = self.env.ref("cst_kerama_variants.%s" % xmlid)
            if current or extra:
                plan.append((attribute, current, extra - current))
        return plan

    # ------------------------------------------------------------------
    def action_apply(self):
        self.ensure_one()
        plan = self._attribute_plan()
        if not plan:
            raise UserError(_("Hech bo'lmaganda bitta xarakteristika qiymatini tanlang."))
        Line = self.env["product.template.attribute.line"]
        report = []
        for template in self.product_tmpl_ids:
            before = template.with_context(active_test=False).product_variant_ids
            single = len(before.filtered("active")) == 1 and not before.filtered("active").product_template_attribute_value_ids

            # 1. the existing product becomes the current combination
            #    (single-value lines are written onto it, nothing is archived)
            for attribute, current, _extra in plan:
                line = template.attribute_line_ids.filtered(lambda l: l.attribute_id == attribute)
                if line:
                    continue  # already characterised on this axis; only widen below
                if not current:
                    continue  # no current value given: the axis is added below as extra only
                Line.create({"product_tmpl_id": template.id, "attribute_id": attribute.id,
                             "value_ids": [(6, 0, current.ids)]})
            self.env.flush_all()

            # 2. widen every axis with the other values the product comes in
            for attribute, current, extra in plan:
                values = extra | current if not template.attribute_line_ids.filtered(
                    lambda l: l.attribute_id == attribute) else extra
                if not values:
                    continue
                line = template.attribute_line_ids.filtered(lambda l: l.attribute_id == attribute)
                if line:
                    missing = values - line.value_ids
                    if missing:
                        line.write({"value_ids": [(4, v.id) for v in missing]})
                else:
                    Line.create({"product_tmpl_id": template.id, "attribute_id": attribute.id,
                                 "value_ids": [(6, 0, values.ids)]})
            self.env.flush_all()

            after = template.with_context(active_test=False).product_variant_ids
            kept = before & after.filtered("active")
            lost = before.filtered("active") - after.filtered("active")
            if lost:
                raise UserError(_(
                    "«%s»: mavjud mahsulot arxivga tushib qolardi — bekor qilindi. "
                    "Har uch xarakteristika uchun «hozirgi» qiymatni ko'rsating.",
                    template.display_name))
            report.append("%s → %s | variantlar: %d (yangi %d)%s" % (
                template.name, ", ".join(kept[:1].product_template_attribute_value_ids.mapped("name")) or "—",
                len(after.filtered("active")), len(after.filtered("active") - before),
                "" if single else " (avval ham variantli edi)"))
        self.summary = "\n".join(report)
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
            "view_mode": "form", "target": "new", "name": _("Xarakteristika biriktirish — natija"),
        }
