from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CstProductionShiftCorrection(models.TransientModel):
    """«Tuzatish»: a booked shift result had a typo (53 instead of 50).

    The administrator types the right quantities and why. Stock is put right
    with counter-documents (unbuild, correction order, scrap moves), the result
    row takes the new numbers so every total and report follows, and the old
    and new values go to the chatter with the reason.
    """

    _name = "cst.production.shift.correction"
    _description = "Smena natijasini tuzatish"

    entry_id = fields.Many2one("cst.production.shift.entry", string="Natija", required=True, readonly=True)
    shift_id = fields.Many2one(related="entry_id.shift_id")
    production_id = fields.Many2one(related="entry_id.production_id", string="Buyurtma")
    product_id = fields.Many2one(related="entry_id.product_id", string="Mahsulot")
    is_final = fields.Boolean(related="entry_id.line_id.is_final_operation", string="Omborga tushadi")
    old_good = fields.Float(string="Hozir: 1-sort", readonly=True, digits="Product Unit of Measure")
    old_second = fields.Float(string="Hozir: 2-sort", readonly=True, digits="Product Unit of Measure")
    old_scrap = fields.Float(string="Hozir: brak", readonly=True, digits="Product Unit of Measure")
    new_good = fields.Float(string="To'g'ri 1-sort", digits="Product Unit of Measure")
    new_second = fields.Float(string="To'g'ri 2-sort", digits="Product Unit of Measure")
    new_scrap = fields.Float(string="To'g'ri brak", digits="Product Unit of Measure")
    reason = fields.Text(string="Sabab", required=True)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        entry = self.env["cst.production.shift.entry"].browse(
            values.get("entry_id") or self.env.context.get("default_entry_id"))
        if entry:
            values.update({
                "old_good": entry.qty_good, "old_second": entry.qty_second, "old_scrap": entry.qty_scrap,
                "new_good": entry.qty_good, "new_second": entry.qty_second, "new_scrap": entry.qty_scrap,
            })
        return values

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group("cst_kerama_shift.group_doc_correction"):
            raise UserError(_("Yakunlangan natijani faqat administrator yoki rahbar tuzatadi."))
        entry = self.entry_id
        line = entry.line_id
        uom = line.product_uom_id
        if min(self.new_good, self.new_second, self.new_scrap) < 0:
            raise UserError(_("Miqdorlar manfiy bo'lishi mumkin emas."))
        if not (self.reason or "").strip():
            raise UserError(_("Tuzatish sababini yozing."))
        if not entry.posted:
            raise UserError(_("Bu natija hali omborga o'tmagan — uni oddiy tahrirlash mumkin."))
        d_good = self.new_good - entry.qty_good
        d_second = self.new_second - entry.qty_second
        d_scrap = self.new_scrap - entry.qty_scrap
        if all(uom.compare(d, 0.0) == 0 for d in (d_good, d_second, d_scrap)):
            raise UserError(_("Miqdorlar o'zgarmadi."))
        if not (self.new_good or self.new_second or self.new_scrap or entry.qty_material):
            raise UserError(_("Hamma miqdor nol bo'lib qoldi. Natijani butunlay bekor qilish uchun "
                              "bo'lim oynasidagi «o'chirish»dan foydalaning."))
        line.sudo()._cst_apply_correction(d_good, d_second, d_scrap, entry.second_product_id or None)
        stamp = fields.Datetime.context_timestamp(self, fields.Datetime.now()).strftime("%d.%m.%Y %H:%M")
        change = _("1-sort %(g0)s → %(g1)s, 2-sort %(s0)s → %(s1)s, brak %(b0)s → %(b1)s",
                   g0=entry.qty_good, g1=self.new_good, s0=entry.qty_second, s1=self.new_second,
                   b0=entry.qty_scrap, b1=self.new_scrap)
        log = "%s · %s · %s: %s" % (stamp, self.env.user.name, change, self.reason.strip())
        entry.sudo().with_context(cst_correction=True).write({
            "qty_good": self.new_good, "qty_second": self.new_second, "qty_scrap": self.new_scrap,
            "corrected": True,
            "correction_log": "\n".join(filter(None, [entry.correction_log, log])),
        })
        body = _("Natija tuzatildi (%(mo)s, %(product)s): %(change)s. Sabab: %(reason)s",
                 mo=line.production_id.name, product=line.product_id.display_name, change=change,
                 reason=self.reason.strip())
        line.shift_id.sudo().message_post(body=body)
        line.production_id.sudo().message_post(body=body)
        return {"type": "ir.actions.act_window_close"}
