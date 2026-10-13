from collections import defaultdict

from odoo import api, fields, models


class CstStockReportBase(models.AbstractModel):
    """Shared plumbing of the warehouse sheets."""

    _name = "cst.stock.report.base"
    _description = "Stock report helpers"

    @api.model
    def _companies(self, company_ids=None):
        allowed = self.env.companies
        if company_ids:
            wanted = allowed.filtered(lambda c: c.id in company_ids)
            if wanted:
                return wanted
        return allowed

    @api.model
    def _warehouses(self, warehouse_ids=None, company_ids=None):
        companies = self._companies(company_ids)
        Warehouse = self.env["stock.warehouse"]
        warehouses = Warehouse.browse(warehouse_ids) if warehouse_ids \
            else Warehouse.search([("company_id", "in", companies.ids)])
        return warehouses.filtered(lambda w: w.company_id in companies)

    @api.model
    def _internal_locations(self, warehouses):
        return self.env["stock.location"].search([
            ("id", "child_of", warehouses.view_location_id.ids),
            ("usage", "=", "internal"),
        ])

    @api.model
    def _root_and_leaf(self, product):
        return self.env["cst.warehouse.report"]._category_pair(product.categ_id)

    @api.model
    def _characteristic(self, product):
        return self.env["cst.warehouse.report"]._characteristic(product)

    @api.model
    def _period(self, date_from, date_to):
        return [("date", ">=", fields.Datetime.to_datetime(date_from)),
                ("date", "<=", fields.Datetime.to_datetime(date_to).replace(
                    hour=23, minute=59, second=59))]


class CstWriteoffReport(models.AbstractModel):
    """«Hisobdan chiqarilgan xomashyo va mahsulot» — every write-off of the
    period, document by document, the lines under it.

    A write-off is stock leaving an internal location for an inventory-loss
    location *without* being an inventory count: scraps, spoiled rolls, fuel
    burned. Count differences have their own sheet (reviziya)."""

    _name = "cst.writeoff.report"
    _description = "Hisobdan chiqarilganlar"
    _inherit = "cst.stock.report.base"

    @api.model
    def build(self, date_from, date_to, warehouse_ids=None, company_ids=None):
        warehouses = self._warehouses(warehouse_ids, company_ids)
        if not warehouses:
            return []
        locations = self._internal_locations(warehouses)
        lines = self.env["stock.move.line"].sudo().search(
            [("state", "=", "done"),
             ("location_id", "in", locations.ids),
             ("location_dest_id.usage", "=", "inventory"),
             ("move_id.is_inventory", "=", False)] + self._period(date_from, date_to),
            order="date, id")

        result = []
        for company in warehouses.company_id:
            groups = {}
            for line in lines.filtered(lambda l: l.company_id == company):
                root, _leaf = self._root_and_leaf(line.product_id)
                group = groups.setdefault(root.id, {
                    "category": root, "documents": {}, "quantity": 0.0})
                key = self._document_key(line)
                doc = group["documents"].setdefault(key, {
                    "date": fields.Datetime.context_timestamp(self, line.date).date(),
                    "title": self._document_title(line),
                    "lines": [], "quantity": 0.0})
                doc["lines"].append({
                    "line": line,
                    "product": line.product_id,
                    "characteristic": self._characteristic(line.product_id),
                    "uom": line.product_uom_id.name,
                    "quantity": line.quantity,
                })
                doc["quantity"] += line.quantity_product_uom
                group["quantity"] += line.quantity_product_uom
            if not groups:
                continue
            for group in groups.values():
                group["documents"] = sorted(group["documents"].values(),
                                            key=lambda d: (d["date"], d["title"]))
            result.append({
                "company": company,
                "groups": sorted(groups.values(),
                                 key=lambda g: g["category"].complete_name or ""),
            })
        return result

    @api.model
    def _document_key(self, line):
        move = line.move_id
        if move.scrap_id:
            return ("scrap", move.scrap_id.id)
        if line.picking_id:
            return ("picking", line.picking_id.id)
        return ("move", move.reference or move.id, fields.Date.to_date(line.date))

    @api.model
    def _document_title(self, line):
        move = line.move_id
        reason = ""
        if move.scrap_id:
            reason = move.scrap_id.origin or move.scrap_id.name or ""
        elif line.picking_id:
            reason = line.picking_id.origin or line.picking_id.note or line.picking_id.name or ""
        else:
            reason = move.origin or move.description_picking or move.reference or ""
        return "Hisobdan chiqarildi: %s" % reason if reason else "Hisobdan chiqarildi"


class CstInventoryCountReport(models.AbstractModel):
    """«Reviziya hisoboti» — what the count found more of, what it found less
    of, per product, grouped mahsulot/xom ashyo ▸ kategoriya."""

    _name = "cst.inventory.count.report"
    _description = "Reviziya hisoboti"
    _inherit = "cst.stock.report.base"

    @api.model
    def build(self, date_from, date_to, warehouse_ids=None, company_ids=None):
        warehouses = self._warehouses(warehouse_ids, company_ids)
        if not warehouses:
            return []
        locations = self._internal_locations(warehouses)
        lines = self.env["stock.move.line"].sudo().search(
            [("state", "=", "done"), ("move_id.is_inventory", "=", True),
             "|", ("location_id", "in", locations.ids),
                  ("location_dest_id", "in", locations.ids)] + self._period(date_from, date_to))
        inside = set(locations.ids)

        result = []
        for company in warehouses.company_id:
            groups = {}
            for line in lines.filtered(lambda l: l.company_id == company):
                surplus = line.quantity_product_uom if line.location_dest_id.id in inside else 0.0
                shortage = line.quantity_product_uom if line.location_id.id in inside else 0.0
                root, leaf = self._root_and_leaf(line.product_id)
                group = groups.setdefault(root.id, {
                    "category": root, "leaves": {}, "surplus": 0.0, "shortage": 0.0})
                cat = group["leaves"].setdefault(leaf.id, {
                    "category": leaf, "products": {}, "surplus": 0.0, "shortage": 0.0})
                prod = cat["products"].setdefault(line.product_id.id, {
                    "product": line.product_id,
                    "characteristic": self._characteristic(line.product_id),
                    "surplus": 0.0, "shortage": 0.0})
                for bucket in (prod, cat, group):
                    bucket["surplus"] += surplus
                    bucket["shortage"] += shortage
            if not groups:
                continue
            for group in groups.values():
                for cat in group["leaves"].values():
                    cat["products"] = sorted(cat["products"].values(),
                                             key=lambda p: p["product"].display_name or "")
                group["leaves"] = sorted(group["leaves"].values(),
                                         key=lambda c: c["category"].complete_name or "")
            result.append({
                "company": company,
                "groups": sorted(groups.values(),
                                 key=lambda g: g["category"].complete_name or ""),
                "surplus": sum(g["surplus"] for g in groups.values()),
                "shortage": sum(g["shortage"] for g in groups.values()),
            })
        return result


class CstConsumptionReport(models.AbstractModel):
    """«Kam yoki ko'p miqdorda sarflangan» — per manufacturing order, what the
    bill of materials said each component should take for the quantity made,
    what was actually consumed, and the gap."""

    _name = "cst.consumption.report"
    _description = "Norma va fakt sarfi"
    _inherit = "cst.stock.report.base"

    @api.model
    def build(self, date_from, date_to, company_ids=None, product_ids=None, only_deviations=False):
        companies = self._companies(company_ids)
        domain = [("state", "=", "done"), ("company_id", "in", companies.ids),
                  ("date_finished", ">=", fields.Datetime.to_datetime(date_from)),
                  ("date_finished", "<=", fields.Datetime.to_datetime(date_to).replace(
                      hour=23, minute=59, second=59))]
        if product_ids:
            domain.append(("product_id", "in", product_ids))
        orders = self.env["mrp.production"].sudo().search(domain, order="date_finished, id")

        result = []
        for mo in orders:
            produced = mo.qty_produced or mo.product_qty
            norms = defaultdict(float)
            if mo.bom_id and mo.bom_id.product_qty:
                factor = produced / mo.bom_id.product_qty
                for bl in mo.bom_id.bom_line_ids:
                    if bl._skip_bom_line(mo.product_id) if hasattr(bl, "_skip_bom_line") else False:
                        continue
                    qty = bl.product_uom_id._compute_quantity(
                        bl.product_qty * factor, bl.product_id.uom_id)
                    norms[bl.product_id] += qty
            facts = defaultdict(float)
            for move in mo.move_raw_ids.filtered(lambda m: m.state == "done"):
                facts[move.product_id] += move.product_uom._compute_quantity(
                    move.quantity, move.product_id.uom_id)
            components = []
            for product in sorted(set(norms) | set(facts), key=lambda p: p.display_name or ""):
                norm, fact = norms.get(product, 0.0), facts.get(product, 0.0)
                if only_deviations and abs(fact - norm) < 1e-6:
                    continue
                components.append({
                    "product": product,
                    "characteristic": self._characteristic(product),
                    "uom": product.uom_id.name,
                    "norm": norm, "fact": fact, "diff": fact - norm,
                })
            if only_deviations and not components:
                continue
            result.append({
                "mo": mo,
                "date": fields.Datetime.context_timestamp(self, mo.date_finished).date()
                        if mo.date_finished else False,
                "product": mo.product_id,
                "characteristic": self._characteristic(mo.product_id),
                "quantity": produced,
                "uom": mo.product_uom_id.name,
                "components": components,
            })
        return result


class CstMinMaxReport(models.AbstractModel):
    """«Kam yoki ko'p miqdorda turgan mahsulot va xomashyo» — every product
    against its min/max, with the quantity standing in the warehouse today.

    The min and the max live on Odoo's reordering rules (one per product per
    warehouse); this sheet reads them and adds what the rules screen never
    shows side by side: how far below the minimum (*kam*) or above the
    maximum (*ko'p*) the stock stands. Products without a rule can be listed
    too, so the storekeeper sees what still has no limits set.
    """

    _name = "cst.minmax.report"
    _description = "Min-max bo'yicha qoldiqlar"
    _inherit = "cst.stock.report.base"

    @api.model
    def build(self, warehouse_ids=None, category_ids=None, company_ids=None,
              only_deviations=True, include_without_rule=False):
        warehouses = self._warehouses(warehouse_ids, company_ids)
        if not warehouses:
            return []
        Rule = self.env["stock.warehouse.orderpoint"].sudo()
        domain = [("warehouse_id", "in", warehouses.ids)]
        if category_ids:
            categories = self.env["product.category"].search([("id", "child_of", category_ids)])
            domain.append(("product_id.categ_id", "in", categories.ids))
        rules = Rule.search(domain, order="warehouse_id, product_id")
        ruled = {(r.warehouse_id.id, r.product_id.id) for r in rules}

        rows = []
        for rule in rules:
            on_hand = rule.qty_on_hand
            low = rule.product_min_qty - on_hand if on_hand < rule.product_min_qty else 0.0
            high = on_hand - rule.product_max_qty if rule.product_max_qty and on_hand > rule.product_max_qty else 0.0
            if only_deviations and not low and not high:
                continue
            rows.append(self._row(rule.warehouse_id, rule.product_id, rule.product_min_qty,
                                  rule.product_max_qty, on_hand, rule.qty_forecast,
                                  rule.qty_to_order, low, high, True))

        if include_without_rule:
            Product = self.env["product.product"].sudo()
            pdomain = [("is_storable", "=", True), ("active", "=", True)]
            if category_ids:
                pdomain.append(("categ_id", "in", categories.ids))
            products = Product.search(pdomain)
            for warehouse in warehouses:
                stocked = products.with_context(warehouse_id=warehouse.id)
                for product in stocked:
                    if (warehouse.id, product.id) in ruled or not product.qty_available:
                        continue
                    rows.append(self._row(warehouse, product, None, None, product.qty_available,
                                          product.virtual_available, 0.0, 0.0, 0.0, False))

        result = []
        for warehouse in warehouses.sorted(lambda w: (w.company_id.name, w.name)):
            groups = {}
            for row in sorted((r for r in rows if r["warehouse"] == warehouse),
                              key=lambda r: (r["product"].categ_id.complete_name or "", r["product"].display_name or "")):
                root, leaf = self._root_and_leaf(row["product"])
                group = groups.setdefault(root.id, {"category": root, "leaves": {}, "low": 0.0, "high": 0.0, "count": 0})
                cat = group["leaves"].setdefault(leaf.id, {"category": leaf, "products": [], "low": 0.0, "high": 0.0})
                cat["products"].append(row)
                for bucket in (group, cat):
                    bucket["low"] += row["low"]
                    bucket["high"] += row["high"]
                group["count"] += 1
            if not groups:
                continue
            for group in groups.values():
                group["leaves"] = sorted(group["leaves"].values(),
                                         key=lambda c: c["category"].complete_name or "")
            result.append({
                "warehouse": warehouse, "company": warehouse.company_id,
                "groups": sorted(groups.values(), key=lambda g: g["category"].complete_name or ""),
                "count": sum(g["count"] for g in groups.values()),
                "low_count": sum(1 for r in rows if r["warehouse"] == warehouse and r["low"]),
                "high_count": sum(1 for r in rows if r["warehouse"] == warehouse and r["high"]),
            })
        return result

    @api.model
    def _row(self, warehouse, product, minimum, maximum, on_hand, forecast, to_order, low, high, has_rule):
        return {
            "warehouse": warehouse, "product": product,
            "characteristic": self._characteristic(product),
            "uom": product.uom_id.name,
            "min": minimum, "max": maximum,
            "on_hand": on_hand, "forecast": forecast, "to_order": to_order,
            "low": low, "high": high, "has_rule": has_rule,
            "state": "low" if low else "high" if high else ("ok" if has_rule else "none"),
        }
