from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CstProductionShiftEntry(models.Model):
    """A result the manager typed during the shift: so many good, 2-sort, brak."""

    _name = "cst.production.shift.entry"
    _description = "Smena natijasi"
    _order = "datetime desc, id desc"

    line_id = fields.Many2one("cst.production.shift.line", string="Buyurtma", required=True, ondelete="cascade", index=True)
    shift_id = fields.Many2one(related="line_id.shift_id", store=True, index=True)
    # results belong to the shift's day, whenever they were typed
    shift_date = fields.Date(related="line_id.shift_id.date", store=True, string="Smena sanasi", index=True)
    template_id = fields.Many2one(related="line_id.shift_id.template_id", store=True, string="Smena vaqti")
    department_id = fields.Many2one(related="line_id.department_id", store=True)
    production_id = fields.Many2one(related="line_id.production_id", store=True)
    product_id = fields.Many2one(related="line_id.product_id", store=True)
    workcenter_id = fields.Many2one(related="line_id.workcenter_id", store=True)
    datetime = fields.Datetime(string="Vaqt", default=fields.Datetime.now, required=True)
    user_id = fields.Many2one("res.users", string="Kim kiritdi", default=lambda self: self.env.user, readonly=True)
    qty_good = fields.Float(string="1-sort", digits="Product Unit of Measure")
    qty_second = fields.Float(string="2-sort", digits="Product Unit of Measure")
    qty_scrap = fields.Float(string="Brak", digits="Product Unit of Measure")
    second_product_id = fields.Many2one(
        "product.product", string="2-sort mahsuloti",
        help="2-sort qaysi mahsulot bo'lib omborga kirishi. Bo'sh bo'lsa — mahsulotning avtomatik "
             "«— 2-sort» egizagi.")
    material_product_id = fields.Many2one(
        "product.product", string="Brak bo'lgan material",
        help="Masalan preslashda buzilgan обой: texkarta xomashyosidan qaysi biri brakka chiqdi.")
    qty_material = fields.Float(string="Material braki", digits="Product Unit of Measure")
    note = fields.Char(string="Eslatma")
    posted = fields.Boolean(string="Omborga o'tgan", readonly=True, copy=False)
    corrected = fields.Boolean(string="Tuzatilgan", readonly=True, copy=False)
    correction_log = fields.Text(string="Tuzatishlar", readonly=True, copy=False)

    @api.constrains("qty_good", "qty_second", "qty_scrap", "qty_material", "material_product_id")
    def _check_positive(self):
        for entry in self:
            if min(entry.qty_good, entry.qty_second, entry.qty_scrap, entry.qty_material) < 0:
                raise ValidationError(_("Miqdorlar manfiy bo'lishi mumkin emas."))
            if not (entry.qty_good or entry.qty_second or entry.qty_scrap or entry.qty_material):
                raise ValidationError(_("Hech bo'lmaganda bitta miqdor kiriting."))
            if entry.qty_material and not entry.material_product_id:
                raise ValidationError(_("Brak bo'lgan materialni tanlang."))

    @api.model_create_multi
    def create(self, vals_list):
        entries = super().create(vals_list)
        # Odoo only runs a constraint for the fields present in the values, so
        # an entry created with no quantity at all would slip through
        entries._check_positive()
        if self.env.context.get("cst_sync"):
            return entries  # written by the system from what Odoo already booked
        for entry in entries:
            if entry.shift_id.state != "open":
                raise UserError(_("Smena ochiq emas, natija kiritib bo'lmaydi."))
            if entry.line_id.state == "todo":
                entry.line_id.action_start()
            elif entry.line_id.state in ("done", "carried"):
                raise UserError(_("«%s» bu smenada yakunlangan. Yangi qator oching.", entry.line_id.production_id.name))
            entry.line_id._check_order_remaining()
        return entries

    def write(self, vals):
        if self.env.context.get("cst_correction"):
            return super().write(vals)  # the «Tuzatish» wizard, stock already corrected
        if any(e.posted for e in self) and set(vals) & {"qty_good", "qty_second", "qty_scrap", "qty_material",
                                                             "second_product_id", "material_product_id", "line_id"}:
            raise UserError(_("Omborga o'tgan natijani o'zgartirib bo'lmaydi. Yangi yozuv kiriting "
                              "yoki administrator «Tuzatish» qilsin."))
        return super().write(vals)

    def unlink(self):
        # cst_undo: the floor's «o'chirish» already unbuilt the stock
        if any(e.posted for e in self) and not self.env.context.get("cst_undo"):
            raise UserError(_("Omborga o'tgan natijani o'chirib bo'lmaydi."))
        return super().unlink()

    def action_open_correction(self):
        """«Tuzatish» on a booked result: new quantities and a reason."""
        self.ensure_one()
        if not self.env.user.has_group("cst_kerama_shift.group_doc_correction"):
            raise UserError(_("Yakunlangan natijani faqat administrator yoki rahbar tuzatadi."))
        return {
            "type": "ir.actions.act_window", "name": _("Natijani tuzatish"),
            "res_model": "cst.production.shift.correction", "view_mode": "form", "target": "new",
            "context": {"default_entry_id": self.id},
        }
