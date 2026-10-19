import logging

from markupsafe import Markup

from odoo import _, models
from odoo.tools import float_compare, float_is_zero

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        result = super()._action_done()
        if not self.env.context.get("cst_skip_qty_sync"):
            self.filtered(lambda p: p.state == "done" and p.picking_type_code == "outgoing"
                          and p.sale_id)._cst_sync_sale_qty()
        return result

    def _cst_sync_sale_qty(self):
        """A delivery validated on the ordinary Delivery form with a corrected
        quantity (less without a backorder, or more) makes the order say what
        actually left — the same rule the Jo'natish gate applies, so the
        order amount, debt and invoice follow the goods. While a backorder is
        open the rest is still coming and nothing changes."""
        prec = self.env["decimal.precision"].precision_get("Product Unit")
        for order in self.sale_id:
            todo = []
            for sl in self.move_ids.sale_line_id.filtered(lambda l: l.order_id == order):
                still_open = sl.move_ids.filtered(
                    lambda m: m.state not in ("done", "cancel") and m.picking_code == "outgoing")
                if still_open:
                    continue
                if float_compare(sl.qty_delivered, sl.product_uom_qty, precision_digits=prec) != 0:
                    todo.append(sl)
            if not todo:
                continue
            order = order.sudo()
            was_locked = order.locked
            if was_locked:
                order.action_unlock()
            changes = []
            for sl in todo:
                changes.append((sl.product_id.display_name, sl.product_uom_qty, sl.qty_delivered))
                # a quantity change re-runs the pricelist: keep the agreed price and discount
                sl.sudo().write({"product_uom_qty": sl.qty_delivered,
                                 "price_unit": sl.price_unit, "discount": sl.discount})
            posted = order.invoice_ids.filtered(lambda m: m.state == "posted" and m.move_type == "out_invoice")
            if posted and any(not float_is_zero(sl.qty_to_invoice, precision_digits=prec) for sl in todo):
                try:
                    with self.env.cr.savepoint():
                        order.with_context(cst_dispatch_sale_line_ids=[sl.id for sl in todo]) \
                            ._create_invoices(final=True).action_post()
                except Exception as exc:  # noqa: BLE001 — never block a delivery on accounting
                    self.env.invalidate_all()
                    _logger.warning("delivery qty sync %s: difference invoice failed: %s", order.name, exc)
            if was_locked:
                order.action_lock()
            body = Markup("<p>%s</p><ul>%s</ul>") % (
                _("Omborchi yetkazib berishda miqdorni o'zgartirdi — buyurtma yangilandi:"),
                Markup("").join(Markup("<li>%s: %s → %s</li>") % (name, f"{old:g}", f"{new:g}")
                                for name, old, new in changes))
            order.message_post(body=body)
