import logging

from markupsafe import Markup

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

_logger = logging.getLogger(__name__)

GROUP_CORRECTION = "cst_kerama_shift.group_doc_correction"


class SaleOrder(models.Model):
    _inherit = "sale.order"

    cst_can_correct_sale = fields.Boolean(compute="_compute_cst_can_correct_sale")

    @api.depends_context("uid")
    @api.depends("state", "order_line.qty_delivered")
    def _compute_cst_can_correct_sale(self):
        allowed = self.env.user.has_group(GROUP_CORRECTION)
        for order in self:
            order.cst_can_correct_sale = allowed and order._cst_has_history()

    def _cst_has_history(self):
        """Goods have left or an invoice is posted: from here on the order is
        corrected with counter-documents, not edited or cancelled."""
        self.ensure_one()
        if self.state == "cancel":
            return False
        order = self.sudo()
        return any(l.qty_delivered for l in order.order_line) or any(
            m.state == "posted" for m in order.invoice_ids)

    def action_cst_open_sale_correction(self):
        self.ensure_one()
        if not self.env.user.has_group(GROUP_CORRECTION):
            raise UserError(_("Yuk chiqib ketgan sotuvni faqat administrator yoki rahbar tuzatadi."))
        return {
            "type": "ir.actions.act_window", "name": _("Sotuvni tuzatish: %s", self.name),
            "res_model": "cst.sale.correction", "view_mode": "form", "target": "new",
            "context": {"default_order_id": self.id},
        }

    def action_cancel(self):
        # cancelling leaves the delivery done and the invoices posted (S00454):
        # goods that left come back only through «Tuzatish»
        prec = self.env["decimal.precision"].precision_get("Product Unit")
        for order in self:
            delivered = order.order_line.filtered(
                lambda l: float_compare(l.qty_delivered, 0.0, precision_digits=prec) > 0)
            if delivered:
                raise UserError(_(
                    "%(order)s: yuk chiqib ketgan (%(products)s). Bekor qilib bo'lmaydi — «Tuzatish» tugmasi bilan "
                    "miqdorni 0 qiling: tovar omborga qaytadi, hisob-faktura kreditlanadi, keyin bekor qilish mumkin.",
                    order=order.name, products=", ".join(delivered.product_id.mapped("display_name")[:5])))
        return super().action_cancel()


class CstSaleCorrection(models.TransientModel):
    """«Sotuvni tuzatish» -- a sale whose goods have left (and whose invoice
    is posted at the gate) is corrected with counter-documents:

    * fewer pieces -> a return of the difference, validated into the warehouse
      the goods left from;
    * more pieces -> the order grows; the extra goes out at once (it already
      left) or waits in an open delivery for the Jo'natish gate;
    * a new price or discount -> what was invoiced at the old price is credited
      at that price and invoiced again at the new one;
    * the money follows: credit notes for what came back, an invoice for what
      left, the client's open documents reconciled with each other.

    Nothing done is edited in place; every document is linked to the order and
    the reason, the user and the old/new numbers go to its chatter.
    """

    _name = "cst.sale.correction"
    _description = "Sotuvni tuzatish"

    order_id = fields.Many2one("sale.order", string="Buyurtma", required=True, readonly=True)
    partner_id = fields.Many2one(related="order_id.partner_id", string="Mijoz")
    currency_id = fields.Many2one(related="order_id.currency_id")
    order_state = fields.Selection(related="order_id.state", string="Holati")
    line_ids = fields.One2many("cst.sale.correction.line", "wizard_id", string="Mahsulotlar")
    ship_now = fields.Boolean(
        string="Qo'shimcha tovar allaqachon chiqib ketgan", default=True,
        help="Belgilansa, ko'paytirilgan miqdor darhol ombordan chiqim qilinadi (yuk ketib bo'lgan). "
             "Belgilanmasa, u ochiq yetkazib berishda qoladi va Jo'natish orqali chiqadi.")
    reason = fields.Text(string="Sabab", required=True)
    amount_before = fields.Monetary(string="Hozirgi summa", currency_field="currency_id",
                                    compute="_compute_amounts")
    amount_after = fields.Monetary(string="Yangi summa", currency_field="currency_id",
                                   compute="_compute_amounts")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        order = self.env["sale.order"].browse(values.get("order_id") or self.env.context.get("default_order_id"))
        if order:
            rows = []
            for line in order.sudo().order_line.filtered(lambda l: not l.display_type and not l.is_downpayment):
                rows.append((0, 0, {
                    "sale_line_id": line.id, "product_id": line.product_id.id, "uom_id": line.product_uom_id.id,
                    "delivered_qty": line.qty_delivered, "invoiced_qty": line.qty_invoiced,
                    "old_qty": line.product_uom_qty, "old_price": line.price_unit, "old_discount": line.discount,
                    "new_qty": line.product_uom_qty, "new_price": line.price_unit, "new_discount": line.discount,
                }))
            values["line_ids"] = rows
        return values

    @api.depends("line_ids.subtotal_old", "line_ids.subtotal_new")
    def _compute_amounts(self):
        for wizard in self:
            wizard.amount_before = sum(wizard.line_ids.mapped("subtotal_old"))
            wizard.amount_after = sum(wizard.line_ids.mapped("subtotal_new"))

    # ------------------------------------------------------------------
    def _check(self, changes):
        prec = self.env["decimal.precision"].precision_get("Product Unit")
        if not self.env.user.has_group(GROUP_CORRECTION):
            raise UserError(_("Yuk chiqib ketgan sotuvni faqat administrator yoki rahbar tuzatadi."))
        if not (self.reason or "").strip():
            raise UserError(_("Tuzatish sababini yozing."))
        if self.order_id.state == "cancel":
            raise UserError(_("Bekor qilingan buyurtma tuzatilmaydi."))
        if not changes:
            raise UserError(_("Hech narsa o'zgarmadi."))
        for line in changes:
            if not line.product_id:
                raise UserError(_("Yangi qatorda mahsulot tanlanmagan."))
            if float_compare(line.new_qty, 0.0, precision_digits=prec) < 0 or line.new_price < 0:
                raise UserError(_("%s: miqdor va narx manfiy bo'lmaydi.", line.product_id.display_name))
            if not 0 <= line.new_discount <= 100:
                raise UserError(_("%s: chegirma 0–100%% bo'ladi.", line.product_id.display_name))
            if not line.sale_line_id and float_is_zero(line.new_qty, precision_digits=prec):
                raise UserError(_("%s: yangi qatorning miqdori 0.", line.product_id.display_name))
        busy = self.env["cst.dispatch"].sudo().search([
            ("sale_order_id", "=", self.order_id.id), ("state", "in", ("draft", "ready"))], limit=1)
        if busy:
            raise UserError(_(
                "%(order)s bo'yicha ochiq jo'natma bor (%(d)s). Avval uni eshikda yakunlang yoki bekor qiling.",
                order=self.order_id.name, d=busy.name))

    def action_apply(self):
        self.ensure_one()
        changes = self.line_ids.filtered(lambda l: l._cst_changed())
        self._check(changes)
        order = self.order_id.sudo().with_company(self.order_id.company_id)
        amount_before = order.amount_total
        had_invoices = bool(order.invoice_ids.filtered(lambda m: m.state == "posted"))
        notes = []
        if order.state in ("draft", "sent"):
            # an order cancelled and set back to a quotation after its goods left:
            # it is still a sale -- confirm it again before correcting it
            order.action_confirm()
            notes.append(_("buyurtma qayta tasdiqlandi (yuk chiqib ketgan edi)"))
        was_locked = order.locked
        if was_locked:
            order.action_unlock()

        # 1. what was invoiced at the old price is credited at that price
        repriced = changes.filtered(lambda l: l.sale_line_id and l._cst_price_changed()
                                    and not float_is_zero(l.sale_line_id.qty_invoiced, precision_digits=6))
        credit = self._cst_credit_invoiced(order, repriced) if repriced else self.env["account.move"]

        # 2. goods that did not leave after all come back
        returns = self._cst_return_goods(order, changes)

        # 3. the order says the new numbers (the price is passed on: a quantity
        #    change re-runs the pricelist)
        for line in changes.filtered("sale_line_id"):
            line.sale_line_id.with_context(cst_correction=True).write({
                "product_uom_qty": line.new_qty, "price_unit": line.new_price, "discount": line.new_discount})
        for line in changes.filtered(lambda l: not l.sale_line_id):
            line.sale_line_id = self.env["sale.order.line"].sudo().create({
                "order_id": order.id, "product_id": line.product_id.id, "product_uom_qty": line.new_qty,
                "product_uom_id": (line.uom_id or line.product_id.uom_id).id,
                "price_unit": line.new_price, "discount": line.new_discount})
        self._cst_drop_covered_moves(order)

        # 4. extra pieces that already left
        deliveries = self._cst_ship_now(order, changes.sale_line_id) if self.ship_now else self.env["stock.picking"]

        # 5. the money
        invoices = self._cst_settle_money(order, changes.sale_line_id, had_invoices) | credit
        if was_locked:
            order.action_lock()
        self._cst_log(order, changes, amount_before, notes, returns | deliveries, invoices)
        return {"type": "ir.actions.act_window_close"}

    # ------------------------------------------------------------------ stock
    def _cst_return_goods(self, order, changes):
        """Return (delivered − new) of every line made smaller than what left,
        newest delivery first, validated at once."""
        prec = self.env["decimal.precision"].precision_get("Product Unit")
        wanted = {}
        for line in changes.filtered("sale_line_id"):
            back = line.sale_line_id.qty_delivered - line.new_qty
            if float_compare(back, 0.0, precision_digits=prec) > 0:
                wanted[line.sale_line_id.id] = back
        pickings = self.env["stock.picking"]
        if not wanted:
            return pickings
        done = order.picking_ids.filtered(
            lambda p: p.picking_type_code == "outgoing" and p.state == "done").sorted("date_done", reverse=True)
        for picking in done:
            if not any(float_compare(q, 0.0, precision_digits=prec) > 0 for q in wanted.values()):
                break
            wizard = self.env["stock.return.picking"].sudo().with_context(
                active_id=picking.id, active_model="stock.picking").create({"picking_id": picking.id})
            took = False
            for rline in wizard.product_return_moves:
                move = rline.move_id
                sl = move.sale_line_id
                want = wanted.get(sl.id, 0.0)
                returnable = move.quantity - sum(
                    m.quantity for m in move.returned_move_ids if m.state == "done")
                returnable = move.product_uom._compute_quantity(returnable, sl.product_uom_id) if sl else 0.0
                take = min(want, max(returnable, 0.0))
                if float_compare(take, 0.0, precision_digits=prec) <= 0:
                    rline.quantity = 0.0
                    continue
                rline.quantity = sl.product_uom_id._compute_quantity(take, move.product_uom)
                wanted[sl.id] = want - take
                took = True
            if not took:
                continue
            action = wizard.action_create_returns()
            new_picking = self.env["stock.picking"].sudo().browse(action["res_id"])
            for move in new_picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            new_picking.message_post(body=_("Sotuvni tuzatish (%(order)s): %(reason)s", order=order.name,
                                            reason=self.reason))
            self._cst_validate(new_picking)
            pickings |= new_picking
        left = {k: v for k, v in wanted.items() if float_compare(v, 0.0, precision_digits=prec) > 0}
        if left:
            names = self.env["sale.order.line"].browse(list(left)).product_id.mapped("display_name")
            raise UserError(_("Qaytariladigan miqdor yetkazib berilganidan ko'p: %s", ", ".join(names)))
        return pickings

    def _cst_validate(self, picking):
        result = picking.with_context(
            skip_backorder=True, skip_sms=True, cst_skip_qty_sync=True, cst_no_auto_invoice=True,
            cst_skip_wh_control=True).button_validate()
        if isinstance(result, dict) and picking.state != "done":
            raise UserError(_("%s hujjatini tasdiqlab bo'lmadi.", picking.name))

    def _cst_drop_covered_moves(self, order):
        """Open delivery moves of lines whose order quantity has left already."""
        prec = self.env["decimal.precision"].precision_get("Product Unit")
        for picking in order.picking_ids.filtered(
                lambda p: p.picking_type_code == "outgoing" and p.state not in ("done", "cancel")):
            moves = picking.move_ids.filtered(
                lambda m: m.state not in ("done", "cancel") and m.sale_line_id and float_compare(
                    m.sale_line_id.qty_delivered, m.sale_line_id.product_uom_qty, precision_digits=prec) >= 0)
            if moves:
                moves._action_cancel()
            if all(m.state == "cancel" for m in picking.move_ids):
                picking.action_cancel()

    def _cst_ship_now(self, order, sale_lines):
        """The pieces added to lines that had left already: out of the
        warehouse now, the rest of a shared delivery stays open."""
        prec = self.env["decimal.precision"].precision_get("Product Unit")
        pickings = self.env["stock.picking"]
        ours = self.env["stock.move"]
        for sl in sale_lines:
            need = sl.product_uom_qty - sl.qty_delivered
            if float_compare(need, 0.0, precision_digits=prec) <= 0:
                continue
            moves = sl.move_ids.filtered(
                lambda m: m.state not in ("done", "cancel") and m.picking_code == "outgoing")
            for i, move in enumerate(moves):
                demand = move.product_uom._compute_quantity(move.product_uom_qty, sl.product_uom_id)
                take = need if i == len(moves) - 1 else min(need, demand)
                move.quantity = sl.product_uom_id._compute_quantity(take, move.product_uom)
                move.picked = True
                need -= take
                ours |= move
        for picking in ours.picking_id:
            picking.move_ids.filtered(lambda m: m.state not in ("done", "cancel") and m not in ours).write(
                {"quantity": 0.0, "picked": False})
            picking.message_post(body=_("Sotuvni tuzatish (%(order)s): %(reason)s", order=order.name,
                                        reason=self.reason))
            self._cst_validate(picking)
            pickings |= picking
        return pickings

    # ------------------------------------------------------------------ money
    def _cst_credit_invoiced(self, order, lines):
        """A credit note for the invoiced pieces of re-priced lines, at the
        price they were invoiced at (the order line's price before the change)."""
        vals = order._prepare_invoice()
        vals.update({
            "move_type": "out_refund",
            "invoice_origin": order.name,
            "ref": _("Narx tuzatish: %s", order.name),
            "invoice_line_ids": [
                Command.create(line.sale_line_id._prepare_invoice_line(quantity=line.sale_line_id.qty_invoiced))
                for line in lines],
        })
        credit = self.env["account.move"].sudo().with_company(order.company_id).create(vals)
        credit.action_post()
        return credit

    def _cst_settle_money(self, order, sale_lines, had_invoices):
        """Credit what came back, invoice what left (in an auto-invoicing
        company: only goods that left), then let the open documents meet."""
        prec = self.env["decimal.precision"].precision_get("Product Unit")
        auto = getattr(order.company_id, "cst_auto_invoice_sale", False)
        moves = self.env["account.move"]
        if not (had_invoices or auto):
            return moves  # never invoiced: the usual flow invoices the new numbers
        sale_lines.invalidate_recordset(["qty_invoiced", "qty_to_invoice", "qty_delivered"])
        minus = sale_lines.filtered(lambda l: float_compare(l.qty_to_invoice, 0.0, precision_digits=prec) < 0)
        plus = sale_lines.filtered(lambda l: float_compare(l.qty_to_invoice, 0.0, precision_digits=prec) > 0)
        if minus:
            moves |= order.with_context(cst_dispatch_sale_line_ids=minus.ids)._create_invoices(final=True)
        if plus:
            ctx = {"cst_dispatch_sale_line_ids": plus.ids}
            if auto:
                ctx["cst_auto_invoice"] = True  # only what has left
                plus = plus.filtered(lambda l: hasattr(l, "_cst_auto_qty") and float_compare(
                    l._cst_auto_qty(), 0.0, precision_digits=prec) > 0)
            if plus:
                moves |= order.with_context(**ctx)._create_invoices(final=True)
        moves = moves.filtered(lambda m: m.state == "draft")
        if moves:
            moves.action_post()
            if hasattr(order, "_cst_apply_advances"):
                order._cst_apply_advances(moves)
        self._cst_reconcile_open(order)
        return moves

    def _cst_reconcile_open(self, order):
        """The order's open invoices and credit notes settle each other."""
        lines = order.invoice_ids.filtered(lambda m: m.state == "posted").line_ids.filtered(
            lambda l: l.account_id.account_type == "asset_receivable" and not l.reconciled)
        for account in lines.account_id:
            group = lines.filtered(lambda l, a=account: l.account_id == a)
            if group.filtered(lambda l: l.amount_residual > 0) and group.filtered(lambda l: l.amount_residual < 0):
                try:
                    with self.env.cr.savepoint():
                        group.reconcile()
                except Exception as exc:  # noqa: BLE001 -- the balance is right either way
                    _logger.warning("sale correction %s: reconcile skipped: %s", order.name, exc)

    # ------------------------------------------------------------------ log
    def _cst_log(self, order, changes, amount_before, notes, pickings, invoices):
        def num(value):
            return f"{value:g}"
        rows = Markup("").join(
            Markup("<li>%s: %s</li>") % (line.product_id.display_name, line._cst_describe(num)) for line in changes)
        docs = ", ".join((pickings.mapped("name") + invoices.mapped("name")))
        body = Markup("<p><b>%s</b> %s</p><ul>%s</ul><p>%s</p>") % (
            _("Sotuv tuzatildi"), _("(%(user)s). Sabab: %(reason)s", user=self.env.user.name, reason=self.reason),
            rows, _("Summa: %(a)s → %(b)s", a=amount_before, b=order.amount_total))
        if notes:
            body += Markup("<p>%s</p>") % "; ".join(notes)
        if docs:
            body += Markup("<p>%s %s</p>") % (_("Hujjatlar:"), docs)
        order.message_post(body=body)


class CstSaleCorrectionLine(models.TransientModel):
    _name = "cst.sale.correction.line"
    _description = "Sotuvni tuzatish qatori"

    wizard_id = fields.Many2one("cst.sale.correction", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    sale_line_id = fields.Many2one("sale.order.line", string="Buyurtma qatori", readonly=True)
    product_id = fields.Many2one("product.product", string="Mahsulot", domain=[("sale_ok", "=", True)])
    cst_characteristic = fields.Char(related="product_id.cst_characteristic", string="Xarakteristika")
    uom_id = fields.Many2one("uom.uom", string="Birlik")
    delivered_qty = fields.Float(string="Chiqib ketgan", digits="Product Unit", readonly=True)
    invoiced_qty = fields.Float(string="Hisob-faktura", digits="Product Unit", readonly=True)
    old_qty = fields.Float(string="Eski miqdor", digits="Product Unit", readonly=True)
    old_price = fields.Float(string="Eski narx", digits="Product Price", readonly=True)
    old_discount = fields.Float(string="Eski chegirma %", digits="Discount", readonly=True)
    new_qty = fields.Float(string="Miqdor", digits="Product Unit")
    new_price = fields.Float(string="Narx", digits="Product Price")
    new_discount = fields.Float(string="Chegirma %", digits="Discount")
    subtotal_old = fields.Monetary(string="Eski summa", currency_field="currency_id", compute="_compute_subtotals")
    subtotal_new = fields.Monetary(string="Yangi summa", currency_field="currency_id", compute="_compute_subtotals")
    effect = fields.Char(string="Nima bo'ladi", compute="_compute_subtotals")

    @api.depends("old_qty", "old_price", "old_discount", "new_qty", "new_price", "new_discount", "delivered_qty")
    def _compute_subtotals(self):
        prec = self.env["decimal.precision"].precision_get("Product Unit")
        for line in self:
            line.subtotal_old = line.old_qty * line.old_price * (1 - (line.old_discount or 0.0) / 100.0)
            line.subtotal_new = line.new_qty * line.new_price * (1 - (line.new_discount or 0.0) / 100.0)
            bits = []
            back = line.delivered_qty - line.new_qty
            if line.sale_line_id and float_compare(back, 0.0, precision_digits=prec) > 0:
                bits.append(_("%g omborga qaytadi", back))
            more = line.new_qty - max(line.delivered_qty, 0.0)
            if float_compare(more, 0.0, precision_digits=prec) > 0 and (
                    not line.sale_line_id or float_compare(line.new_qty, line.old_qty, precision_digits=prec) > 0):
                bits.append(_("%g qo'shimcha chiqim", more))
            if line.sale_line_id and line._cst_price_changed():
                bits.append(_("narx qayta hisoblanadi"))
            line.effect = ", ".join(bits)

    @api.onchange("product_id")
    def _onchange_product_id(self):
        for line in self.filtered(lambda l: not l.sale_line_id and l.product_id):
            order = line.wizard_id.order_id
            line.uom_id = line.product_id.uom_id
            if order.pricelist_id:
                line.new_price = order.pricelist_id._get_product_price(line.product_id, line.new_qty or 1.0)
            else:
                line.new_price = line.product_id.lst_price

    def _cst_price_changed(self):
        self.ensure_one()
        digits = self.env["decimal.precision"].precision_get("Product Price")
        return float_compare(self.new_price, self.old_price, precision_digits=digits) != 0 or \
            float_compare(self.new_discount, self.old_discount, precision_digits=2) != 0

    def _cst_changed(self):
        self.ensure_one()
        prec = self.env["decimal.precision"].precision_get("Product Unit")
        if not self.sale_line_id:
            return bool(self.product_id) or not float_is_zero(self.new_qty, precision_digits=prec)
        return float_compare(self.new_qty, self.old_qty, precision_digits=prec) != 0 or self._cst_price_changed()

    def _cst_describe(self, num):
        self.ensure_one()
        bits = []
        if not self.sale_line_id:
            bits.append(_("yangi qator %(q)s × %(p)s", q=num(self.new_qty), p=num(self.new_price)))
        else:
            prec = self.env["decimal.precision"].precision_get("Product Unit")
            if float_compare(self.new_qty, self.old_qty, precision_digits=prec) != 0:
                bits.append(_("miqdor %(a)s → %(b)s", a=num(self.old_qty), b=num(self.new_qty)))
            if self._cst_price_changed():
                bits.append(_("narx %(a)s → %(b)s", a=num(self.old_price), b=num(self.new_price)))
                if self.new_discount != self.old_discount:
                    bits.append(_("chegirma %(a)s%% → %(b)s%%", a=num(self.old_discount), b=num(self.new_discount)))
        return ", ".join(bits)
