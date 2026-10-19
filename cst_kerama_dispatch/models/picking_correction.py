from odoo import _, api, fields, models
from odoo.exceptions import UserError

GROUP_CORRECTION = "cst_kerama_shift.group_doc_correction"


class StockPicking(models.Model):
    _inherit = "stock.picking"

    cst_correction_of_id = fields.Many2one(
        "stock.picking", string="Tuzatilgan hujjat", copy=False, readonly=True, index="btree_not_null",
        help="Bu ko'chirish shu bajarilgan hujjatdagi miqdor xatosini tuzatish uchun yaratilgan.")
    cst_correction_ids = fields.One2many("stock.picking", "cst_correction_of_id", string="Tuzatishlar")
    cst_correction_log = fields.Text(string="Tuzatishlar tarixi", copy=False, readonly=True)
    cst_can_correct = fields.Boolean(compute="_compute_cst_can_correct")

    @api.depends_context("uid")
    @api.depends("state", "picking_type_code")
    def _compute_cst_can_correct(self):
        allowed = self.env.user.has_group(GROUP_CORRECTION)
        for picking in self:
            picking.cst_can_correct = allowed and picking._cst_correctable()

    def _cst_effective_qty(self, move):
        """What really moved for ``move``'s product: the done quantity plus
        what earlier corrections sent on, minus what they brought back."""
        self.ensure_one()
        qty = move.quantity
        for fix in self.cst_correction_ids.filtered(lambda p: p.state == "done"):
            sign = -1 if fix.location_id == self.location_dest_id else 1
            for other in fix.move_ids.filtered(lambda m: m.state == "done" and m.product_id == move.product_id):
                qty += sign * other.product_uom._compute_quantity(other.quantity, move.product_uom)
        return qty

    def _cst_correctable(self):
        self.ensure_one()
        return (self.state == "done" and self.picking_type_code == "internal"
                and not self.cst_final_location_id and not self.cst_ic_origin_id and not self.cst_ic_receipt_id)

    def action_cst_open_correction(self):
        self.ensure_one()
        if not self.env.user.has_group(GROUP_CORRECTION):
            raise UserError(_("Bajarilgan hujjatni faqat administrator yoki rahbar tuzatadi."))
        if not self._cst_correctable():
            raise UserError(_("Faqat bajarilgan ichki ko'chirish tuzatiladi (kompaniyalararo emas)."))
        return {
            "type": "ir.actions.act_window", "name": _("Ko'chirishni tuzatish: %s", self.name),
            "res_model": "cst.picking.correction", "view_mode": "form", "target": "new",
            "context": {"default_picking_id": self.id},
        }


class CstPickingCorrection(models.TransientModel):
    """«Tuzatish» of a done internal transfer (648 typed instead of 650).

    The done transfer is not touched: the difference is a second document --
    a return of the surplus, or a new transfer of the shortfall -- validated at
    once and linked to the original, with the old and new numbers, the user
    and the reason in its chatter. Quants and the stock reports follow the
    documents like any other move.
    """

    _name = "cst.picking.correction"
    _description = "Ichki ko'chirishni tuzatish"

    picking_id = fields.Many2one("stock.picking", string="Hujjat", required=True, readonly=True)
    line_ids = fields.One2many("cst.picking.correction.line", "wizard_id", string="Mahsulotlar")
    reason = fields.Text(string="Sabab", required=True)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        picking = self.env["stock.picking"].browse(values.get("picking_id") or self.env.context.get("default_picking_id"))
        if picking:
            rows = []
            for move in picking.move_ids.filtered(lambda m: m.state == "done"):
                current = picking._cst_effective_qty(move)
                rows.append((0, 0, {"move_id": move.id, "old_qty": current, "new_qty": current}))
            values["line_ids"] = rows
        return values

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group(GROUP_CORRECTION):
            raise UserError(_("Bajarilgan hujjatni faqat administrator yoki rahbar tuzatadi."))
        picking = self.picking_id.sudo()
        if not picking._cst_correctable():
            raise UserError(_("Faqat bajarilgan ichki ko'chirish tuzatiladi (kompaniyalararo emas)."))
        if not (self.reason or "").strip():
            raise UserError(_("Tuzatish sababini yozing."))
        less, more, changes = {}, {}, []
        for line in self.line_ids:
            move = line.move_id.sudo()
            if line.new_qty < 0:
                raise UserError(_("Miqdor manfiy bo'lishi mumkin emas."))
            current = picking._cst_effective_qty(move)
            diff = line.new_qty - current
            if move.product_uom.compare(diff, 0.0) == 0:
                continue
            (more if diff > 0 else less)[move] = abs(diff)
            changes.append("%s: %g → %g %s" % (move.product_id.display_name, current, line.new_qty,
                                                move.product_uom.name))
        if not changes:
            raise UserError(_("Miqdorlar o'zgarmadi."))
        created = self.env["stock.picking"].sudo()
        if less:
            created |= self._cst_return_less(picking, less)
        if more:
            created |= self._cst_send_more(picking, more)
        stamp = fields.Datetime.context_timestamp(self, fields.Datetime.now()).strftime("%d.%m.%Y %H:%M")
        log = "%s · %s · %s. Sabab: %s (%s)" % (stamp, self.env.user.name, "; ".join(changes), self.reason.strip(),
                                                ", ".join(created.mapped("name")))
        picking.write({"cst_correction_log": "\n".join(filter(None, [picking.cst_correction_log, log]))})
        body = _("Tuzatildi: %(changes)s. Sabab: %(reason)s. Hujjat: %(docs)s",
                 changes="; ".join(changes), reason=self.reason.strip(), docs=", ".join(created.mapped("name")))
        picking.message_post(body=body)
        for doc in created:
            doc.message_post(body=_("%(orig)s tuzatishi. Sabab: %(reason)s", orig=picking.name,
                                    reason=self.reason.strip()))
        return {"type": "ir.actions.act_window_close"}

    def _cst_validate(self, picking):
        for move in picking.move_ids:
            if move.product_uom.compare(move.quantity, move.product_uom_qty) < 0:
                raise UserError(_(
                    "%(product)s: %(loc)s joyida tuzatish uchun yetarli qoldiq yo'q (kerak %(need)s, bor %(have)s).",
                    product=move.product_id.display_name, loc=move.location_id.display_name,
                    need=move.product_uom_qty, have=move.quantity))
            move.picked = True
        picking.with_context(cst_skip_wh_control=True, skip_backorder=True, cancel_backorder=True,
                             picking_ids_not_to_backorder=picking.ids, skip_sms=True).button_validate()
        if picking.state != "done":
            raise UserError(_("%s tasdiqlanmadi.", picking.name))
        stamp = {}
        now = fields.Datetime.now()
        if "cst_received_at" in picking._fields:
            stamp.update(cst_received_at=now, cst_received_by_id=self.env.uid,
                         cst_sent_at=now, cst_sent_by_id=self.env.uid)
        if stamp:
            picking.write(stamp)

    def _cst_return_less(self, picking, less):
        """Too much was moved: the surplus goes back, as Odoo's own return."""
        wizard = self.env["stock.return.picking"].sudo().create({"picking_id": picking.id})
        for row in wizard.product_return_moves:
            row.quantity = less.get(row.move_id, 0.0)
        back = wizard._create_return()
        back.write({"cst_correction_of_id": picking.id,
                    "origin": _("Tuzatish: %s", picking.name)})
        back.move_ids.filtered(lambda m: m.product_uom.compare(m.product_uom_qty, 0.0) <= 0)._action_cancel()
        back.action_assign()
        self._cst_validate(back)
        return back

    def _cst_send_more(self, picking, more):
        """Too little was moved: the rest follows, same route, same type."""
        new = picking.copy({
            "move_ids": [],
            "origin": _("Tuzatish: %s", picking.name),
            "cst_correction_of_id": picking.id,
        })
        for move, qty in more.items():
            move.copy({
                "picking_id": new.id, "product_uom_qty": qty, "move_line_ids": [],
                "move_orig_ids": [], "move_dest_ids": [], "state": "draft", "picked": False,
            })
        new.action_confirm()
        new.action_assign()
        self._cst_validate(new)
        return new


class CstPickingCorrectionLine(models.TransientModel):
    _name = "cst.picking.correction.line"
    _description = "Ichki ko'chirishni tuzatish: mahsulot"

    wizard_id = fields.Many2one("cst.picking.correction", required=True, ondelete="cascade")
    move_id = fields.Many2one("stock.move", required=True, readonly=True)
    product_id = fields.Many2one(related="move_id.product_id", string="Mahsulot")
    uom_id = fields.Many2one(related="move_id.product_uom", string="Birlik")
    old_qty = fields.Float(string="Hujjatda", readonly=True, digits="Product Unit of Measure")
    new_qty = fields.Float(string="To'g'risi", digits="Product Unit of Measure")
