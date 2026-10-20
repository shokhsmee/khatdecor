from odoo import models


class CstProductionFloor(models.AbstractModel):
    _inherit = "cst.production.floor"

    def _cst_material_status(self, productions):
        """{mo id: status} for orders still to be made, the same three colours as
        the planning screen: what the order still lacks is in its own warehouse
        (green), somewhere else in the company (yellow, a transfer is needed), or
        nowhere (red)."""
        productions = productions.filtered(lambda p: p.state not in ("done", "cancel"))
        missing, components = {}, self.env["product.product"]
        for mo in productions:
            need = {}
            for move in mo.move_raw_ids.filtered(lambda m: m.state not in ("done", "cancel") and m.product_id.is_storable):
                uom = move.product_id.uom_id
                left = move.product_uom._compute_quantity(max(move.product_uom_qty - move.quantity, 0.0), uom)
                if uom.compare(left, 0.0) > 0:
                    need[move.product_id] = need.get(move.product_id, 0.0) + left
                    components |= move.product_id
            missing[mo.id] = need
        Board = self.env["cst.production.request.board"]
        free = {}

        def free_in(warehouse):
            if warehouse.id not in free:
                free[warehouse.id] = Board._free_map(components, warehouse)
            return free[warehouse.id]

        result = {}
        for mo in productions:
            need = missing[mo.id]
            if not need:
                result[mo.id] = "ok"
                continue
            here_wh = mo.picking_type_id.warehouse_id
            others = Board._company_warehouses(mo.company_id) - here_wh
            status = "ok"
            for product, qty in need.items():
                here = max(free_in(here_wh).get(product.id, 0.0), 0.0) if here_wh else 0.0
                if product.uom_id.compare(here, qty) >= 0:
                    continue
                elsewhere = sum(max(free_in(wh).get(product.id, 0.0), 0.0) for wh in others)
                if product.uom_id.compare(here + elsewhere, qty) >= 0:
                    status = "move"
                else:
                    status = "short"
                    break
            result[mo.id] = status
        return result

    def _cst_request_info(self, row, mo, status):
        request = mo.cst_request_id
        row["urgent"] = mo.priority == "1"
        row["request"] = request.name or ""
        row["partner"] = request.partner_id.name or ""
        row["mat_status"] = status or ""
        labels = {"ok": self.env._("Xomashyo yetarli"), "move": self.env._("O'tkazma kerak"),
                  "short": self.env._("Xomashyo yetmaydi")}
        row["mat_label"] = labels.get(status, "")

    def _queue(self, department, shift):
        rows = super()._queue(department, shift)
        productions = self.env["mrp.production"].browse({row["mo_id"] for row in rows})
        status = self._cst_material_status(productions)
        for row in rows:
            mo = productions.browse(row["mo_id"])
            self._cst_request_info(row, mo, status.get(mo.id))
        return rows

    def _shift_data(self, shift):
        data = super()._shift_data(shift)
        if shift and data and data.get("lines"):
            productions = shift.line_ids.filtered(lambda l: l.state in ("todo", "progress", "paused")).production_id
            status = self._cst_material_status(productions)
            for row in data["lines"]:
                mo = self.env["mrp.production"].browse(row["mo_id"])
                if row.get("state") not in ("todo", "progress", "paused"):
                    status_row = ""
                else:
                    status_row = status.get(mo.id)
                self._cst_request_info(row, mo, status_row)
        return data
