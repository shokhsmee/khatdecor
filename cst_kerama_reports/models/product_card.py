from collections import defaultdict

from odoo import _, api, fields, models

from .goods_movement import IN_COLUMNS, IN_KEYS, OUT_COLUMNS, REGRADE_OUT

KIND_LABELS = dict(IN_COLUMNS + OUT_COLUMNS)
KIND_LABELS.update({
    "production_in": "Ishlab chiqarishdan",
    REGRADE_OUT: "2-sortga o'tkazildi",
})


class CstProductCardReport(models.AbstractModel):
    """«Mahsulot kartochkasi» — one product, date by date.

    Every done movement of the product in the chosen warehouses, in the order it
    happened, with what came in, what went out and the balance after it — the
    stock card the warehouse used to keep by hand. Above it the stock on hand
    right now, per warehouse. Classification and warehouse boundaries are the
    ones of «Tovar harakati», so the card's opening, totals and closing are the
    same numbers as that sheet's row for the product.
    """

    _name = "cst.product.card.report"
    _description = "Mahsulot kartochkasi"
    _inherit = "cst.stock.report.base"

    @api.model
    def build(self, product_ids, date_from, date_to, warehouse_ids=None, company_ids=None,
              together=False, daily=False):
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        products = self.env["product.product"].sudo().with_context(active_test=False).browse(product_ids or []).exists()
        warehouses = self._warehouses(warehouse_ids, company_ids)
        if not products or not warehouses:
            return []
        Movement = self.env["cst.goods.movement.report"]
        locations = self._internal_locations(warehouses)
        inside = set(locations.ids)
        warehouse_of = {loc.id: (0 if together else loc.warehouse_id.id) for loc in locations}
        period_start, period_end = self._local_bounds(date_from, date_to)

        lines = self.env["stock.move.line"].sudo().search([
            ("state", "=", "done"), ("product_id", "in", products.ids),
            "|", ("location_id", "in", locations.ids), ("location_dest_id", "in", locations.ids),
            ("date", "<", period_end),
        ], order="date, id")
        usage = {loc.id: loc.usage for loc in (lines.location_id | lines.location_dest_id)}
        inventory_moves = set(lines.move_id.filtered("is_inventory").ids)
        regrades = Movement._regrade_moves(set(lines.move_id.ids))

        # (product, warehouse key) -> {"opening": qty, "rows": [...]}
        cards = defaultdict(lambda: {"opening": 0.0, "rows": []})
        for line in lines:
            qty = line.quantity_product_uom
            if not qty:
                continue
            sides = Movement._sides(line.location_id.id, line.location_dest_id.id, inside, warehouse_of,
                                    usage, line.move_id.id in inventory_moves,
                                    regrade=line.move_id.id in regrades)
            for wh_key, kind in sides:
                card = cards[(line.product_id.id, wh_key)]
                incoming = kind in IN_KEYS
                if line.date < period_start:
                    card["opening"] += qty if incoming else -qty
                    continue
                card["rows"].append(self._row(line, kind, qty if incoming else 0.0, 0.0 if incoming else qty))

        if together:
            keys = [(0, False)]
        else:
            keys = [(w.id, w) for w in warehouses.sorted(lambda w: (w.company_id.name, w.name))]
        on_hand = self._on_hand(products, warehouses)
        result = []
        for product in products.sorted(lambda p: p.display_name or ""):
            blocks = []
            for wh_key, warehouse in keys:
                card = cards.get((product.id, wh_key))
                if not card:
                    continue
                rows = self._daily(card["rows"]) if daily else card["rows"]
                balance = card["opening"]
                total_in = total_out = 0.0
                for row in rows:
                    balance += row["in"] - row["out"]
                    row["balance"] = balance
                    total_in += row["in"]
                    total_out += row["out"]
                if not rows and not card["opening"]:
                    continue
                blocks.append({
                    "warehouse": warehouse,
                    "label": ("%s — %s" % (warehouse.company_id.name, warehouse.name)) if warehouse
                             else _("Tanlangan omborlar birgalikda"),
                    "opening": card["opening"], "rows": rows,
                    "in": total_in, "out": total_out, "closing": balance,
                })
            stock = on_hand.get(product.id, [])
            if not blocks and not stock:
                continue
            result.append({
                "product": product,
                "label": self.env["cst.warehouse.report"].product_label(product),
                "characteristic": self._characteristic(product),
                "uom": product.uom_id.name,
                "blocks": blocks,
                "on_hand": stock,
                "on_hand_total": {key: sum(s[key] for s in stock) for key in ("qty", "reserved", "free")},
            })
        return result

    @api.model
    def _row(self, line, kind, qty_in, qty_out):
        move = line.move_id
        doc, model, res_id = self._document(line)
        partner = line.picking_id.partner_id or move.partner_id
        return {
            "date": fields.Datetime.context_timestamp(self, line.date),
            "day": fields.Datetime.context_timestamp(self, line.date).date(),
            "document": doc, "model": model, "res_id": res_id,
            "kind": KIND_LABELS.get(kind, kind),
            "source": line.location_id.complete_name or "",
            "dest": line.location_dest_id.complete_name or "",
            "partner": partner.display_name or "",
            "origin": (line.picking_id.origin or move.origin or "") if (line.picking_id.origin or move.origin) != doc else "",
            "in": qty_in, "out": qty_out,
        }

    @api.model
    def _document(self, line):
        """(name, model, id) of the paper behind a move line — the one to open."""
        move = line.move_id
        if line.picking_id:
            return line.picking_id.name, "stock.picking", line.picking_id.id
        production = move.production_id or move.raw_material_production_id
        if production:
            return production.name, "mrp.production", production.id
        if move.scrap_id:
            return move.scrap_id.name, "stock.scrap", move.scrap_id.id
        if move.unbuild_id:
            return move.unbuild_id.name, "mrp.unbuild", move.unbuild_id.id
        if move.is_inventory:
            return move.reference or _("Reviziya"), "stock.move", move.id
        return move.reference or move.origin or "", "stock.move", move.id

    @api.model
    def _daily(self, rows):
        """The same movements folded to one row per day."""
        days = {}
        for row in rows:
            day = days.setdefault(row["day"], {
                "date": row["day"], "day": row["day"], "documents": [], "kinds": [],
                "document": "", "model": False, "res_id": False, "source": "", "dest": "",
                "partner": "", "origin": "", "in": 0.0, "out": 0.0})
            day["in"] += row["in"]
            day["out"] += row["out"]
            if row["document"] and row["document"] not in day["documents"]:
                day["documents"].append(row["document"])
            if row["kind"] not in day["kinds"]:
                day["kinds"].append(row["kind"])
        for day in days.values():
            day["document"] = ", ".join(day["documents"][:6]) + (" …" if len(day["documents"]) > 6 else "")
            day["kind"] = ", ".join(day["kinds"])
        return [days[d] for d in sorted(days)]

    @api.model
    def _on_hand(self, products, warehouses):
        """Right now, per warehouse: on hand, reserved, free."""
        quants = self.env["stock.quant"].sudo().search([
            ("product_id", "in", products.ids),
            ("location_id.usage", "=", "internal"),
            ("location_id.warehouse_id", "in", warehouses.ids),
        ])
        totals = defaultdict(lambda: {"qty": 0.0, "reserved": 0.0})
        for quant in quants:
            entry = totals[(quant.product_id.id, quant.location_id.warehouse_id)]
            entry["qty"] += quant.quantity
            entry["reserved"] += quant.reserved_quantity
        result = defaultdict(list)
        for (product_id, warehouse), entry in sorted(
                totals.items(), key=lambda kv: (kv[0][1].company_id.name, kv[0][1].name)):
            if not entry["qty"] and not entry["reserved"]:
                continue
            result[product_id].append({
                "warehouse": warehouse,
                "label": "%s — %s" % (warehouse.company_id.name, warehouse.name),
                "qty": entry["qty"], "reserved": entry["reserved"],
                "free": entry["qty"] - entry["reserved"],
            })
        return result
