import logging

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare, float_is_zero, float_round

_logger = logging.getLogger(__name__)

GROUP_WH = "cst_kerama_dispatch.group_dispatch_warehouse"
GROUP_GATE = "cst_kerama_dispatch.group_dispatch_gate"


class CstDispatch(models.Model):
    _name = "cst.dispatch"
    _description = "Jo'natish"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char("Raqam", readonly=True, copy=False, default="/")
    state = fields.Selection([
        ("draft", "Tayyorlanmoqda"),
        ("ready", "Jo'natishga tayyor"),
        ("done", "Chiqarildi"),
        ("cancel", "Bekor qilindi"),
    ], string="Holat", default="draft", required=True, tracking=True, index=True)
    sale_order_id = fields.Many2one(
        "sale.order", string="Sotuv buyurtmasi", required=True, index=True,
        ondelete="restrict")
    partner_id = fields.Many2one(
        "res.partner", string="Mijoz", related="sale_order_id.partner_id", store=True)
    company_id = fields.Many2one(
        "res.company", string="Kompaniya", related="sale_order_id.company_id",
        store=True, precompute=True, index=True)
    warehouse_id = fields.Many2one(
        "stock.warehouse", string="Ombor", related="sale_order_id.warehouse_id", store=True)
    currency_id = fields.Many2one(related="sale_order_id.currency_id", string="Valyuta")
    line_ids = fields.One2many("cst.dispatch.line", "dispatch_id", string="Qatorlar")

    prepared_by_id = fields.Many2one("res.users", string="Tayyorladi", readonly=True)
    prepared_at = fields.Datetime("Tayyorlangan vaqt", readonly=True)
    checked_by_id = fields.Many2one("res.users", string="Tekshirdi (eshik)", readonly=True)
    checked_at = fields.Datetime("Chiqarilgan vaqt", readonly=True)
    car_model = fields.Char("Mashina rusumi")
    car_number = fields.Char("Mashina raqami")
    driver = fields.Char("Haydovchi")
    driver_phone = fields.Char("Haydovchi telefoni")
    note = fields.Text("Izoh")
    amount_before = fields.Monetary("Summa (oldin)", readonly=True)
    amount_after = fields.Monetary("Summa (keyin)", readonly=True)
    picking_ids = fields.Many2many(
        "stock.picking", string="Yetkazib berishlar", readonly=True, groups="stock.group_stock_user")
    invoice_ids = fields.Many2many(
        "account.move", string="Hisob-fakturalar", readonly=True,
        groups="account.group_account_invoice")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("cst.dispatch") or "/"
        return super().create(vals_list)

    # ------------------------------------------------------------------
    #  helpers
    # ------------------------------------------------------------------
    def _cst_require(self, group):
        if not self.env.user.has_group(group):
            raise AccessError(_("Bu amal uchun huquqingiz yo'q."))

    def _cst_companies(self):
        return self.env.companies.ids or self.env.company.ids

    @api.model
    def _cst_open_lines(self, order):
        """Goods lines of an order that still have something to deliver."""
        prec = self.env["decimal.precision"].precision_get("Product Unit")
        return order.order_line.filtered(
            lambda l: not l.display_type and l.product_id.type == "consu"
            and float_compare(l.product_uom_qty - l.qty_delivered, 0, precision_digits=prec) > 0)

    def _cst_fmt(self, qty):
        return float_round(qty or 0.0, precision_digits=3)

    def _cst_onhand(self, product, uom):
        wh = self.warehouse_id
        if not wh:
            return 0.0
        qty = product.with_context(location=wh.lot_stock_id.id).qty_available
        if uom and uom != product.uom_id:
            qty = product.uom_id._compute_quantity(qty, uom, round=False)
        return qty

    def _cst_price(self, line):
        """Unit price (tax included) used for the estimated new total."""
        if line.sale_line_id:
            sl = line.sale_line_id
            return sl.price_total / sl.product_uom_qty if sl.product_uom_qty else sl.price_unit
        order = self.sale_order_id
        if order.pricelist_id:
            return order.pricelist_id._get_product_price(line.product_id, max(line.qty, 1.0))
        return line.product_id.lst_price

    def _cst_get(self, dispatch_id):
        rec = self.sudo().browse(int(dispatch_id)).exists()
        if not rec or rec.company_id.id not in self._cst_companies():
            raise UserError(_("Jo'natma topilmadi."))
        return rec

    def _cst_line(self, line_id):
        line = self.env["cst.dispatch.line"].sudo().browse(int(line_id)).exists()
        if not line or line.dispatch_id.company_id.id not in self._cst_companies():
            raise UserError(_("Qator topilmadi."))
        return line

    def _cst_need_state(self, state):
        if self.state != state:
            raise UserError(_("Jo'natma holati o'zgargan («%s»). Sahifani yangilang.",
                              dict(self._fields["state"].selection)[self.state]))

    # ------------------------------------------------------------------
    #  UI: lists
    # ------------------------------------------------------------------
    @api.model
    def ui_home(self):
        user = self.env.user
        can_wh = user.has_group(GROUP_WH)
        can_gate = user.has_group(GROUP_GATE)
        can_transfer = user.has_group("cst_kerama_dispatch.group_dispatch_transfer")
        if not (can_wh or can_gate or can_transfer):
            raise AccessError(_("Bu ilova uchun huquqingiz yo'q."))
        Dispatch = self.sudo()
        cids = self._cst_companies()
        today = fields.Datetime.to_string(fields.Datetime.now().replace(hour=0, minute=0, second=0))
        return {
            "can_wh": can_wh,
            "can_gate": can_gate,
            "can_transfer": can_transfer,
            "transfers_to_me": self.env["cst.transfer.ui"].ui_count_to_me() if can_transfer else 0,
            "orders": len(self._cst_orders_to_prepare()) if can_wh else 0,
            "drafts": Dispatch.search_count([("state", "=", "draft"), ("company_id", "in", cids)]),
            "ready": Dispatch.search_count([("state", "=", "ready"), ("company_id", "in", cids)]),
            "done_today": Dispatch.search_count([
                ("state", "=", "done"), ("company_id", "in", cids), ("checked_at", ">=", today)]),
            "user": user.name,
        }

    @api.model
    def _cst_orders_to_prepare(self, search=None):
        domain = [
            ("state", "=", "sale"),
            ("company_id", "in", self._cst_companies()),
            ("delivery_status", "!=", "full"),
        ]
        if search:
            domain += ["|", "|", ("name", "ilike", search),
                       ("partner_id.name", "ilike", search),
                       ("client_order_ref", "ilike", search)]
        orders = self.env["sale.order"].sudo().search(domain, order="date_order desc", limit=300)
        return orders.filtered(lambda o: self._cst_open_lines(o))

    @api.model
    def ui_orders(self, search=None):
        self._cst_require(GROUP_WH)
        orders = self._cst_orders_to_prepare(search)[:100]
        active = self.sudo().search([
            ("sale_order_id", "in", orders.ids), ("state", "in", ("draft", "ready"))])
        by_order = {d.sale_order_id.id: d for d in active}
        res = []
        for o in orders:
            d = by_order.get(o.id)
            res.append({
                "id": o.id,
                "name": o.name,
                "partner": o.partner_id.display_name,
                "date": fields.Date.to_string(o.date_order.date()) if o.date_order else "",
                "amount": o.amount_total,
                "currency": o.currency_id.symbol or o.currency_id.name,
                "lines": len(self._cst_open_lines(o)),
                "warehouse": o.warehouse_id.name or "",
                "dispatch_id": d.id if d else False,
                "dispatch_name": d.name if d else "",
                "dispatch_state": d.state if d else "",
            })
        return res

    def _cst_card(self):
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "order": self.sale_order_id.name,
            "partner": self.partner_id.display_name,
            "warehouse": self.warehouse_id.name or "",
            "prepared_by": self.prepared_by_id.name or "",
            "prepared_at": fields.Datetime.to_string(
                fields.Datetime.context_timestamp(self, self.prepared_at)) if self.prepared_at else "",
            "checked_by": self.checked_by_id.name or "",
            "checked_at": fields.Datetime.to_string(
                fields.Datetime.context_timestamp(self, self.checked_at)) if self.checked_at else "",
            "lines": len(self.line_ids.filtered(lambda l: l.qty > 0)),
            "amount_before": self.amount_before,
            "amount_after": self.amount_after,
            "currency": self.currency_id.symbol or self.currency_id.name or "",
        }

    @api.model
    def ui_ready(self, search=None):
        self._cst_require(GROUP_GATE)
        domain = [("state", "=", "ready"), ("company_id", "in", self._cst_companies())]
        if search:
            domain += ["|", "|", ("name", "ilike", search),
                       ("sale_order_id.name", "ilike", search), ("partner_id.name", "ilike", search)]
        return [d._cst_card() for d in self.sudo().search(domain, order="prepared_at asc, id asc")]

    @api.model
    def ui_history(self, search=None):
        if not (self.env.user.has_group(GROUP_WH) or self.env.user.has_group(GROUP_GATE)):
            return []
        domain = [("state", "in", ("done", "cancel")), ("company_id", "in", self._cst_companies())]
        if search:
            domain += ["|", "|", ("name", "ilike", search),
                       ("sale_order_id.name", "ilike", search), ("partner_id.name", "ilike", search)]
        return [d._cst_card() for d in self.sudo().search(domain, limit=60)]

    # ------------------------------------------------------------------
    #  UI: one dispatch
    # ------------------------------------------------------------------
    @api.model
    def ui_start(self, order_id):
        self._cst_require(GROUP_WH)
        order = self.env["sale.order"].sudo().browse(int(order_id)).exists()
        if not order or order.company_id.id not in self._cst_companies():
            raise UserError(_("Buyurtma topilmadi."))
        existing = self.sudo().search([
            ("sale_order_id", "=", order.id), ("state", "in", ("draft", "ready"))], limit=1)
        if existing:
            return existing.id
        if order.state != "sale":
            raise UserError(_("Buyurtma tasdiqlanmagan."))
        lines = self._cst_open_lines(order)
        if not lines:
            raise UserError(_("Bu buyurtmada jo'natiladigan mahsulot qolmagan."))
        dispatch = self.sudo().create({
            "sale_order_id": order.id,
            "line_ids": [fields.Command.create({
                "sequence": i,
                "sale_line_id": sl.id,
                "product_id": sl.product_id.id,
                "uom_id": sl.product_uom_id.id,
                "ordered_qty": sl.product_uom_qty,
                "delivered_qty": sl.qty_delivered,
                "qty": sl.product_uom_qty - sl.qty_delivered,
            }) for i, sl in enumerate(lines)],
        })
        return dispatch.id

    def _cst_line_data(self, line):
        remaining = 0.0 if line.is_extra else line.ordered_qty - line.delivered_qty
        return {
            "id": line.id,
            "product_id": line.product_id.id,
            "product": line.product_id.display_name,
            "char": line.product_id.cst_characteristic or "",
            "code": line.product_id.default_code or "",
            "barcode": line.product_id.barcode or "",
            "uom": line.uom_id.name or "",
            "is_extra": line.is_extra,
            "ordered": self._cst_fmt(line.ordered_qty),
            "delivered": self._cst_fmt(line.delivered_qty),
            "remaining": self._cst_fmt(remaining),
            "qty": self._cst_fmt(line.qty),
            "checked": self._cst_fmt(line.checked_qty),
            "diff": self._cst_fmt(line.qty - remaining),
            "onhand": self._cst_fmt(self._cst_onhand(line.product_id, line.uom_id)),
            "price": line.price_unit,
        }

    @api.model
    def ui_load(self, dispatch_id):
        if not (self.env.user.has_group(GROUP_WH) or self.env.user.has_group(GROUP_GATE)):
            raise AccessError(_("Bu amal uchun huquqingiz yo'q."))
        d = self._cst_get(dispatch_id)
        order = d.sale_order_id
        lines = d.line_ids.sorted(lambda l: (l.sequence, l.id))
        for line in lines:
            line.price_unit = d._cst_price(line)
        base = order.amount_total if d.state != "done" else d.amount_before
        if d.state == "done":
            estimate = d.amount_after
        else:
            final = "checked_qty" if d.state == "ready" else "qty"
            delta = 0.0
            for line in lines:
                remaining = 0.0 if line.is_extra else line.ordered_qty - line.delivered_qty
                delta += (line[final] - remaining) * line.price_unit
            estimate = base + delta
        data = d._cst_card()
        data.update({
            "car_model": d.car_model or "",
            "car_number": d.car_number or "",
            "driver": d.driver or "",
            "driver_phone": d.driver_phone or "",
            "note": d.note or "",
            "order_amount": base,
            "estimate": estimate,
            "pickings": ", ".join(d.picking_ids.mapped("name")),
            "invoices": ", ".join(d.invoice_ids.mapped("name")),
            "line_list": [d._cst_line_data(l) for l in lines],
        })
        return data

    @api.model
    def ui_set_qty(self, line_id, qty, field="qty"):
        line = self._cst_line(line_id)
        d = line.dispatch_id
        qty = max(float(qty or 0.0), 0.0)
        if field == "qty":
            self._cst_require(GROUP_WH)
            d._cst_need_state("draft")
            line.qty = qty
        elif field == "checked_qty":
            self._cst_require(GROUP_GATE)
            d._cst_need_state("ready")
            line.checked_qty = qty
        else:
            raise UserError(_("Noto'g'ri maydon."))
        return True

    @api.model
    def ui_set_vehicle(self, dispatch_id, vals):
        """Car and driver: the warehouse may know them first, the gate confirms."""
        d = self._cst_get(dispatch_id)
        if d.state == "draft":
            self._cst_require(GROUP_WH)
        elif d.state == "ready":
            self._cst_require(GROUP_GATE)
        else:
            raise UserError(_("Bu jo'natma yopilgan."))
        allowed = ("car_model", "car_number", "driver", "driver_phone")
        d.write({k: (v or "").strip() or False for k, v in (vals or {}).items() if k in allowed})
        return True

    @api.model
    def ui_check_all(self, dispatch_id):
        self._cst_require(GROUP_GATE)
        d = self._cst_get(dispatch_id)
        d._cst_need_state("ready")
        for line in d.line_ids:
            line.checked_qty = line.qty
        return True

    def _cst_product_by_barcode(self, barcode):
        Product = self.env["product.product"].sudo()
        company_dom = ["|", ("company_id", "=", False), ("company_id", "=", self.company_id.id)]
        product = Product.search([("barcode", "=", barcode)] + company_dom, limit=1)
        if not product:
            product = Product.search([("default_code", "=", barcode)] + company_dom, limit=1)
        return product

    @api.model
    def ui_scan(self, dispatch_id, barcode):
        d = self._cst_get(dispatch_id)
        barcode = (barcode or "").strip()
        product = d._cst_product_by_barcode(barcode)
        if not product:
            return {"ok": False, "message": _("«%s» shtrix-kodli mahsulot topilmadi.", barcode)}
        lines = d.line_ids.filtered(lambda l: l.product_id == product)
        if d.state == "draft":
            self._cst_require(GROUP_WH)
            if lines:
                line = lines[0]
                line.qty += 1
            else:
                line = d._cst_add_line(product, 1.0)
            return {"ok": True, "line_id": line.id,
                    "message": _("%(p)s: %(q)s", p=product.display_name, q=self._cst_fmt(line.qty))}
        if d.state == "ready":
            self._cst_require(GROUP_GATE)
            if not lines:
                return {"ok": False, "message": _(
                    "%s bu jo'natmada yo'q! Ombor menejeriga qaytaring.", product.display_name)}
            line = next((l for l in lines if l.checked_qty < l.qty), lines[0])
            line.checked_qty += 1
            return {"ok": True, "line_id": line.id, "message": _(
                "%(p)s: %(c)s / %(q)s", p=product.display_name,
                c=self._cst_fmt(line.checked_qty), q=self._cst_fmt(line.qty))}
        return {"ok": False, "message": _("Bu jo'natma yopilgan.")}

    def _cst_add_line(self, product, qty):
        self.ensure_one()
        if product.type != "consu":
            raise UserError(_("Faqat tovar qo'shish mumkin (xizmat emas)."))
        seq = max(self.line_ids.mapped("sequence") or [0]) + 1
        return self.env["cst.dispatch.line"].sudo().create({
            "dispatch_id": self.id,
            "sequence": seq,
            "product_id": product.id,
            "uom_id": product.uom_id.id,
            "qty": qty,
        })

    @api.model
    def ui_search_products(self, dispatch_id, term):
        self._cst_require(GROUP_WH)
        d = self._cst_get(dispatch_id)
        term = (term or "").strip()
        if len(term) < 2:
            return []
        Product = self.env["product.product"].sudo().with_company(d.company_id)
        domain = [("sale_ok", "=", True), ("type", "=", "consu"),
                  "|", ("company_id", "=", False), ("company_id", "=", d.company_id.id)]
        found = Product.search(domain + [("barcode", "=", term)], limit=1)
        if not found:
            ids = [r[0] for r in Product.name_search(term, domain, limit=30)]
            found = Product.browse(ids)
        return [{
            "id": p.id,
            "name": p.display_name,
            "char": p.cst_characteristic or "",
            "code": p.default_code or "",
            "barcode": p.barcode or "",
            "uom": p.uom_id.name,
            "onhand": self._cst_fmt(d._cst_onhand(p, p.uom_id)),
        } for p in found]

    @api.model
    def ui_add_product(self, dispatch_id, product_id, qty=1.0):
        self._cst_require(GROUP_WH)
        d = self._cst_get(dispatch_id)
        d._cst_need_state("draft")
        product = self.env["product.product"].sudo().browse(int(product_id)).exists()
        if not product:
            raise UserError(_("Mahsulot topilmadi."))
        line = d.line_ids.filtered(lambda l: l.product_id == product)[:1]
        if line:
            line.qty += float(qty or 1.0)
        else:
            line = d._cst_add_line(product, float(qty or 1.0))
        return line.id

    @api.model
    def ui_remove_line(self, line_id):
        self._cst_require(GROUP_WH)
        line = self._cst_line(line_id)
        line.dispatch_id._cst_need_state("draft")
        if line.sale_line_id:
            line.qty = 0.0
        else:
            line.unlink()
        return True

    @api.model
    def ui_confirm(self, dispatch_id, note=None):
        """Warehouse: prepared → ready for the gate."""
        self._cst_require(GROUP_WH)
        d = self._cst_get(dispatch_id)
        d._cst_need_state("draft")
        if not any(l.qty > 0 for l in d.line_ids):
            raise UserError(_("Jo'natiladigan miqdor yo'q. Kamida bitta mahsulot kiriting."))
        d.line_ids.write({"checked_qty": 0.0})
        d.write({
            "state": "ready",
            "prepared_by_id": self.env.uid,
            "prepared_at": fields.Datetime.now(),
            "note": note if note is not None else d.note,
        })
        return True

    @api.model
    def ui_back_to_draft(self, dispatch_id, reason=None):
        """Gate (or warehouse) sends a ready order back for re-preparation."""
        if not (self.env.user.has_group(GROUP_WH) or self.env.user.has_group(GROUP_GATE)):
            raise AccessError(_("Bu amal uchun huquqingiz yo'q."))
        d = self._cst_get(dispatch_id)
        d._cst_need_state("ready")
        d.line_ids.write({"checked_qty": 0.0})
        d.state = "draft"
        if reason:
            d.message_post(body=_("Omborga qaytarildi: %s", reason))
        return True

    @api.model
    def ui_cancel(self, dispatch_id):
        self._cst_require(GROUP_WH)
        d = self._cst_get(dispatch_id)
        d._cst_need_state("draft")
        d.state = "cancel"
        return True

    @api.model
    def ui_done(self, dispatch_id, car_number=None, driver=None):
        """Gate: approve. Sync the order, deliver, invoice the difference."""
        self._cst_require(GROUP_GATE)
        d = self._cst_get(dispatch_id)
        d._cst_need_state("ready")
        vals = {}
        if car_number is not None:
            vals["car_number"] = car_number
        if driver is not None:
            vals["driver"] = driver
        if vals:
            d.write(vals)
        d._cst_apply()
        return True

    # ------------------------------------------------------------------
    #  the sync
    # ------------------------------------------------------------------
    def _cst_apply(self):
        self.ensure_one()
        prec = self.env["decimal.precision"].precision_get("Product Unit")
        order = self.sale_order_id.sudo().with_company(self.company_id)
        if order.state != "sale":
            raise UserError(_("%s buyurtmasi tasdiqlangan holatda emas.", order.name))
        amount_before = order.amount_total
        posted_invoices = order.invoice_ids.filtered(
            lambda m: m.state == "posted" and m.move_type == "out_invoice")
        was_locked = order.locked
        if was_locked:
            order.action_unlock()

        changes = []
        lines = self.line_ids.sorted(lambda l: (l.sequence, l.id))
        # 1. fewer first (negative procurements shrink the open moves), then more
        def target(line):
            return line.sale_line_id.qty_delivered + line.checked_qty

        decrease = lines.filtered(lambda l: l.sale_line_id and float_compare(
            target(l), l.sale_line_id.product_uom_qty, precision_digits=prec) < 0)
        increase = lines.filtered(lambda l: l.sale_line_id and float_compare(
            target(l), l.sale_line_id.product_uom_qty, precision_digits=prec) > 0)
        for line in decrease | increase:
            sl = line.sale_line_id
            changes.append((sl.product_id.display_name, sl.product_uom_qty, target(line)))
            # a quantity change re-runs the pricelist: keep the agreed price and discount
            sl.write({
                "product_uom_qty": target(line),
                "price_unit": sl.price_unit,
                "discount": sl.discount,
            })
        for line in lines.filtered(lambda l: not l.sale_line_id):
            if float_is_zero(line.checked_qty, precision_digits=prec):
                continue
            sl = self.env["sale.order.line"].sudo().create({
                "order_id": order.id,
                "product_id": line.product_id.id,
                "product_uom_qty": line.checked_qty,
                "product_uom_id": line.uom_id.id,
            })
            line.sale_line_id = sl
            changes.append((sl.product_id.display_name, 0.0, line.checked_qty))

        # 2. deliver exactly what passed the gate
        pickings = self.env["stock.picking"]
        for line in lines.filtered("sale_line_id"):
            sl = line.sale_line_id
            moves = sl.move_ids.filtered(
                lambda m: m.state not in ("done", "cancel")
                and m.picking_id.picking_type_code == "outgoing")
            qty_left = line.checked_qty
            if float_is_zero(qty_left, precision_digits=prec):
                moves.filtered(lambda m: m.quantity).write({"quantity": 0.0})
                continue
            if not moves:
                raise UserError(_(
                    "%s uchun ochiq yetkazib berish topilmadi. Administratorga murojaat qiling.",
                    sl.product_id.display_name))
            for i, move in enumerate(moves):
                demand = move.product_uom._compute_quantity(move.product_uom_qty, sl.product_uom_id)
                take = qty_left if i == len(moves) - 1 else min(qty_left, demand)
                move.quantity = sl.product_uom_id._compute_quantity(take, move.product_uom)
                move.picked = True
                qty_left -= take
                pickings |= move.picking_id
        for picking in pickings:
            # moves of this picking we did not deliver (order lines left out of the dispatch)
            picking.move_ids.filtered(
                lambda m: m.state not in ("done", "cancel") and not m.picked).write({"quantity": 0.0})
            res = picking.with_context(
                skip_backorder=True, cancel_backorder=True,
                picking_ids_not_to_backorder=picking.ids,
                skip_sms=True,
            ).button_validate()
            if isinstance(res, dict) and picking.state != "done":
                raise UserError(_("%s yetkazib berishini tasdiqlab bo'lmadi.", picking.name))
        # deliveries whose demand is now fully covered: drop the leftovers
        for picking in order.picking_ids.filtered(
                lambda p: p.picking_type_code == "outgoing" and p.state not in ("done", "cancel")):
            moves = picking.move_ids.filtered(
                lambda m: m.state not in ("done", "cancel") and m.sale_line_id and float_compare(
                    m.sale_line_id.qty_delivered, m.sale_line_id.product_uom_qty,
                    precision_digits=prec) >= 0)
            if moves:
                moves._action_cancel()
            if all(m.state == "cancel" for m in picking.move_ids):
                picking.action_cancel()

        # 3. the money side: an already invoiced order gets the difference invoiced
        invoices = self.env["account.move"]
        if posted_invoices and any(
                not float_is_zero(sl.qty_to_invoice, precision_digits=prec)
                for sl in lines.sale_line_id):
            try:
                with self.env.cr.savepoint():
                    invoices = order.with_context(
                        cst_dispatch_sale_line_ids=lines.sale_line_id.ids,
                    )._create_invoices(final=True)
                    invoices.action_post()
            except Exception as exc:  # noqa: BLE001 — never block the gate on accounting
                _logger.warning("dispatch %s: difference invoice failed: %s", self.name, exc)
                invoices = self.env["account.move"]
                order.message_post(body=_(
                    "Jo'natma %(d)s: farq uchun hisob-faktura avtomatik yaratilmadi (%(e)s). "
                    "Buxgalter qo'lda yaratsin.", d=self.name, e=str(exc)))

        if was_locked:
            order.action_lock()

        if changes:
            rows = "".join(
                "<li>%s: %s → %s</li>" % (name, self._cst_fmt(old), self._cst_fmt(new))
                for name, old, new in changes)
            order.message_post(body=Markup(
                "<p>%s</p><ul>%s</ul><p>%s</p>") % (
                _("Jo'natma %s eshikda tasdiqlandi. Miqdor o'zgarishlari:", self.name),
                Markup(rows),
                _("Summa: %(a)s → %(b)s", a=amount_before, b=order.amount_total)))

        if self.car_number or self.driver or self.car_model:
            driver = self.driver or ""
            if self.driver_phone:
                driver = ("%s (%s)" % (driver, self.driver_phone)).strip()
            pickings.filtered(lambda p: p.state == "done").write({
                "cst_car_model": self.car_model or False,
                "cst_car_number": self.car_number or False,
                "cst_driver": driver or False,
            })
        self.write({
            "state": "done",
            "checked_by_id": self.env.uid,
            "checked_at": fields.Datetime.now(),
            "amount_before": amount_before,
            "amount_after": order.amount_total,
            "picking_ids": [fields.Command.set(pickings.filtered(lambda p: p.state == "done").ids)],
            "invoice_ids": [fields.Command.set(invoices.ids)],
        })

    def action_print_waybill_80(self):
        return {"type": "ir.actions.act_url", "target": "new",
                "url": "/kerama/dispatch/waybill/%d?size=80" % self.id}

    def action_print_waybill_a4(self):
        return {"type": "ir.actions.act_url", "target": "new",
                "url": "/kerama/dispatch/waybill/%d?size=a4" % self.id}

    def action_open_app(self):
        return {"type": "ir.actions.client", "tag": "cst_dispatch_app",
                "params": {"dispatch_id": self.id}}


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _get_invoiceable_lines(self, final=False):
        lines = super()._get_invoiceable_lines(final=final)
        only = self.env.context.get("cst_dispatch_sale_line_ids")
        if only is not None:
            # the gate invoices its own difference only, never a pending
            # down-payment deduction or another line someone left open
            lines = lines.filtered(lambda l: l.id in only)
        return lines


class CstDispatchLine(models.Model):
    _name = "cst.dispatch.line"
    _description = "Jo'natish qatori"
    _order = "sequence, id"

    dispatch_id = fields.Many2one("cst.dispatch", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    sale_line_id = fields.Many2one("sale.order.line", string="Buyurtma qatori", ondelete="set null")
    product_id = fields.Many2one("product.product", string="Mahsulot", required=True)
    uom_id = fields.Many2one("uom.uom", string="O'lchov birligi")
    ordered_qty = fields.Float("Buyurtma", digits="Product Unit")
    delivered_qty = fields.Float("Oldin yetkazilgan", digits="Product Unit")
    qty = fields.Float("Jo'natiladi", digits="Product Unit")
    checked_qty = fields.Float("Eshikda sanaldi", digits="Product Unit")
    is_extra = fields.Boolean("Qo'shimcha mahsulot", compute="_compute_is_extra", store=True)
    price_unit = fields.Float("Narx (QQS bilan)")

    @api.depends("ordered_qty", "delivered_qty")
    def _compute_is_extra(self):
        # set once at creation: an order line has an ordered quantity, a
        # product added by the warehouse has none (even after it got its own
        # order line at the gate)
        for line in self:
            line.is_extra = not line.ordered_qty and not line.delivered_qty
