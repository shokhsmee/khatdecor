from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    # Cancelling a sale order also cancels its open deliveries and walks the
    # upstream chain (purchase lines, batches) — records a salesperson has no
    # right to. Odoo itself does that walk as superuser when an ordered quantity
    # decreases; do the same while a sale order is being cancelled.

    def _log_activity_get_documents(self, orig_obj_changes, stream_field, stream, groupby_method=False):
        if self.env.context.get("cst_cancel_sudo_documents"):
            self = self.sudo()
        return super()._log_activity_get_documents(
            orig_obj_changes, stream_field, stream, groupby_method=groupby_method)

    def action_cancel(self):
        if self.env.context.get("cst_cancel_sudo_documents"):
            self = self.sudo()
        return super().action_cancel()
