from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models

# The columns of the workbook this replaces, in its order. Each flow is a
# (quantity, value) pair; the key is what the classifier below returns.
IN_FLOWS = [
    ("purchase", "Sotib olindi"),
    ("production_in", "I/ch dan kirim"),
    ("return_in", "Vozvrat orqali kirim"),
    ("transfer_in", "Boshqa ombordan kirim"),
    ("count_surplus", "Reviziyada ko'p chiqdi"),
    ("other_in", "Boshqa kirim"),
]
OUT_FLOWS = [
    ("sale", "Sotildi"),
    ("production_out", "I/ch ga chiqim"),
    ("transfer_out", "Boshqa omborga chiqim"),
    ("count_shortage", "Reviziyada kam chiqdi"),
    ("writeoff", "Hisobdan chiqarildi"),
    ("other_out", "Boshqa chiqim"),
]


class CstStockLedgerReport(models.AbstractModel):
    """«Ombor batafsil hisoboti» — the full stock ledger of the workbook: for
    every product in every warehouse, the opening balance with its unit cost
    and value, each kind of inflow and outflow with quantity and value, the
    revaluations, and the closing balance.

    Quantities come from the done move lines; the value of a flow is the
    valuation Odoo 19 stores on the move itself (``stock.move.value``), shared
    across the move's lines pro rata. Moves Odoo does not value — transfers
    between two warehouses of one company, consumption of a zero-cost
    component — are valued at the product's average cost at the end of the
    period, so every value column is filled and the workbook's columns add up.
    Opening and closing unit costs are Odoo's own ``avg_cost`` at the two dates.

    Revaluations (a ``product.value`` entry without a move) are company-wide,
    not per warehouse: they are shown once, on the first warehouse row of the
    product, so the company total stays right.
    """

    _name = "cst.stock.ledger.report"
    _description = "Ombor batafsil hisoboti"
    _inherit = "cst.stock.report.base"

    # ------------------------------------------------------------------
    @api.model
    def _classify(self, line, inside, warehouse_of):
        """Which column a move line belongs to, seen from ``warehouse``."""
        move = line.move_id
        src, dst = line.location_id, line.location_dest_id
        src_in, dst_in = src.id in inside, dst.id in inside
        if src_in and dst_in and warehouse_of.get(src.id) == warehouse_of.get(dst.id):
            return None, None  # shuffling inside one warehouse
        if dst_in:
            wh = warehouse_of.get(dst.id)
            if src.usage == "supplier":
                return wh, "purchase"
            if src.usage == "production":
                return wh, "production_in"
            if src.usage == "customer":
                return wh, "return_in"
            if src.usage in ("internal", "transit"):
                return wh, "transfer_in"
            if src.usage == "inventory" and move.is_inventory:
                return wh, "count_surplus"
            return wh, "other_in"
        if src_in:
            wh = warehouse_of.get(src.id)
            if dst.usage == "customer":
                return wh, "sale"
            if dst.usage == "production":
                return wh, "production_out"
            if dst.usage in ("internal", "transit"):
                return wh, "transfer_out"
            if dst.usage == "inventory" and move.is_inventory:
                return wh, "count_shortage"
            if dst.usage == "inventory":
                return wh, "writeoff"
            return wh, "other_out"
        return None, None

    @api.model
    def _line_value(self, line):
        """The move's stored value, shared across its lines; None if unvalued."""
        move = line.move_id
        if not move.value or not move.quantity:
            return None
        return abs(move.value) * (line.quantity_product_uom / move.quantity)

    @api.model
    def _unit_costs(self, products, company, warehouse, at_date):
        """{product id: avg cost} for one warehouse at the end of one day."""
        if not products:
            return {}
        priced = products.with_company(company).with_context(
            to_date=fields.Datetime.to_datetime(at_date).replace(hour=23, minute=59, second=59),
            warehouse_id=warehouse.id)
        costs = {}
        for product in priced:
            try:
                costs[product.id] = product.avg_cost or product.standard_price or 0.0
            except Exception:  # noqa: BLE001 — a broken layer must not kill the sheet
                costs[product.id] = product.standard_price or 0.0
        return costs

    # ------------------------------------------------------------------
    @api.model
    def build(self, date_from, date_to, warehouse_ids=None, category_ids=None,
              product_ids=None, company_ids=None, hide_zero=True):
        warehouses = self._warehouses(warehouse_ids, company_ids)
        if not warehouses:
            return {"warehouses": [], "in_flows": IN_FLOWS, "out_flows": OUT_FLOWS}
        locations = self._internal_locations(warehouses)
        inside = set(locations.ids)
        warehouse_of = {loc.id: loc.warehouse_id.id for loc in locations}

        domain = [("state", "=", "done"),
                  "|", ("location_id", "in", locations.ids),
                       ("location_dest_id", "in", locations.ids),
                  ("date", "<=", fields.Datetime.to_datetime(date_to).replace(
                      hour=23, minute=59, second=59))]
        if product_ids:
            domain.append(("product_id", "in", product_ids))
        if category_ids:
            categories = self.env["product.category"].search([("id", "child_of", category_ids)])
            domain.append(("product_id.categ_id", "in", categories.ids))
        lines = self.env["stock.move.line"].sudo().search(domain)
        period_start = fields.Datetime.to_datetime(date_from)

        # (warehouse, product) -> {"open": qty, flows: {key: [qty, value, unvalued_qty]}}
        cells = defaultdict(lambda: {"open": 0.0,
                                     "flows": defaultdict(lambda: [0.0, 0.0, 0.0])})
        for line in lines:
            wh, flow = self._classify(line, inside, warehouse_of)
            if not flow:
                continue
            cell = cells[(wh, line.product_id.id)]
            qty = line.quantity_product_uom
            if line.date < period_start:
                cell["open"] += qty if flow in dict(IN_FLOWS) else -qty
                continue
            value = self._line_value(line)
            bucket = cell["flows"][flow]
            bucket[0] += qty
            if value is None:
                bucket[2] += qty
            else:
                bucket[1] += value

        revaluations = self._revaluations(warehouses.company_id, date_from, date_to)
        seen_reval = set()
        Product = self.env["product.product"].sudo()
        result = []
        for warehouse in warehouses.sorted(lambda w: (w.company_id.name, w.name)):
            keys = [k for k in cells if k[0] == warehouse.id]
            products = Product.browse(sorted({k[1] for k in keys})).exists()
            open_costs = self._unit_costs(products, warehouse.company_id, warehouse,
                                          fields.Date.to_date(date_from) - timedelta(days=1))
            close_costs = self._unit_costs(products, warehouse.company_id, warehouse, date_to)
            groups = {}
            for product in products.sorted(lambda p: (p.categ_id.complete_name or "", p.display_name or "")):
                cell = cells[(warehouse.id, product.id)]
                close_cost = close_costs.get(product.id, 0.0)
                flows = {}
                total_in = total_out = 0.0
                for key, _label in IN_FLOWS + OUT_FLOWS:
                    qty, value, unvalued = cell["flows"].get(key, (0.0, 0.0, 0.0))
                    value += unvalued * close_cost
                    flows[key] = (qty, value)
                    if key in dict(IN_FLOWS):
                        total_in += qty
                    else:
                        total_out += qty
                reval_in = reval_out = 0.0
                if (warehouse.company_id.id, product.id) in revaluations \
                        and (warehouse.company_id.id, product.id) not in seen_reval:
                    seen_reval.add((warehouse.company_id.id, product.id))
                    delta = revaluations[(warehouse.company_id.id, product.id)]
                    reval_in, reval_out = max(delta, 0.0), max(-delta, 0.0)
                opening = cell["open"]
                closing = opening + total_in - total_out
                if hide_zero and not any((opening, total_in, total_out, closing, reval_in, reval_out)):
                    continue
                open_cost = open_costs.get(product.id, 0.0)
                row = {
                    "product": product,
                    "characteristic": self._characteristic(product),
                    "uom": product.uom_id.name,
                    "open_qty": opening, "open_cost": open_cost, "open_value": opening * open_cost,
                    "flows": flows,
                    "reval_in": reval_in, "reval_out": reval_out,
                    "close_qty": closing, "close_cost": close_cost, "close_value": closing * close_cost,
                }
                root, leaf = self._root_and_leaf(product)
                group = groups.setdefault(root.id, {"category": root, "leaves": {}, "rows": []})
                cat = group["leaves"].setdefault(leaf.id, {"category": leaf, "products": []})
                cat["products"].append(row)
                group["rows"].append(row)
            if not groups:
                continue
            all_rows = [r for g in groups.values() for r in g["rows"]]
            for group in groups.values():
                for cat in group["leaves"].values():
                    cat["totals"] = self._sum(cat["products"])
                group["leaves"] = sorted(group["leaves"].values(),
                                         key=lambda c: c["category"].complete_name or "")
                group["totals"] = self._sum(group["rows"])
            result.append({
                "warehouse": warehouse,
                "company": warehouse.company_id,
                "groups": sorted(groups.values(), key=lambda g: g["category"].complete_name or ""),
                "totals": self._sum(all_rows),
            })
        grand = self._sum([r for w in result for g in w["groups"] for r in g["rows"]])
        return {"warehouses": result, "in_flows": IN_FLOWS, "out_flows": OUT_FLOWS,
                "totals": grand, "currency": warehouses[:1].company_id.currency_id}

    @api.model
    def _sum(self, rows):
        totals = {"open_qty": 0.0, "open_value": 0.0, "reval_in": 0.0, "reval_out": 0.0,
                  "close_qty": 0.0, "close_value": 0.0,
                  "flows": {key: [0.0, 0.0] for key, _ in IN_FLOWS + OUT_FLOWS}}
        for row in rows:
            for key in ("open_qty", "open_value", "reval_in", "reval_out", "close_qty", "close_value"):
                totals[key] += row[key]
            for key, (qty, value) in row["flows"].items():
                totals["flows"][key][0] += qty
                totals["flows"][key][1] += value
        return totals

    @api.model
    def _revaluations(self, companies, date_from, date_to):
        """{(company, product): value delta} of manual revaluations in the period."""
        Value = self.env["product.value"].sudo() if "product.value" in self.env else None
        if Value is None:
            return {}
        deltas = defaultdict(float)
        for rec in Value.search([
                ("company_id", "in", companies.ids), ("move_id", "=", False),
                ("date", ">=", fields.Datetime.to_datetime(date_from)),
                ("date", "<=", fields.Datetime.to_datetime(date_to).replace(hour=23, minute=59, second=59))]):
            deltas[(rec.company_id.id, rec.product_id.id)] += (rec.value or 0.0) - (rec.current_value or 0.0)
        return deltas
