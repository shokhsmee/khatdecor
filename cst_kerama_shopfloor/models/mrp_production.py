"""What the Shop Floor card shows about an order: which sale order it serves.

The 2-sort / brak counters and the booking of what the floor typed live with
the shifts, in ``cst_kerama_shift``.
"""
import re

from odoo import _, api, fields, models


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    cst_sale_ref = fields.Char(
        string="Sotuv buyurtmasi", compute="_compute_cst_sale_ref",
        help="Bu buyurtma qaysi sotuv buyurtmasi(lari) uchun: sotuv qatori, "
             "loyihaning sotuvlari yoki manba matnidagi raqam bo'yicha.")

    @api.depends("sale_line_id", "origin", "reference_ids")
    def _compute_cst_sale_ref(self):
        SaleOrder = self.env["sale.order"].sudo()
        token_re = re.compile(r"[\s,;/|]+")
        for mo in self:
            orders = mo.sale_line_id.order_id
            references = getattr(mo, "reference_ids", None)
            if references is not None:
                orders |= getattr(references, "sale_ids", SaleOrder.browse())
            project = getattr(mo, "project_id", None)
            if not orders and project:
                orders = SaleOrder.search([("project_id", "=", project.id), ("state", "=", "sale")], limit=5)
            if not orders and mo.origin:
                tokens = [t for t in token_re.split(mo.origin) if t]
                if tokens:
                    orders = SaleOrder.search([("name", "in", tokens)], limit=5)
            names = orders.sorted("id").mapped("name")
            mo.cst_sale_ref = ", ".join(names[:3]) + (" …" if len(names) > 3 else "")
