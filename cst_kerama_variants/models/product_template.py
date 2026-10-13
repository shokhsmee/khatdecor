"""One line per characteristic on a product, and instant variants.

Odoo 19 lets a template carry two attribute lines for the same attribute. Both
single-value lines are then written onto the one existing variant, which comes
out as «Глянцевый, Древесный» on a single product instead of two products.
The constraint below refuses that door from now on; the repair method folds
the lines of templates that already went through it; the attribute helper
switches the creation mode for attributes that products already use, which
Odoo's own ``write`` refuses.
"""
import logging
from collections import defaultdict

from odoo import Command, _, api, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ProductTemplateAttributeLine(models.Model):
    _inherit = "product.template.attribute.line"

    @api.constrains("attribute_id", "product_tmpl_id", "active")
    def _cst_check_one_line_per_attribute(self):
        for line in self.filtered("active"):
            twin = self.search_count([
                ("id", "!=", line.id), ("active", "=", True),
                ("product_tmpl_id", "=", line.product_tmpl_id.id),
                ("attribute_id", "=", line.attribute_id.id),
            ])
            if twin:
                raise ValidationError(_(
                    "«%(product)s» already has a «%(attribute)s» line. Add the value to "
                    "that line instead of a second one: a variant carries one value per "
                    "characteristic, and a second line would put two values on one product.",
                    product=line.product_tmpl_id.display_name,
                    attribute=line.attribute_id.display_name))


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _cst_merge_duplicate_attribute_lines(self):
        """Fold several lines of one attribute into the first of them.

        The first line (lowest id -- the one the storekeeper created first, the
        «hozirgi» value) keeps the existing variant, its id, stock and history.
        The other lines' values become further values of that line, and so
        variants of their own; the extra lines are removed.

        Returns ``[(template, kept value names, folded value names)]``.
        """
        report = []
        Ptal = self.env["product.template.attribute.line"]
        for template in self.with_context(active_test=False):
            grouped = defaultdict(lambda: Ptal)
            for line in template.attribute_line_ids.filtered("active").sorted("id"):
                grouped[line.attribute_id] |= line
            for attribute, lines in grouped.items():
                if len(lines) < 2:
                    continue
                keep, extras = lines[0], lines[1:]
                # read before widening: afterwards the line sorts its values by
                # sequence and the shelf value may no longer come first
                kept_names = keep.value_ids.mapped("name")
                folded = extras.value_ids - keep.value_ids
                extra_ptavs = extras.product_template_value_ids
                # 1. a variant carries one value per attribute: let go of the extras'
                variants = template.with_context(active_test=False).product_variant_ids
                for variant in variants:
                    dropping = variant.product_template_attribute_value_ids & extra_ptavs
                    if dropping:
                        variant.write({"product_template_attribute_value_ids": [
                            Command.unlink(ptav.id) for ptav in dropping]})
                # 2. nothing references the extra lines' values any more: remove them
                #    (Odoo recomputes the variants; the kept line is still single-value,
                #    so the existing variant stays exactly as it is)
                extras.unlink()
                # 3. the folded values join the surviving line -- in instant mode each
                #    becomes a variant of its own right here
                if folded:
                    keep.write({"value_ids": [Command.link(v.id) for v in folded]})
                report.append((template, kept_names, folded.mapped("name")))
                _logger.info("%s: %s lines of %s folded into one; kept %s, added %s",
                             template.display_name, len(lines), attribute.name,
                             ", ".join(kept_names), ", ".join(folded.mapped("name")) or "-")
        return report


class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    def _cst_force_create_variant(self, mode):
        """Set the creation mode even on attributes that products already use.

        Odoo's ``write`` refuses the change because the existing combinations
        would be left stale; the point of refusing is the recomputation, not the
        change. So the mode is set in SQL and every template using the
        attribute recomputes its variants right after -- affordable while a
        handful of products carry characteristics. Returns those templates.
        """
        changed = self.filtered(lambda a: a.create_variant != mode)
        if not changed:
            return self.env["product.template"]
        self.env.cr.execute(
            "UPDATE product_attribute SET create_variant = %s WHERE id = ANY(%s)",
            (mode, changed.ids))
        self.env.invalidate_all()
        templates = changed.with_context(active_test=False).product_tmpl_ids
        templates._create_variant_ids()
        _logger.info("%s -> %s; %s products recomputed",
                     ", ".join(changed.mapped("name")), mode, len(templates))
        return templates
