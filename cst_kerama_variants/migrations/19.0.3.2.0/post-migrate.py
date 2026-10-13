"""2-sort twins become variants of a shared «<product> — 2-sort» template.

Old twins were plain products with the characteristic written into the name.
Those whose first-grade product has a characteristic and nothing in stock are
archived (their history stays); the next 2-sort of that variant creates the
proper variant twin. Twins still holding stock are left alone and logged.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    twins = env["product.product"].search([
        ("cst_is_second_grade", "=", True), ("cst_grade_of_id", "!=", False),
        ("product_tmpl_id.attribute_line_ids", "=", False)])
    for twin in twins:
        main = twin.cst_grade_of_id
        if not main.product_template_attribute_value_ids:
            continue
        if twin.qty_available:
            _logger.warning("2-sort %s (id %s) still holds %s — left as it is",
                            twin.display_name, twin.id, twin.qty_available)
            continue
        twin.product_tmpl_id.active = False
        _logger.info("2-sort %s (id %s) archived; its variant twin is created on next use",
                     twin.display_name, twin.id)
