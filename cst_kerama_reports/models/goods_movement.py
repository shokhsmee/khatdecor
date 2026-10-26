from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models

# The columns of «Товарнинг ҳаракати»: what came in and what went out, split by
# where it came from / went to. Every finer flow of the ledger folds into one.
IN_COLUMNS = [
    ("purchase", "Xarid"),
    ("production_in", "Ishlab chiqarishdan"),
    ("transfer_in", "Ko'chirish (kirim)"),
    ("inventory_in", "Reviziya (ortiqcha)"),
    ("other_in", "Qaytish va boshqa"),
]
OUT_COLUMNS = [
    ("sale", "Sotuv"),
    ("production_out", "Ishlab chiqarishga"),
    ("transfer_out", "Ko'chirish (chiqim)"),
    ("inventory_out", "Reviziya (kamomad)"),
    ("other_out", "Spisaniya va boshqa"),
]
# a 1-sort piece regraded to its 2-sort twin: not a write-off, the shift's
# output simply came out as another product
REGRADE_OUT = "production_in_back"
IN_KEYS = [key for key, _label in IN_COLUMNS]
OUT_KEYS = [key for key, _label in OUT_COLUMNS]


class CstGoodsMovementReport(models.AbstractModel):
    """«Tovar harakati» (Товарнинг ҳаракати) — per product and period: the
    opening balance, what came in (purchase, production, transfers, other),
    what went out (sales, production, transfers, write-offs) and the closing
    balance.

    Quantities only, read from the done move lines, so every row adds up:
    ``oxirgi = boshlang'ich + jami kirim − jami chiqim``. A transfer between
    two warehouses is an outflow of one and an inflow of the other; seen
    «together» (all chosen warehouses as one) it is internal and not shown.
    """

    _name = "cst.goods.movement.report"
    _description = "Tovar harakati"
    _inherit = "cst.stock.report.base"

    @api.model
    def _sides(self, src, dst, inside, warehouse_of, usage, is_inventory, regrade=False):
        """[(warehouse key, column)] a move line counts for — none, one or two."""
        src_in, dst_in = src in inside, dst in inside
        if src_in and dst_in and warehouse_of[src] == warehouse_of[dst]:
            return []
        sides = []
        if dst_in:
            origin = usage.get(src)
            if regrade:
                key = "production_in"
            elif is_inventory:
                key = "inventory_in"
            elif origin == "supplier":
                key = "purchase"
            elif origin == "production":
                key = "production_in"
            elif origin in ("internal", "transit"):
                key = "transfer_in"
            else:  # customer return, count surplus, anything else
                key = "other_in"
            sides.append((warehouse_of[dst], key))
        if src_in:
            target = usage.get(dst)
            if regrade:
                key = REGRADE_OUT
            elif is_inventory:
                key = "inventory_out"
            elif target == "customer":
                key = "sale"
            elif target == "production":
                key = "production_out"
            elif target in ("internal", "transit"):
                key = "transfer_out"
            else:  # scrap, count shortage, anything else
                key = "other_out"
            sides.append((warehouse_of[src], key))
        return sides

    @api.model
    def build(self, date_from, date_to, warehouse_ids=None, category_ids=None,
              product_ids=None, company_ids=None, together=False, hide_zero=True):
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        warehouses = self._warehouses(warehouse_ids, company_ids)
        if not warehouses:
            return {"blocks": [], "totals": self._empty()}
        locations = self._internal_locations(warehouses)
        inside = set(locations.ids)
        warehouse_of = {loc.id: (0 if together else loc.warehouse_id.id) for loc in locations}

        period_start, period_end = self._local_bounds(date_from, date_to)
        domain = [("state", "=", "done"),
                  "|", ("location_id", "in", locations.ids),
                       ("location_dest_id", "in", locations.ids),
                  ("date", "<", period_end)]
        if product_ids:
            domain.append(("product_id", "in", product_ids))
        if category_ids:
            categories = self.env["product.category"].search([("id", "child_of", category_ids)])
            domain.append(("product_id.categ_id", "in", categories.ids))
        rows = self.env["stock.move.line"].sudo().search_read(domain, [
            "product_id", "location_id", "location_dest_id", "quantity_product_uom", "date", "move_id"])

        location_ids = {r["location_id"][0] for r in rows} | {r["location_dest_id"][0] for r in rows}
        usage = {loc.id: loc.usage for loc in self.env["stock.location"].sudo().browse(location_ids)}
        move_ids = {r["move_id"][0] for r in rows if r["move_id"]}
        is_inventory = set(self.env["stock.move"].sudo().search(
            [("id", "in", list(move_ids)), ("is_inventory", "=", True)]).ids)
        regrades = self._regrade_moves(move_ids)

        # (warehouse key, product) -> {"opening": qty, column: qty}
        cells = defaultdict(lambda: defaultdict(float))
        for row in rows:
            qty = row["quantity_product_uom"] or 0.0
            if not qty:
                continue
            move_id = row["move_id"] and row["move_id"][0]
            sides = self._sides(row["location_id"][0], row["location_dest_id"][0], inside, warehouse_of,
                                usage, move_id in is_inventory, regrade=move_id in regrades)
            for wh_key, column in sides:
                cell = cells[(wh_key, row["product_id"][0])]
                if row["date"] < period_start:
                    cell["opening"] += qty if column in IN_KEYS else -qty
                elif column == REGRADE_OUT:
                    cell["production_in"] -= qty
                else:
                    cell[column] += qty

        products = self.env["product.product"].sudo().with_context(active_test=False).browse(
            sorted({key[1] for key in cells})).exists()
        products = products.sorted(lambda p: (p.categ_id.complete_name or "", p.display_name or ""))
        if together:
            blocks_keys = [(0, False)]
        else:
            blocks_keys = [(w.id, w) for w in warehouses.sorted(lambda w: (w.company_id.name, w.name))]

        blocks = []
        for wh_key, warehouse in blocks_keys:
            groups = {}
            for product in products:
                cell = cells.get((wh_key, product.id))
                if not cell:
                    continue
                line = self._row(product, cell)
                # «harakatsiz» = nothing came in or went out in the period; a
                # product that only sat on the shelf belongs to the stock sheet
                if hide_zero and not (line["in_total"] or line["out_total"] or any(line["flows"].values())):
                    continue
                if not any((line["opening"], line["in_total"], line["out_total"], line["closing"])):
                    continue
                root, leaf = self._root_and_leaf(product)
                group = groups.setdefault(root.id, {"category": root, "leaves": {}, "rows": []})
                group["leaves"].setdefault(leaf.id, {"category": leaf, "products": []})["products"].append(line)
                group["rows"].append(line)
            if not groups:
                continue
            for group in groups.values():
                for leaf in group["leaves"].values():
                    leaf["totals"] = self._sum(leaf["products"])
                group["leaves"] = sorted(group["leaves"].values(),
                                         key=lambda c: c["category"].complete_name or "")
                group["totals"] = self._sum(group["rows"])
            all_rows = [r for g in groups.values() for r in g["rows"]]
            blocks.append({
                "warehouse": warehouse,
                "label": ("%s — %s" % (warehouse.company_id.name, warehouse.name)) if warehouse
                         else "Tanlangan omborlar birgalikda: %s" % ", ".join(warehouses.mapped("name")),
                "groups": sorted(groups.values(), key=lambda g: g["category"].complete_name or ""),
                "totals": self._sum(all_rows),
                "count": len(all_rows),
            })
        return {"blocks": blocks,
                "totals": self._sum([r for b in blocks for g in b["groups"] for r in g["rows"]])}

    @api.model
    def _regrade_moves(self, move_ids):
        """Both legs of a shift's 2-sort regrade: the 1-sort piece scrapped with
        the «2-sort» reason, and the twin brought in for it."""
        if not move_ids:
            return set()
        Move = self.env["stock.move"].sudo()
        reason = self.env.ref("cst_kerama_shift.scrap_reason_second_grade", raise_if_not_found=False)
        found = set()
        if reason:
            found |= set(Move.search([("id", "in", list(move_ids)),
                                      ("scrap_id.scrap_reason_tag_ids", "in", reason.ids)]).ids)
        if "cst.production.shift.line" in self.env:
            self.env.cr.execute(
                "SELECT move_id FROM cst_shift_line_second_move_rel WHERE move_id = ANY(%s)", [list(move_ids)])
            found |= {r[0] for r in self.env.cr.fetchall()}
        return found

    @api.model
    def _row(self, product, cell):
        flows = {key: cell.get(key, 0.0) for key in IN_KEYS + OUT_KEYS}
        in_total = sum(flows[k] for k in IN_KEYS)
        out_total = sum(flows[k] for k in OUT_KEYS)
        opening = cell.get("opening", 0.0)
        return {
            "product": product,
            "characteristic": self._characteristic(product),
            "uom": product.uom_id.name,
            "opening": opening,
            "flows": flows,
            "in_total": in_total,
            "out_total": out_total,
            "closing": opening + in_total - out_total,
        }

    @api.model
    def _empty(self):
        return {"opening": 0.0, "in_total": 0.0, "out_total": 0.0, "closing": 0.0,
                "flows": {key: 0.0 for key in IN_KEYS + OUT_KEYS}}

    @api.model
    def _sum(self, rows):
        totals = self._empty()
        for row in rows:
            for key in ("opening", "in_total", "out_total", "closing"):
                totals[key] += row[key]
            for key, qty in row["flows"].items():
                totals["flows"][key] += qty
        return totals

    @api.model
    def columns(self):
        return {"in": IN_COLUMNS, "out": OUT_COLUMNS}

    @api.model
    def eve(self, date_from):
        return fields.Date.to_date(date_from) - timedelta(days=1)
