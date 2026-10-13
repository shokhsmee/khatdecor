from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    cst_production_id = fields.Many2one(
        "mrp.production", string="Ishlab chiqarish buyurtmasi", index="btree_not_null", copy=False,
        readonly=True, help="Bu ko'chirish shu buyurtma uchun avtomatik yaratilgan.")
    cst_flow_kind = fields.Selection([
        ("supply", "Xomashyo so'rovi"),
        ("output", "Tayyor mahsulot"),
    ], string="Ko'chirish turi", copy=False, readonly=True)
    # one label for every internal document, hand-made ones included, so the
    # warehouse can tell «came out of production» from an ordinary transfer
    cst_move_kind = fields.Selection([
        ("output", "Ishlab chiqarishdan"),
        ("supply", "Xomashyo so'rovi"),
        ("transfer", "Ko'chirish"),
    ], string="Turi", compute="_compute_cst_move_kind", store=True, index=True)

    @api.depends("cst_flow_kind", "picking_type_id.code")
    def _compute_cst_move_kind(self):
        for picking in self:
            if picking.cst_flow_kind:
                picking.cst_move_kind = picking.cst_flow_kind
            elif picking.picking_type_id.code == "internal":
                picking.cst_move_kind = "transfer"
            else:
                picking.cst_move_kind = False

    @api.model
    def _cst_default_receiver(self, location_dest_id, picking_type_id):
        picking_type = self.env["stock.picking.type"].browse(picking_type_id)
        location = self.env["stock.location"].browse(location_dest_id) if location_dest_id else \
            picking_type.default_location_dest_id
        return location.warehouse_id.cst_receiver_id

    @api.model_create_multi
    def create(self, vals_list):
        # the receiving warehouse names who takes delivery, unless the document already says
        for vals in vals_list:
            if vals.get("cst_receiver_id") or not vals.get("picking_type_id"):
                continue
            picking_type = self.env["stock.picking.type"].browse(vals["picking_type_id"])
            if picking_type.code != "internal":
                continue
            receiver = self._cst_default_receiver(vals.get("location_dest_id"), picking_type.id)
            if receiver:
                vals["cst_receiver_id"] = receiver.id
        return super().create(vals_list)

    @api.onchange("location_dest_id", "picking_type_id")
    def _onchange_cst_flow_receiver(self):
        if self.picking_type_code == "internal" and not self.cst_receiver_id:
            receiver = self.location_dest_id.warehouse_id.cst_receiver_id
            if receiver:
                self.cst_receiver_id = receiver


class StockMove(models.Model):
    _inherit = "stock.move"

    cst_supply_production_id = fields.Many2one(
        "mrp.production", string="Xomashyo so'rovi (buyurtma)", index="btree_not_null", copy=False, readonly=True)
    cst_forward_production_id = fields.Many2one(
        "mrp.production", string="Tayyor mahsulot (buyurtma)", index="btree_not_null", copy=False, readonly=True)
