from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models

DEFAULT_TZ = "Asia/Tashkent"


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
        # archived warehouses too (ТМ, retired 29.09): their history still
        # belongs to the period it happened in; an empty one prints nothing
        Warehouse = self.env["stock.warehouse"].with_context(active_test=False)
        warehouses = Warehouse.browse(warehouse_ids) if warehouse_ids \
            else Warehouse.search([("company_id", "in", companies.ids)])
        return warehouses.filtered(lambda w: w.company_id in companies)

    @api.model
    def _internal_locations(self, warehouses):
        return self.env["stock.location"].with_context(active_test=False).search([
            ("id", "child_of", warehouses.view_location_id.ids),
            ("usage", "=", "internal"),
        ])

    @api.model
    def _local_bounds(self, date_from, date_to):
        """The period as UTC datetimes [start, end): from the user's midnight of
        ``date_from`` to the user's midnight after ``date_to``. Stock moves are
        stored in UTC; reading the dates as UTC put everything done between
        00:00 and 05:00 in Tashkent on the day before."""
        tz = pytz.timezone(self.env.context.get("tz") or self.env.user.tz or DEFAULT_TZ)

        def utc(day):
            local = tz.localize(datetime.combine(fields.Date.to_date(day), time.min))
            return local.astimezone(pytz.utc).replace(tzinfo=None)

        start = utc(date_from) if date_from else None
        end = utc(fields.Date.to_date(date_to) + timedelta(days=1)) if date_to else None
        return start, end

    @api.model
    def _root_and_leaf(self, product):
        return self.env["cst.warehouse.report"]._category_pair(product.categ_id)

    @api.model
    def _characteristic(self, product):
        return self.env["cst.warehouse.report"]._characteristic(product)

    @api.model
    def _period(self, date_from, date_to):
        start, end = self._local_bounds(date_from, date_to)
        return [("date", ">=", start), ("date", "<", end)]


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
        # a 1-sort piece regraded to its 2-sort twin is not a write-off: the
        # shift's output just came out as the other product
        regrades = self.env["cst.goods.movement.report"]._regrade_moves(set(lines.move_id.ids))
        if regrades:
            lines = lines.filtered(lambda l: l.move_id.id not in regrades)

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
        fuel = self.env["cst.fuel.log"].sudo().search([("stock_move_id", "=", move.id)], limit=1)
        if fuel:
            # the label stored on the move predates the plate number; read it fresh
            reason = fuel._move_label()
            if move.scrap_id:
                reason = "%s · %s" % (move.scrap_id.name, reason)
        return "Hisobdan chiqarildi: %s" % reason if reason else "Hisobdan chiqarildi"


class CstInventoryCountReport(models.AbstractModel):
    """«Reviziya hisoboti» — what the count found more of, what it found less
    of, per product, grouped ombor ▸ mahsulot/xom ashyo ▸ kategoriya."""

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

        warehouse_of = {loc.id: loc.warehouse_id for loc in locations}
        before = self._system_qty(lines, locations, warehouse_of)

        result = []
        for company in warehouses.company_id:
            stores = {}
            for line in lines.filtered(lambda l: l.company_id == company):
                surplus = line.quantity_product_uom if line.location_dest_id.id in inside else 0.0
                shortage = line.quantity_product_uom if line.location_id.id in inside else 0.0
                warehouse = warehouse_of.get(line.location_dest_id.id if surplus else line.location_id.id)
                price = self._unit_value(line)
                value = (surplus - shortage) * price
                root, leaf = self._root_and_leaf(line.product_id)
                store = stores.setdefault(warehouse.id if warehouse else 0, {
                    "warehouse": warehouse, "name": warehouse.name if warehouse else "",
                    "groups": {}, "surplus": 0.0, "shortage": 0.0, "value": 0.0})
                groups = store["groups"]
                group = groups.setdefault(root.id, {
                    "category": root, "leaves": {}, "surplus": 0.0, "shortage": 0.0, "value": 0.0})
                cat = group["leaves"].setdefault(leaf.id, {
                    "category": leaf, "products": {}, "surplus": 0.0, "shortage": 0.0, "value": 0.0})
                key = (line.product_id.id, warehouse.id if warehouse else 0)
                prod = cat["products"].setdefault(key, {
                    "product": line.product_id,
                    "characteristic": self._characteristic(line.product_id),
                    "warehouse": warehouse.name if warehouse else "",
                    "before": before.get(key, 0.0),
                    "surplus": 0.0, "shortage": 0.0, "value": 0.0, "price": price})
                for bucket in (prod, cat, group, store):
                    bucket["surplus"] += surplus
                    bucket["shortage"] += shortage
                    bucket["value"] += value
            if not stores:
                continue
            for store in stores.values():
                for group in store["groups"].values():
                    for cat in group["leaves"].values():
                        for prod in cat["products"].values():
                            prod["counted"] = prod["before"] + prod["surplus"] - prod["shortage"]
                        cat["products"] = sorted(cat["products"].values(),
                                                 key=lambda p: p["product"].display_name or "")
                    group["leaves"] = sorted(group["leaves"].values(),
                                             key=lambda c: c["category"].complete_name or "")
                store["groups"] = sorted(store["groups"].values(),
                                         key=lambda g: g["category"].complete_name or "")
            result.append({
                "company": company,
                "currency": company.currency_id,
                # ombor ▸ mahsulot/xom ashyo ▸ kategoriya ▸ tovar
                "warehouses": sorted(stores.values(), key=lambda w: (
                    w["warehouse"].sequence if w["warehouse"] else 0, w["name"])),
                "surplus": sum(w["surplus"] for w in stores.values()),
                "shortage": sum(w["shortage"] for w in stores.values()),
                "value": sum(w["value"] for w in stores.values()),
            })
        return result

    @api.model
    def _system_qty(self, count_lines, locations, warehouse_of):
        """What the books held of each (product, warehouse) just before its first
        count in the period — the «hisobda» figure the count is compared with."""
        first = {}
        for line in count_lines:
            loc = line.location_dest_id if line.location_dest_id.id in warehouse_of else line.location_id
            key = (line.product_id.id, warehouse_of[loc.id].id)
            if key not in first or line.date < first[key]:
                first[key] = line.date
        if not first:
            return {}
        history = self.env["stock.move.line"].sudo().search_read([
            ("state", "=", "done"), ("product_id", "in", list({k[0] for k in first})),
            "|", ("location_id", "in", locations.ids), ("location_dest_id", "in", locations.ids),
            ("date", "<", max(first.values())),
        ], ["product_id", "location_id", "location_dest_id", "quantity_product_uom", "date"])
        balance = defaultdict(float)
        for row in history:
            src = warehouse_of.get(row["location_id"][0])
            dst = warehouse_of.get(row["location_dest_id"][0])
            if src == dst:
                continue
            qty = row["quantity_product_uom"] or 0.0
            product_id = row["product_id"][0]
            if dst:
                key = (product_id, dst.id)
                if key in first and row["date"] < first[key]:
                    balance[key] += qty
            if src:
                key = (product_id, src.id)
                if key in first and row["date"] < first[key]:
                    balance[key] -= qty
        return balance

    @api.model
    def _unit_value(self, line):
        """Value of one unit of the counted difference: the inventory move's own
        valuation where Odoo made one, else the product's cost."""
        move = line.move_id
        qty = move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id) if move.quantity else 0.0
        if qty and move.value:
            return abs(move.value) / qty
        return line.product_id.standard_price


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
                  ("date_finished", ">=", self.env["cst.stock.report.base"]._local_bounds(date_from, date_to)[0]),
                  ("date_finished", "<", self.env["cst.stock.report.base"]._local_bounds(date_from, date_to)[1])]
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
