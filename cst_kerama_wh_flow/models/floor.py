from odoo import _, api, models
from odoo.exceptions import UserError


class CstProductionFloor(models.AbstractModel):
    _inherit = "cst.production.floor"

    @api.model
    def create_order(self, shift_id, product_id, qty, workcenter_id=None, employee_ids=None, start=True, materials=None,
                     bom_id=None):
        shift = self.env["cst.production.shift"].browse(int(shift_id))
        return super(CstProductionFloor, self.with_context(
            cst_flow_department_id=shift.department_id.id)).create_order(
            shift_id, product_id, qty, workcenter_id=workcenter_id, employee_ids=employee_ids,
            start=start, materials=materials, bom_id=bom_id)

    @api.model
    def bom_materials(self, product_id, qty, bom_id=None, department_id=None):
        # «Omborda» of the new-order dialog: the stock of the department that
        # makes it, not of whatever line the bill's operation happens to sit on
        floor = self.with_context(cst_flow_department_id=int(department_id)) if department_id else self
        return super(CstProductionFloor, floor).bom_materials(product_id, qty, bom_id=bom_id, department_id=department_id)

    @api.model
    def search_products(self, query, limit=20, department_id=None):
        if not department_id:
            return super().search_products(query, limit)
        warehouse = self._department(department_id)._cst_warehouse()
        return self.env["cst.mo.builder"].mo_search_products(query, limit, warehouse_id=warehouse.id)

    def _before_undo(self, production):
        # pieces already on their way to the next warehouse come back first;
        # once received there they are that warehouse's stock -- stop
        output = self.env["stock.picking"].sudo().search([
            ("cst_production_id", "=", production.id), ("cst_flow_kind", "=", "output"), ("state", "!=", "cancel")])
        received = output.filtered(lambda p: p.state == "done")
        if received:
            raise UserError(_("%(mo)s: tayyor mahsulot %(pick)s bilan boshqa omborga o'tkazilgan va qabul qilingan, "
                              "o'chirib bo'lmaydi.", mo=production.name, pick=", ".join(received.mapped("name"))))
        if output:
            output.action_cancel()
        return super()._before_undo(production)

    def _materials_for(self, production, department):
        warehouse = production.location_src_id.warehouse_id or department._cst_warehouse()
        rows = []
        for move in production.move_raw_ids.filtered(lambda m: m.state not in ("done", "cancel")):
            product = move.product_id
            # what this order still lacks: its own reservation counts as covered
            need = move.product_uom._compute_quantity(max(move.product_uom_qty - move.quantity, 0.0), product.uom_id)
            free = product.with_context(warehouse_id=warehouse.id).free_qty
            rows.append({"id": product.id, "product": product.cst_base_name(),
                         "characteristic": product.cst_characteristic or "",
                         "needed": need, "free": free, "uom": product.uom_id.name,
                         "ok": product.uom_id.compare(free, need) >= 0 or need <= 0})
        return rows

    def _materials(self, department, shift):
        productions = shift.line_ids.filtered(lambda l: l.state != "done").production_id if shift \
            else self.env["mrp.production"]
        if not productions:
            productions = department._pending_workorders()[:5].production_id
        warehouse = department._cst_warehouse()
        needs = {}
        for move in productions.move_raw_ids.filtered(lambda m: m.state not in ("done", "cancel")):
            product = move.product_id
            need = move.product_uom._compute_quantity(max(move.product_uom_qty - move.quantity, 0.0), product.uom_id)
            entry = needs.setdefault(product.id, {"product": product, "needed": 0.0})
            entry["needed"] += need
        rows = []
        for entry in needs.values():
            product = entry["product"]
            free = product.with_context(warehouse_id=warehouse.id).free_qty
            rows.append({
                "id": product.id, "product": product.cst_base_name(),
                "characteristic": product.cst_characteristic or "",
                "needed": entry["needed"], "free": free, "uom": product.uom_id.name,
                "ok": product.uom_id.compare(free, entry["needed"]) >= 0,
            })
        rows.sort(key=lambda r: (r["ok"], r["product"]))
        return rows
