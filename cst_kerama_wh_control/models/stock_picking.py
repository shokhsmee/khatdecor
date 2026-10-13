from odoo import _, api, fields, models
from odoo.exceptions import UserError


def is_wh_supervisor(env):
    """A supervisor may validate without a photo and on someone else's behalf."""
    return bool(
        env.context.get("cst_skip_wh_control")
        or env.user.has_group("cst_kerama_wh_control.group_wh_supervisor")
    )


class StockPicking(models.Model):
    _inherit = "stock.picking"

    cst_photo_ids = fields.Many2many(
        "ir.attachment", "cst_picking_photo_rel", "picking_id", "attachment_id",
        string="Photos", copy=False,
        help="Photographic proof of the goods. Required to validate a receipt.")
    cst_photo_count = fields.Integer(compute="_compute_cst_photo_count")
    cst_photo_required = fields.Boolean(compute="_compute_cst_flags")
    cst_receiver_required = fields.Boolean(compute="_compute_cst_flags")
    cst_receiver_id = fields.Many2one(
        "res.users", string="Receiver", copy=False, tracking=True,
        domain=[("share", "=", False)],
        help="Who takes delivery of this internal transfer. Only this person "
             "(or a warehouse supervisor) can validate it.")
    cst_all_picked = fields.Boolean(
        string="Ready to Validate", compute="_compute_cst_all_picked",
        help="Every line of this transfer has been confirmed.")

    cst_transport_visible = fields.Boolean(compute="_compute_cst_flags")
    cst_driver = fields.Char(
        string="Driver", copy=False,
        help="Who drove the goods in or out.")
    cst_car_model = fields.Char(
        string="Car Model", copy=False,
        help="Model of the vehicle that carried the goods.")
    cst_car_number = fields.Char(
        string="Car Number", copy=False,
        help="Plate number of the vehicle that carried the goods.")

    cst_line_photo_ids = fields.Many2many(
        "ir.attachment", string="Line Photos", compute="_compute_cst_photo_count",
        help="Photos taken on the individual lines, e.g. from the Barcode app.")
    cst_has_photo = fields.Boolean(compute="_compute_cst_photo_count")

    @api.depends("cst_photo_ids", "move_line_ids.cst_photo_ids")
    def _compute_cst_photo_count(self):
        for picking in self:
            line_photos = picking.move_line_ids.cst_photo_ids
            picking.cst_line_photo_ids = line_photos
            picking.cst_photo_count = len(picking.cst_photo_ids) + len(line_photos)
            picking.cst_has_photo = bool(picking.cst_photo_ids or line_photos)

    @api.depends("picking_type_code")
    def _compute_cst_flags(self):
        for picking in self:
            picking.cst_photo_required = picking.picking_type_code == "incoming"
            picking.cst_receiver_required = picking.picking_type_code == "internal"
            # receipts and deliveries move on a vehicle, internal transfers do not
            picking.cst_transport_visible = picking.picking_type_code in (
                "incoming", "outgoing")

    @api.depends("state", "move_ids.picked", "move_ids.state")
    def _compute_cst_all_picked(self):
        for picking in self:
            moves = picking.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
            picking.cst_all_picked = bool(moves) \
                and picking.state not in ("done", "cancel", "draft") \
                and all(move.picked for move in moves)

    # ------------------------------------------------------------------
    #  Rules
    # ------------------------------------------------------------------
    def _cst_check_wh_rules(self):
        """Photo on receipts; named receiver on internal transfers."""
        if is_wh_supervisor(self.env):
            return
        for picking in self:
            if picking.picking_type_code == "incoming" and not picking.cst_has_photo:
                raise UserError(_(
                    "Attach a photo of the goods before validating receipt %s.\n\n"
                    "Use the Photos tab on the transfer, or the camera button on "
                    "a line in the Barcode app.", picking.name))
            if picking.picking_type_code == "internal":
                if not picking.cst_receiver_id:
                    raise UserError(_(
                        "Set the Receiver on internal transfer %s before validating.",
                        picking.name))
                if picking.cst_receiver_id != self.env.user:
                    raise UserError(_(
                        "Only %(receiver)s can validate transfer %(name)s.\n\n"
                        "You are signed in as %(user)s.",
                        receiver=picking.cst_receiver_id.name,
                        name=picking.name,
                        user=self.env.user.name))

    def _cst_autofill_incoming(self):
        """A validated receipt must actually put the goods in the warehouse:
        when nothing was entered by hand, take the full demanded quantity."""
        for picking in self:
            if picking.picking_type_code != "incoming":
                continue
            moves = picking.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
            if not moves or any(moves.mapped("picked")):
                continue  # the user entered quantities: respect them
            for move in moves:
                move.quantity = move.product_uom_qty
                move.picked = True

    def button_validate(self):
        self._cst_check_wh_rules()
        self._cst_autofill_incoming()
        return super().button_validate()
