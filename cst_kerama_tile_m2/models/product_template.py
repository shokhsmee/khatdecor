from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    tile_height = fields.Float(
        string="Tile Height (cm)",
        digits="Product Unit",
        help="Height of a single tile (kafel) in centimeters.",
    )
    tile_width = fields.Float(
        string="Tile Width (cm)",
        digits="Product Unit",
        help="Width of a single tile (kafel) in centimeters.",
    )
    tile_area = fields.Float(
        string="Area per piece (m²)",
        compute="_compute_tile_area",
        store=True,
        digits="Product Unit",
        help="Surface area of a single tile, computed as height × width / 10000.",
    )
    is_sqm_uom = fields.Boolean(
        string="Sold by m²",
        compute="_compute_is_sqm_uom",
        help="Technical field: True when the sales unit of measure is square meter.",
    )

    @api.depends("tile_height", "tile_width")
    def _compute_tile_area(self):
        for product in self:
            product.tile_area = (product.tile_height * product.tile_width) / 10000.0

    @api.depends("uom_id")
    def _compute_is_sqm_uom(self):
        sqm = self.env.ref(
            "uom.product_uom_square_meter", raise_if_not_found=False
        )
        for product in self:
            product.is_sqm_uom = bool(sqm) and product.uom_id == sqm
