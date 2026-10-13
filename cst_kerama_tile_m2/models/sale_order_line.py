import math

from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    tile_height = fields.Float(
        string="Tile Height (cm)",
        related="product_id.tile_height",
        readonly=True,
    )
    tile_width = fields.Float(
        string="Tile Width (cm)",
        related="product_id.tile_width",
        readonly=True,
    )
    tile_area = fields.Float(
        string="Area per piece (m²)",
        related="product_id.tile_area",
        readonly=True,
    )
    is_sqm_uom = fields.Boolean(
        related="product_id.is_sqm_uom",
        readonly=True,
    )

    m2_required = fields.Float(
        string="m² Needed",
        digits="Product Unit",
        help="Square meters the customer asks for. The number of whole tiles is "
        "rounded up from this, and that whole-tile area is what gets sold.",
    )
    tile_qty = fields.Integer(
        string="Pieces",
        compute="_compute_tile_qty",
        store=True,
        readonly=True,
        help="Number of whole tiles (kafel) to hand over, always rounded up so "
        "you never sell a fraction of a tile.",
    )

    @api.depends("m2_required", "tile_area")
    def _compute_tile_qty(self):
        for line in self:
            if line.m2_required > 0 and line.tile_area > 0:
                line.tile_qty = math.ceil(line.m2_required / line.tile_area)
            else:
                line.tile_qty = 0

    @api.onchange("m2_required")
    def _onchange_m2_required(self):
        """Turn the requested m² into whole tiles and bill that real area."""
        for line in self:
            if line.tile_area > 0 and line.m2_required > 0:
                pieces = math.ceil(line.m2_required / line.tile_area)
                line.product_uom_qty = pieces * line.tile_area
