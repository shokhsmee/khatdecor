from odoo import api, fields, models


class StockPicking(models.Model):
    """Who unloaded the wagon is known only at the dock, so it is recorded on
    the document that brought the goods in."""

    _inherit = "stock.picking"

    cst_unloader_ids = fields.One2many(
        "cst.picking.unloader", "picking_id", string="Yuk tushirish",
        copy=False)
    cst_unload_total = fields.Monetary(
        string="Jami", compute="_compute_cst_unload_total",
        currency_field="cst_currency_id")
    cst_currency_id = fields.Many2one(related="company_id.currency_id")
    cst_unload_visible = fields.Boolean(compute="_compute_cst_unload_visible")

    @api.depends("cst_unloader_ids.amount")
    def _compute_cst_unload_total(self):
        for picking in self:
            picking.cst_unload_total = sum(picking.cst_unloader_ids.mapped("amount"))

    @api.depends("picking_type_code")
    def _compute_cst_unload_visible(self):
        for picking in self:
            # Goods are carried, and therefore unloaded, on the way in and on
            # the way out.  An internal transfer moves nothing off a vehicle.
            picking.cst_unload_visible = picking.picking_type_code in (
                "incoming", "outgoing")
