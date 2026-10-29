import logging

from odoo import _, models

_logger = logging.getLogger(__name__)


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    def _cst_is_goods(self):
        return not self.display_type and not self.is_downpayment and self.product_id.type == "consu"

    def _cst_auto_qty(self):
        """What an automatic invoice takes of this line: the goods that have
        left and are not invoiced yet (the order quantity may be invoiced
        already, or not have left at all); a service goes with the goods."""
        self.ensure_one()
        if self.display_type or self.is_downpayment:
            return 0.0
        uom = self.product_uom_id
        if uom.compare(self.qty_to_invoice, 0.0) <= 0:
            return 0.0
        if self.product_id.type == "consu":
            left = self.qty_delivered - self.qty_invoiced
            return max(min(self.qty_to_invoice, left), 0.0)
        return self.qty_to_invoice

    def _prepare_invoice_line(self, **optional_values):
        res = super()._prepare_invoice_line(**optional_values)
        if self.env.context.get("cst_auto_invoice") and not self.display_type and not self.is_downpayment:
            res["quantity"] = self._cst_auto_qty()
        return res


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _cst_auto_invoice_lines(self):
        """Lines an automatic invoice takes now; none while no goods have left."""
        self.ensure_one()
        lines = self.order_line.filtered(
            lambda l: not l.display_type and not l.is_downpayment
            and l.product_uom_id.compare(l._cst_auto_qty(), 0.0) > 0)
        if not any(l._cst_is_goods() for l in lines):
            return self.order_line.browse()
        return lines

    def _get_invoiceable_lines(self, final=False):
        lines = super()._get_invoiceable_lines(final=final)
        if self.env.context.get("cst_auto_invoice"):
            wanted = self._cst_auto_invoice_lines()
            lines = lines.filtered(lambda l: l.display_type or l.is_downpayment or l in wanted) if wanted \
                else lines.browse()
        return lines

    def _cst_auto_invoice(self, date=None, apply_advances=True):
        """Invoice and post what has left the warehouse and is not invoiced yet.

        Never blocks the delivery that calls it: a failure is written on the
        order for the accountant. ``apply_advances``: the client's money that
        is still free (a prepayment) closes the new invoice."""
        invoices = self.env["account.move"]
        for order in self.sudo():
            company = order.company_id
            if order.state != "sale" or not company.cst_auto_invoice_sale:
                continue
            if not order._cst_auto_invoice_lines():
                continue
            order = order.with_company(company)
            try:
                with self.env.cr.savepoint():
                    moves = order.with_context(cst_auto_invoice=True)._create_invoices(final=True)
                    moves = moves.filtered(lambda m: m.state == "draft")
                    if date:
                        moves.write({"invoice_date": date})
                    moves.action_post()
            except Exception as exc:  # noqa: BLE001 — the goods have left; accounting can follow
                self.env.invalidate_all()
                _logger.warning("auto invoice %s failed: %s", order.name, exc)
                order.message_post(body=_(
                    "Avtomatik hisob-faktura yaratilmadi (%s). Buxgalter qo'lda yaratsin.", exc))
                continue
            invoices |= moves
            if apply_advances:
                order._cst_apply_advances(moves)
        return invoices

    def _cst_apply_advances(self, invoices):
        """The client's free money (prepayments, credit notes) closes the new
        invoice, oldest first — through the kassa engine, so the settlement
        shows in the kassa like any other."""
        self.ensure_one()
        invoices = invoices.filtered(lambda m: m.move_type == "out_invoice" and m.state == "posted")
        if not invoices:
            return
        Allocation = self.env["cst.kassa.allocation"].sudo()
        partner = self.partner_id.commercial_partner_id
        company = self.company_id
        credit = Allocation._cst_credit_lines(partner, company).filtered(
            lambda l: self._cst_money_for(l, self.currency_id))
        if not credit:
            return
        try:
            with self.env.cr.savepoint():
                Allocation._cst_allocate(partner, company, credit_lines=credit,
                                         targets=[(False, self, self.env["account.move"])])
        except Exception as exc:  # noqa: BLE001
            self.env.invalidate_all()
            _logger.warning("auto invoice %s: advance not applied: %s", self.name, exc)
            return
        self.env["cst.kassa.partner.balance"]._cst_refresh(partner)

    def _cst_money_for(self, line, currency):
        """May this free money pay a debt in ``currency``? Not when the
        cashier said it pays the client's debt in another currency."""
        op = self.env["cst.kassa.operation"].sudo().search(
            [("payment_id.move_id", "=", line.move_id.id)], limit=1)
        return not (op and op.debt_currency_id and op.debt_currency_id != currency)

    def _cst_kassa_invoice(self):
        """A payment settles the goods that have left, not the whole order:
        the money for the rest stays as advance until the goods leave."""
        if not self.company_id.cst_auto_invoice_sale or not any(
                l._cst_is_goods() for l in self.order_line):
            return super()._cst_kassa_invoice()
        return self._cst_auto_invoice(apply_advances=False)
