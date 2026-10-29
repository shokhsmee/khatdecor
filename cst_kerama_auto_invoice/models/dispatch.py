from odoo import fields, models


class CstDispatch(models.Model):
    _inherit = "cst.dispatch"

    def _cst_difference_lines(self, sale_lines):
        lines = super()._cst_difference_lines(sale_lines)
        if self.company_id.cst_auto_invoice_sale:
            # what passed the gate was invoiced by the delivery itself; only an
            # order made smaller than its invoice is credited here
            lines = lines.filtered(lambda sl: sl.product_uom_id.compare(sl.qty_to_invoice, 0.0) < 0)
        return lines

    def _cst_apply(self):
        order = self.sale_order_id.sudo()
        before = order.invoice_ids
        result = super()._cst_apply()
        new = order.invoice_ids - before
        if new:
            self.sudo().invoice_ids = [fields.Command.link(m.id) for m in new]
        return result
