"""One way to raise a manufacturing order from a screen.

The Shop Floor («Yangi buyurtma») and the Project Hub («Ishlab chiqarish
yaratish») ask the same three questions: which product, how much, and with
what. The answers are worked out here once, so both screens show the same
list of products, the same exploded bill of materials against free stock,
and the same operations with the lines that may run them.

Nothing here touches a bill of materials: a component dropped, a quantity
typed or an operation unticked applies to the order being created only.
"""
import re

from odoo import _, api, models
from odoo.exceptions import UserError

from .floor import skeleton


class CstMoBuilder(models.AbstractModel):
    _name = "cst.mo.builder"
    _description = "Ishlab chiqarish buyurtmasi ustasi"

    # ------------------------------------------------------------------ helpers
    @api.model
    def _mo_company(self, company=None):
        return company or self.env.company

    @api.model
    def _mo_warehouse(self, company=None, warehouse_id=None):
        if warehouse_id:
            warehouse = self.env["stock.warehouse"].browse(int(warehouse_id)).exists()
            if warehouse:
                return warehouse
        company = self._mo_company(company)
        return self.env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)

    @api.model
    def _mo_bom(self, product, company=None):
        company = self._mo_company(company or product.company_id)
        bom = self.env["mrp.bom"]._bom_find(product, company_id=company.id).get(product)
        if not bom:
            raise UserError(_("«%s» uchun texkarta (BoM) yo'q.", product.display_name))
        return bom

    @api.model
    def _mo_free_qty(self, product, warehouse):
        return product.with_context(warehouse_id=warehouse.id).free_qty if warehouse else product.free_qty

    # ------------------------------------------------------------------ reads
    @api.model
    def mo_products(self, company=None, workcenters=None):
        """One row per variant of every product that has a bill of materials.

        ``workcenters`` narrows the list to products a given set of lines can
        actually make; without it every product with a bill is listed.
        """
        company = self._mo_company(company)
        domain = [("active", "=", True), ("type", "=", "normal"),
                  ("company_id", "in", (company.id, False))]
        if workcenters:
            domain.append(("operation_ids.workcenter_id", "in", workcenters.ids))
        rows, seen = [], set()
        for bom in self.env["mrp.bom"].search(domain).sorted(lambda b: (b.product_tmpl_id.name or "", b.id)):
            variants = bom.product_id or bom.product_tmpl_id.product_variant_ids.filtered("active")
            for variant in variants.filtered(lambda v: not v.cst_is_second_grade):
                if variant.id in seen:
                    continue
                seen.add(variant.id)
                rows.append({
                    "id": variant.id,
                    "name": variant.cst_base_name(),
                    "characteristic": variant.cst_characteristic or "",
                    "uom": variant.uom_id.name,
                    "code": variant.default_code or "",
                    "operations": ", ".join(bom.operation_ids.sorted("sequence").mapped("name")),
                    "key": skeleton("%s %s %s" % (variant.default_code or "", variant.display_name,
                                                  variant.cst_characteristic or "")),
                })
        return rows

    @api.model
    def mo_workcenters(self):
        return [{"id": wc.id, "name": wc.name, "department": wc.cst_department_id.code or ""}
                for wc in self.env["mrp.workcenter"].search([])]

    @api.model
    def mo_options(self, company_id=None):
        company = self.env["res.company"].browse(int(company_id)) if company_id else self.env.company
        return {"products": self.mo_products(company), "workcenters": self.mo_workcenters()}

    @api.model
    def mo_materials(self, product, qty, warehouse=None, bom=None):
        """The exploded bill of materials for ``qty``, against free stock;
        ``bom`` picks one of several bills (70/75/80 гр), else the first."""
        bom = bom or self.env["mrp.bom"]._bom_find(
            product, company_id=(product.company_id or self.env.company).id).get(product)
        if not bom:
            return []
        warehouse = warehouse if warehouse is not None else self._mo_warehouse(product.company_id)
        factor = product.uom_id._compute_quantity(float(qty or 0), bom.product_uom_id) / (bom.product_qty or 1.0)
        rows = []
        for bom_line, data in bom.explode(product, factor)[1]:
            component = bom_line.product_id
            need = bom_line.product_uom_id._compute_quantity(data["qty"], component.uom_id)
            free = self._mo_free_qty(component, warehouse)
            rows.append({"id": component.id, "product": component.cst_base_name(),
                         "characteristic": component.cst_characteristic or "",
                         "needed": need, "free": free, "uom": component.uom_id.name,
                         "ok": component.uom_id.compare(free, need) >= 0})
        return rows

    @api.model
    def mo_operations(self, bom):
        """Every operation of the bill with the lines that may run it."""
        rows = []
        for operation in bom.operation_ids.sorted(lambda o: (o.sequence, o.id)):
            options = operation.workcenter_id | operation.workcenter_id.alternative_workcenter_ids
            rows.append({
                "id": operation.id,
                "name": operation.name,
                "workcenter_id": operation.workcenter_id.id,
                "department": operation.workcenter_id.cst_department_id.code or "",
                "options": [{"id": wc.id, "name": wc.name} for wc in options],
                "selected": True,
            })
        return rows

    @api.model
    def mo_preview(self, product_id, qty, warehouse_id=None):
        product = self.env["product.product"].browse(int(product_id)).exists()
        if not product:
            return {"materials": [], "operations": [], "bom_id": False}
        bom = self._mo_bom(product)
        warehouse = self._mo_warehouse(product.company_id, warehouse_id)
        return {
            "materials": self.mo_materials(product, qty, warehouse),
            "operations": self.mo_operations(bom),
            "bom_id": bom.id,
            "uom": product.uom_id.name,
        }

    @api.model
    def mo_search_products(self, query, limit=20, warehouse_id=None):
        """Storable products for the «extra material» picker, Cyrillic or Latin."""
        # every word on its own («бел лдсп»), Latin or Cyrillic; the whole
        # catalogue is scanned — a name-ordered first thousand missed most of it
        words = [w for w in (skeleton(part) for part in re.split(r"[\s,;]+", query or "")) if w]
        if not words:
            return []
        warehouse = self._mo_warehouse(warehouse_id=warehouse_id)
        products = self.env["product.product"].search_fetch(
            [("is_storable", "=", True), ("cst_is_second_grade", "=", False)],
            ["display_name", "default_code", "cst_characteristic"], order="name")
        rows = []
        for product in products:
            key = skeleton("%s %s %s" % (product.default_code or "", product.display_name,
                                         product.cst_characteristic or ""))
            if not all(word in key for word in words):
                continue
            rows.append({"id": product.id, "label": product.display_name,
                         "product": product.cst_base_name(),
                         "characteristic": product.cst_characteristic or "",
                         "uom": product.uom_id.name,
                         "free": self._mo_free_qty(product, warehouse)})
            if len(rows) >= limit:
                break
        return rows

    # ------------------------------------------------------------------ create
    @api.model
    def _mo_apply_materials(self, production, materials):
        """Shape this order's raw material to what the screen listed.

        A component dropped here is dropped from this order only, a quantity
        typed here replaces the exploded one, and a product added here becomes
        an extra raw move. Quantities are in the component's own unit.
        """
        wanted = {}
        for row in materials or []:
            qty = float(row.get("qty") or 0)
            if qty > 0 and row.get("product_id"):
                wanted[int(row["product_id"])] = wanted.get(int(row["product_id"]), 0.0) + qty
        production = production.with_context(skip_compute_move_raw_ids=True)
        for move in production.move_raw_ids:
            pid = move.product_id.id
            if pid not in wanted:
                move.unlink()
                continue
            new_qty = move.product_id.uom_id._compute_quantity(wanted.pop(pid), move.product_uom)
            if move.product_uom.compare(new_qty, move.product_uom_qty) != 0:
                move.product_uom_qty = new_qty
        Move = self.env["stock.move"]
        for pid, qty in wanted.items():
            product = self.env["product.product"].browse(pid)
            Move.create(production._get_move_raw_values(product, qty, product.uom_id))
        return production

    @api.model
    def _mo_apply_operations(self, production, operations):
        """Keep the ticked operations only, each on the line that was chosen."""
        chosen = {int(row["id"]): row for row in operations or [] if row.get("id")}
        for workorder in production.workorder_ids:
            if not workorder.operation_id:
                continue
            spec = chosen.get(workorder.operation_id.id)
            if spec is None or not spec.get("selected", True):
                workorder.unlink()
            elif spec.get("workcenter_id") and int(spec["workcenter_id"]) != workorder.workcenter_id.id:
                workorder.workcenter_id = int(spec["workcenter_id"])
        if not production.workorder_ids:
            raise UserError(_("Hech bo'lmaganda bitta operatsiya tanlang."))
        return production

    @api.model
    def _mo_picking_type(self, company, warehouse=None):
        domain = [("code", "=", "mrp_operation"), ("company_id", "=", company.id)]
        picking_type = self.env["stock.picking.type"]
        if warehouse:
            picking_type = picking_type.search(domain + [("warehouse_id", "=", warehouse.id)], limit=1)
        return picking_type or self.env["stock.picking.type"].search(domain, limit=1)

    @api.model
    def _mo_create(self, product, qty, materials=None, operations=None, values=None,
                   company=None, warehouse=None, confirm=True):
        """Raise the order the screen described and confirm it.

        ``values`` is what the calling screen wants stamped on the order —
        its project, its origin — never anything the browser sent.
        """
        qty = float(qty or 0)
        if qty <= 0:
            raise UserError(_("Miqdor noldan katta bo'lishi kerak."))
        company = self._mo_company(company or product.company_id)
        bom = self._mo_bom(product, company)
        warehouse = warehouse if warehouse is not None else self._mo_warehouse(company)
        picking_type = self._mo_picking_type(company, warehouse)
        vals = {
            "product_id": product.id,
            "product_qty": qty,
            "product_uom_id": product.uom_id.id,
            "bom_id": bom.id,
            "company_id": company.id,
        }
        if picking_type:
            vals["picking_type_id"] = picking_type.id
        vals.update(values or {})
        production = self.env["mrp.production"].sudo().with_company(company).with_context(
            from_project_action=True).create(vals)
        if materials is not None:
            self._mo_apply_materials(production, materials)
        if operations is not None:
            self._mo_apply_operations(production, operations)
        if confirm:
            production.action_confirm()
            production.action_assign()
        return production
