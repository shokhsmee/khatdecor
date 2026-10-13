"""Instant variants, and one line per characteristic.

Two products had two «Ustki qismi» lines each, both written onto their one
variant («Глянцевый, Древесный» on a single product). Fold them, then switch
the three characteristics to instant creation so every listed value is a
variant of its own -- the mode the storekeepers asked for when they saw one
line where they expected two. The 19.0.2 migration that put the attributes
back to dynamic is superseded by this one.
"""
import logging

_logger = logging.getLogger(__name__)

XMLIDS = (
    "cst_kerama_variants.attribute_surface",
    "cst_kerama_variants.attribute_density",
    "cst_kerama_variants.attribute_size",
)


def migrate(cr, version):
    if not version:
        return
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    templates = env["product.template"].with_context(active_test=False).search(
        [("attribute_line_ids", "!=", False)])
    for template, kept, folded in templates._cst_merge_duplicate_attribute_lines():
        _logger.info("folded %s: kept %s, split off %s", template.display_name, kept, folded)
    attributes = env["product.attribute"]
    for xmlid in XMLIDS:
        attribute = env.ref(xmlid, raise_if_not_found=False)
        if attribute:
            attributes |= attribute
    recomputed = attributes._cst_force_create_variant("always")
    _logger.info("instant variants on; %s products recomputed", len(recomputed))
