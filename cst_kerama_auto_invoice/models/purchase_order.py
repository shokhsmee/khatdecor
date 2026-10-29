import logging

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    def _cst_auto_qty(self):
        """What an automatic bill takes of this line: the goods received and
        not billed yet (whatever the product's bill control says)."""
        self.ensure_one()
        if self.display_type:
            return 0.0
        uom = self.product_uom_id
        if uom.compare(self.qty_to_invoice, 0.0) <= 0:
            return 0.0
        if self.product_id.type == "consu":
            return max(min(self.qty_to_invoice, self.qty_received - self.qty_invoiced), 0.0)
        return self.qty_to_invoice

    def _prepare_account_move_line(self, move=False):
        res = super()._prepare_account_move_line(move=move)
        if self.env.context.get("cst_auto_invoice") and not self.display_type:
            res["quantity"] = self._cst_auto_qty()
        return res


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def _cst_auto_bill(self, date=None):
        """Bill and post what has been received and not billed yet; the
        supplier's prepayment closes it. Never blocks the receipt."""
        bills = self.env["account.move"]
        for po in self.sudo():
            company = po.company_id
            if po.state not in ("purchase", "done") or not company.cst_auto_invoice_purchase:
                continue
            goods = po.order_line.filtered(lambda l: l.product_id.type == "consu")
            if not any(l.product_uom_id.compare(l._cst_auto_qty(), 0.0) > 0 for l in goods):
                continue
            po = po.with_company(company)
            before = po.invoice_ids
            try:
                with self.env.cr.savepoint():
                    po.with_context(cst_auto_invoice=True).action_create_invoice()
                    new = (po.invoice_ids - before).filtered(lambda m: m.state == "draft")
                    new.invoice_line_ids.filtered(
                        lambda l: l.display_type == "product" and l.product_uom_id.compare(l.quantity, 0.0) == 0
                    ).unlink()
                    empty = new.filtered(lambda m: not m.invoice_line_ids.filtered(
                        lambda l: l.display_type == "product"))
                    empty.unlink()
                    new = new - empty
                    new.write({"invoice_date": date or fields.Date.context_today(self)})
                    new.action_post()
            except Exception as exc:  # noqa: BLE001 — the goods are in; accounting can follow
                self.env.invalidate_all()
                _logger.warning("auto bill %s failed: %s", po.name, exc)
                po.message_post(body=_(
                    "Avtomatik schyot (vendor bill) yaratilmadi (%s). Buxgalter qo'lda yaratsin.", exc))
                continue
            bills |= new
            self.env["account.move"]._cst_match_payable(new.partner_id.commercial_partner_id, company)
        return bills
