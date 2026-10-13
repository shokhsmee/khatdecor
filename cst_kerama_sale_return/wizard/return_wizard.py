from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

# Invoice payment states that mean nothing is left to collect.
_SETTLED_STATES = ("paid", "in_payment", "reversed")


class SaleReturnWizard(models.TransientModel):
    _name = "cst.sale.return.wizard"
    _description = "Sales Order Return / Refund"

    order_id = fields.Many2one(
        "sale.order",
        string="Sales Order",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(related="order_id.company_id")
    partner_id = fields.Many2one(related="order_id.partner_id", string="Customer")
    order_currency_id = fields.Many2one(
        related="order_id.currency_id", string="Currency"
    )

    # ------------------------------------------------------------------
    # Payment group
    # ------------------------------------------------------------------
    paid_total = fields.Monetary(
        string="To'langan summa",
        compute="_compute_paid_total",
        currency_field="order_currency_id",
        help="Total amount the customer has already paid on this order.",
    )
    refund_amount = fields.Monetary(
        string="Qaytariladigan summa",
        compute="_compute_refund_amount",
        store=True,
        precompute=True,
        readonly=False,
        currency_field="order_currency_id",
        help="Amount of money to refund to the customer. Defaults to the value "
        "of the returned products (taxes included) but can be adjusted.",
    )
    payment_date = fields.Date(
        string="Sana",
        required=True,
        default=fields.Date.context_today,
    )
    available_journal_ids = fields.Many2many(
        "account.journal",
        compute="_compute_available_journal_ids",
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Jurnal",
        compute="_compute_journal_id",
        store=True,
        precompute=True,
        readonly=False,
        domain="[('id', 'in', available_journal_ids)]",
        help="Payment journal used to refund the money to the customer. Leave "
        "the refund amount at 0 to only issue a credit note without paying.",
    )
    communication = fields.Char(string="Izoh")

    # ------------------------------------------------------------------
    # Products group
    # ------------------------------------------------------------------
    line_ids = fields.One2many(
        "cst.sale.return.line",
        "wizard_id",
        string="Mahsulotlar",
        compute="_compute_line_ids",
        store=True,
        precompute=True,
        readonly=False,
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    def _get_available_journals(self, company):
        return self.env["account.journal"].search(
            [
                *self.env["account.journal"]._check_company_domain(company),
                ("type", "in", ("bank", "cash")),
            ]
        )

    @api.depends("order_id")
    def _compute_available_journal_ids(self):
        for wizard in self:
            company = wizard.order_id.company_id or self.env.company
            wizard.available_journal_ids = wizard._get_available_journals(company)

    @api.depends("order_id")
    def _compute_journal_id(self):
        for wizard in self:
            company = wizard.order_id.company_id or self.env.company
            available = wizard._get_available_journals(company)
            if wizard.journal_id and wizard.journal_id in available:
                continue
            wizard.journal_id = available[:1]

    @api.depends("order_id")
    def _compute_paid_total(self):
        for wizard in self:
            order = wizard.order_id
            total = 0.0
            invoices = order.invoice_ids.filtered(
                lambda m: m.move_type == "out_invoice" and m.state == "posted"
            )
            for move in invoices:
                paid = move.amount_total - move.amount_residual
                if move.currency_id != order.currency_id:
                    paid = move.currency_id._convert(
                        paid,
                        order.currency_id,
                        order.company_id,
                        move.invoice_date or fields.Date.context_today(wizard),
                    )
                total += paid
            wizard.paid_total = total

    @api.depends("order_id")
    def _compute_line_ids(self):
        for wizard in self:
            commands = [Command.clear()]
            for line in wizard.order_id.order_line:
                if line.display_type or not line.product_id:
                    continue
                if line.product_uom_qty <= 0:
                    continue
                commands.append(
                    Command.create(
                        {
                            "sale_line_id": line.id,
                            "return_qty": 0.0,
                        }
                    )
                )
            wizard.line_ids = commands

    @api.depends("line_ids.price_total")
    def _compute_refund_amount(self):
        for wizard in self:
            wizard.refund_amount = sum(wizard.line_ids.mapped("price_total"))

    # ------------------------------------------------------------------
    # Action
    # ------------------------------------------------------------------
    def action_confirm_return(self):
        """Create the credit note, refund the payment and return the stock."""
        self.ensure_one()
        return_lines = self.line_ids.filtered(lambda l: l.return_qty > 0)
        if not return_lines:
            raise UserError(_("Please set a return quantity on at least one product."))

        for line in return_lines:
            if line.return_qty > line.ordered_qty:
                raise UserError(
                    _(
                        "You cannot return more than was ordered for %(product)s "
                        "(ordered: %(ordered)s, return: %(ret)s).",
                        product=line.product_id.display_name,
                        ordered=line.ordered_qty,
                        ret=line.return_qty,
                    )
                )

        credit_note = self._create_credit_note(return_lines)
        if self.refund_amount > 0 and self.journal_id:
            self._refund_payment(credit_note)
        self._return_to_stock(return_lines)

        return {
            "name": _("Qaytarish (kredit-nota)"),
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": credit_note.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    # ------------------------------------------------------------------
    # Credit note
    # ------------------------------------------------------------------
    def _create_credit_note(self, return_lines):
        order = self.order_id
        move_vals = order._prepare_invoice()
        move_vals.update(
            {
                "move_type": "out_refund",
                "invoice_origin": order.name,
                "ref": _("Qaytarish: %(order)s", order=order.name),
                "invoice_line_ids": [
                    Command.create(
                        line.sale_line_id._prepare_invoice_line(
                            quantity=line.return_qty
                        )
                    )
                    for line in return_lines
                ],
            }
        )
        credit_note = self.env["account.move"].create(move_vals)
        credit_note.action_post()
        return credit_note

    # ------------------------------------------------------------------
    # Refund payment
    # ------------------------------------------------------------------
    def _refund_payment(self, credit_note):
        register = (
            self.env["account.payment.register"]
            .with_context(
                active_model="account.move",
                active_ids=credit_note.ids,
            )
            .create(
                {
                    "journal_id": self.journal_id.id,
                    "currency_id": self.order_currency_id.id,
                    "amount": self.refund_amount,
                    "payment_date": self.payment_date,
                    "group_payment": True,
                    "communication": self.communication or False,
                }
            )
        )
        payments = register._create_payments()
        # "Tasdiqlangan": take the payment out of the *In Process* (waiting
        # approval) state so the refund is confirmed straight away.
        payments.filtered(lambda p: p.state == "in_process").action_validate()
        return payments

    # ------------------------------------------------------------------
    # Stock return
    # ------------------------------------------------------------------
    def _return_to_stock(self, return_lines):
        order = self.order_id
        # Remaining quantity to send back, per product (in the order line UoM).
        remaining = {}
        for line in return_lines:
            remaining[line.product_id] = (
                remaining.get(line.product_id, 0.0) + line.return_qty
            )

        done_pickings = order.picking_ids.filtered(
            lambda p: p.picking_type_code == "outgoing" and p.state == "done"
        )
        for picking in done_pickings:
            if all(qty <= 0 for qty in remaining.values()):
                break
            if not picking._can_return():
                continue

            wizard = self.env["stock.return.picking"].create(
                {"picking_id": picking.id}
            )
            took_any = False
            for rline in wizard.product_return_moves:
                product = rline.product_id
                want = remaining.get(product, 0.0)
                if want <= 0:
                    rline.quantity = 0.0
                    continue
                available = rline.move_id.quantity
                take = min(want, available)
                rline.quantity = take
                remaining[product] = want - take
                if take > 0:
                    took_any = True

            if not took_any:
                continue

            action = wizard.action_create_returns()
            new_picking = self.env["stock.picking"].browse(action["res_id"])
            self._validate_return_picking(new_picking)

        # Whatever is left was ordered but never delivered (the delivery is
        # still draft/ready and only *reserving* the goods, so the forecast
        # keeps counting it as outgoing). Release that pending demand so the
        # stock no longer shows as leaving the warehouse.
        if any(qty > 0 for qty in remaining.values()):
            self._release_pending_delivery(remaining)

    def _release_pending_delivery(self, remaining):
        """Reduce/cancel the outstanding (not done) delivery for returned qty."""
        order = self.order_id
        pending = order.picking_ids.filtered(
            lambda p: p.picking_type_code == "outgoing"
            and p.state not in ("done", "cancel")
        )
        for picking in pending:
            for move in picking.move_ids:
                if move.state in ("done", "cancel"):
                    continue
                want = remaining.get(move.product_id, 0.0)
                if want <= 0:
                    continue
                reduce_by = min(want, move.product_uom_qty)
                remaining[move.product_id] = want - reduce_by
                new_qty = move.product_uom_qty - reduce_by
                move._do_unreserve()
                if move.product_uom.is_zero(new_qty):
                    move._action_cancel()
                else:
                    move.product_uom_qty = new_qty
                    move._action_assign()

    def _validate_return_picking(self, picking):
        """Force the return picking to *Done* without intermediate wizards."""
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        result = picking.with_context(
            skip_backorder=True,
            skip_sms=True,
        ).button_validate()
        # button_validate may return a backorder/confirmation wizard action; if
        # the picking is already done we simply ignore it.
        if isinstance(result, dict) and picking.state != "done":
            wiz_model = result.get("res_model")
            if wiz_model == "stock.backorder.confirmation":
                self.env[wiz_model].browse(result["res_id"]).process_cancel_backorder()
        return picking


class SaleReturnLine(models.TransientModel):
    _name = "cst.sale.return.line"
    _description = "Sales Order Return Line"

    wizard_id = fields.Many2one(
        "cst.sale.return.wizard",
        required=True,
        ondelete="cascade",
    )
    sale_line_id = fields.Many2one(
        "sale.order.line",
        string="Order Line",
        required=True,
        readonly=True,
    )
    product_id = fields.Many2one(
        related="sale_line_id.product_id",
        string="Mahsulot",
        readonly=True,
    )
    currency_id = fields.Many2one(related="wizard_id.order_currency_id")
    ordered_qty = fields.Float(
        related="sale_line_id.product_uom_qty",
        string="Sotilgan miqdor",
        readonly=True,
    )
    delivered_qty = fields.Float(
        related="sale_line_id.qty_delivered",
        string="Yetkazib berilgan",
        readonly=True,
    )
    return_qty = fields.Float(string="Qaytariladigan miqdor", default=0.0)
    uom_id = fields.Many2one(
        related="sale_line_id.product_uom_id",
        string="Birlik",
        readonly=True,
    )
    price_unit = fields.Float(related="sale_line_id.price_unit", readonly=True)
    discount = fields.Float(related="sale_line_id.discount", readonly=True)
    price_total = fields.Monetary(
        string="Summa",
        compute="_compute_price_total",
        currency_field="currency_id",
    )

    @api.depends("return_qty", "price_unit", "discount", "sale_line_id.tax_ids")
    def _compute_price_total(self):
        for line in self:
            price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            taxes = line.sale_line_id.tax_ids.compute_all(
                price,
                line.currency_id,
                line.return_qty,
                product=line.product_id,
                partner=line.sale_line_id.order_id.partner_shipping_id,
            )
            line.price_total = taxes["total_included"]
