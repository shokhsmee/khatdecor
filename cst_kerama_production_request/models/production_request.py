"""A production request (zayafka): «make this many of this, for this order».

The planning screen raises one per ticked row. Each request opens one
manufacturing order — confirmed, not started — in the chosen department's
warehouse and on its line, so it shows up in that department's window as a
new order. Its state is read back from the order (and the order's backorders).
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

STATES = [
    ("sent", "Yuborildi"),
    ("progress", "Ishlab chiqarilmoqda"),
    ("done", "Tayyor"),
    ("released", "Sotuvga chiqarildi"),
    ("cancel", "Bekor qilindi"),
]


class CstProductionRequest(models.Model):
    _name = "cst.production.request"
    _description = "Ishlab chiqarish zayafkasi"
    _inherit = ["mail.thread"]
    _order = "urgent desc, id desc"

    name = fields.Char(string="Zayafka", required=True, copy=False, readonly=True, default="/")
    kind = fields.Selection([("order", "Zakaz"), ("stock", "Ombor to'ldirish")], string="Tur",
                            required=True, default="order")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    sale_line_id = fields.Many2one("sale.order.line", string="Sotuv qatori", index=True, readonly=True)
    sale_order_id = fields.Many2one(related="sale_line_id.order_id", store=True, string="Sotuv buyurtmasi")
    partner_id = fields.Many2one(related="sale_line_id.order_id.partner_id", store=True, string="Mijoz")
    product_id = fields.Many2one("product.product", string="Mahsulot", required=True, readonly=True)
    uom_id = fields.Many2one(related="product_id.uom_id", string="Birlik")
    bom_id = fields.Many2one("mrp.bom", string="Tex karta", readonly=True)
    department_id = fields.Many2one("cst.production.department", string="Bo'lim", readonly=True, index=True)
    qty = fields.Float(string="Zayafka soni", digits="Product Unit of Measure", required=True, readonly=True)
    demand_qty = fields.Float(string="Zakaz", digits="Product Unit of Measure", readonly=True,
                              help="Zayafka yaratilgan paytda buyurtmada jo'natilishi kerak bo'lgan miqdor.")
    stock_qty = fields.Float(string="Qoldiq", digits="Product Unit of Measure", readonly=True,
                             help="Zayafka yaratilgan paytda shu buyurtma uchun omborda bor edi.")
    short_qty = fields.Float(string="Yetmaydi", digits="Product Unit of Measure", readonly=True)
    urgent = fields.Boolean(string="Tezkor", tracking=True,
                            help="Bo'lim navbatida birinchi turadi (buyurtma ustuvorligi «Shoshilinch»).")
    note = fields.Text(string="Izoh")
    production_ids = fields.One2many("mrp.production", "cst_request_id", string="Ishlab chiqarish buyurtmalari")
    production_id = fields.Many2one("mrp.production", compute="_compute_production", string="Buyurtma")
    qty_produced = fields.Float(compute="_compute_production", digits="Product Unit of Measure",
                                string="Ishlab chiqarildi")
    released = fields.Boolean(string="Sotuvga chiqarilgan", readonly=True, copy=False)
    released_date = fields.Datetime(string="Sotuvga chiqarilgan sana", readonly=True, copy=False)
    cancelled = fields.Boolean(readonly=True, copy=False)
    state = fields.Selection(STATES, string="Holat", compute="_compute_state", store=True, index=True,
                             tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("cst.production.request") or "/"
        return super().create(vals_list)

    @api.depends("production_ids.qty_produced", "production_ids.state")
    def _compute_production(self):
        for request in self:
            productions = request.production_ids.sorted("id")
            request.production_id = productions[:1]
            request.qty_produced = sum(productions.filtered(lambda p: p.state == "done").mapped("qty_produced"))

    @api.depends("production_ids.state", "production_ids.cst_stage", "production_ids.qty_produced",
                 "released", "cancelled")
    def _compute_state(self):
        for request in self:
            productions = request.production_ids
            live = productions.filtered(lambda p: p.state != "cancel")
            if request.cancelled or (productions and not live):
                request.state = "cancel"
            elif live and all(p.state == "done" for p in live):
                # «Tayyor» only once the goods reached the next warehouse
                received = all(p.cst_stage == "received" for p in live)
                request.state = "released" if request.released else ("done" if received else "progress")
            elif any(p.state in ("progress", "to_close", "done") or p.qty_produced > 0 for p in live):
                request.state = "progress"
            else:
                request.state = "sent"

    # ------------------------------------------------------------------ actions
    def _cst_set_urgent(self, value):
        for request in self:
            request.urgent = bool(value)
            request.production_ids.filtered(lambda p: p.state not in ("done", "cancel")).sudo().write(
                {"priority": "1" if value else "0"})

    def _cst_can_cancel(self):
        self.ensure_one()
        if self.state != "sent":
            return False
        Floor = self.env["cst.production.floor"].sudo()
        return all(Floor._can_cancel(p) for p in self.production_ids.filtered(lambda p: p.state != "cancel"))

    def action_cst_cancel(self):
        for request in self:
            if not request._cst_can_cancel():
                raise UserError(_("%s: ishlab chiqarish boshlangan, zayafkani bekor qilib bo'lmaydi.", request.name))
            productions = request.production_ids.filtered(lambda p: p.state != "cancel").sudo()
            # the department window drops the order from its queue on its own
            productions.action_cancel()
            request.cancelled = True
            request.message_post(body=_("Zayafka bekor qilindi."))
        return True

    def _cst_release(self):
        """Book what was made onto the sales order's delivery."""
        reserved = 0.0
        for request in self:
            if request.state != "done":
                raise UserError(_("%s hali tayyor emas.", request.name))
            if request.sale_line_id:
                reserved += self.env["cst.production.request.board"]._cst_reserve_line(request.sale_line_id)
            request.write({"released": True, "released_date": fields.Datetime.now()})
            request.message_post(body=_("Sotuvga chiqarildi."))
        return reserved

    def action_open_production(self):
        self.ensure_one()
        productions = self.production_ids
        action = {
            "type": "ir.actions.act_window",
            "res_model": "mrp.production",
            "name": self.name,
        }
        if len(productions) == 1:
            action.update(view_mode="form", res_id=productions.id)
        else:
            action.update(view_mode="list,form", domain=[("id", "in", productions.ids)])
        return action
