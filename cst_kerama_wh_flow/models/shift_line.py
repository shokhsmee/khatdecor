from odoo import _, api, models
from odoo.exceptions import UserError


class CstProductionShiftLine(models.Model):
    _inherit = "cst.production.shift.line"

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        # the department that takes the order's last operation is where it is
        # made: an order raised elsewhere (Preslash 1 in the bill, run on an
        # automatic line of Янги пресс) follows it while nothing has moved yet
        for line in lines.filtered(lambda l: l.is_final_operation and l.production_id):
            department = line.department_id
            production = line.production_id
            if department.warehouse_id and production.cst_flow_department_id != department:
                production._cst_align_warehouse(department)
        return lines

    def _post_output(self):
        result = super()._post_output()
        if self.is_final_operation:
            self.production_id._cst_forward_output()
        return result

    # «Tuzatish» of a booked result: the output warehouse leg
    def _cst_forward_target(self):
        """(source location, output warehouse) when this order's output is
        sent on automatically, else (None, None) -- same rules as the forward."""
        production = self.production_id
        department = production._cst_flow_department()
        if not department or not department.cst_auto_forward or not department.output_warehouse_id:
            return None, None
        source = production.location_dest_id
        target = department.output_warehouse_id
        if not source.warehouse_id or source.warehouse_id == target:
            return None, None
        if production._cst_used_in_department(production.product_id, department):
            return None, None
        return source, target

    def _cst_correction_pull_back(self, rows):
        result = super()._cst_correction_pull_back(rows)
        source, target = self._cst_forward_target()
        if not source:
            return result
        production = self.production_id
        sent = self.env["stock.move"].sudo().search([
            ("cst_forward_production_id", "=", production.id), ("state", "=", "done")])
        back = []
        for product, qty in rows:
            forwarded = sum(m.product_uom._compute_quantity(m.quantity, product.uom_id)
                            for m in sent.filtered(lambda m, p=product: m.product_id == p))
            qty = min(qty, forwarded)
            if product.uom_id.compare(qty, 0.0) > 0:
                back.append((product, qty))
        if not back:
            return result
        picking = self.env["stock.picking"].sudo().create({
            "picking_type_id": target.int_type_id.id,
            "location_id": target.lot_stock_id.id,
            "location_dest_id": source.id,
            "origin": _("Tuzatish: %(mo)s · %(shift)s", mo=production.name, shift=self.shift_id.name),
            "company_id": production.company_id.id,
            "cst_production_id": production.id,
            "move_ids": [(0, 0, {
                "product_id": product.id, "product_uom": product.uom_id.id,
                "product_uom_qty": product.uom_id.round(qty),
                "location_id": target.lot_stock_id.id, "location_dest_id": source.id,
                "company_id": production.company_id.id,
            }) for product, qty in back],
        })
        picking.action_confirm()
        picking.action_assign()
        complete = all(m.product_uom.compare(m.quantity, m.product_uom_qty) >= 0 for m in picking.move_ids)
        if not complete or not production._cst_validate_quietly(picking):
            raise UserError(_(
                "%(wh)s omborida tuzatish uchun yetarli mahsulot yo'q (sotilgan yoki ko'chirilgan bo'lishi mumkin): %(rows)s.",
                wh=target.display_name,
                rows=", ".join("%s × %g" % (p.display_name, q) for p, q in back)))
        production.message_post(body=_("Tuzatish: %(picking)s bilan %(wh)s'dan qaytarildi.",
                                       picking=picking._get_html_link(), wh=target.display_name))
        return result

    def _cst_correction_push(self, rows):
        result = super()._cst_correction_push(rows)
        source, target = self._cst_forward_target()
        if source:
            self.production_id._cst_make_transfer(source.warehouse_id, source, target.lot_stock_id, rows, "output")
        return result
