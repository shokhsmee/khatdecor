"""«Mahsulot foyda/zarari» — profitability the way МойСклад shows it.

For a period: how much of each product left to clients, at what average
price, what it cost (the stock valuation of those very moves), what came
back from clients, and what is left as profit, with markup and margin.

* sales   = done stock moves into a customer location; revenue = the moved
            quantity at the sale order line's net unit price (after discount,
            without tax, the order's price as it stands after any «Tuzatish»);
* returns = done stock moves out of a customer location, priced the same way;
* cost    = ``stock.move.value`` of those moves (company currency);
* services (no stock move) count on confirmed orders by order date, at cost
  price.

profit = (revenue - cost) - (return revenue - return cost)
markup = profit / (cost - return cost)          («Ustama», МойСклад «Товара»)
margin = profit / (revenue - return revenue)    («Marja», МойСклад «Продаж»)
"""
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

GROUP_BYS = ("product", "partner", "user", "category")


class CstProfitabilityReport(models.AbstractModel):
    _name = "cst.profitability.report"
    _description = "Mahsulot foyda/zarari"

    # ------------------------------------------------------------------
    # access / options
    # ------------------------------------------------------------------
    @api.model
    def _check_rights(self):
        user = self.env.user
        if not (user.has_group("sales_team.group_sale_manager")
                or user.has_group("account.group_account_readonly")):
            raise AccessError(_("Foyda hisobotini ko'rishga ruxsatingiz yo'q."))

    @api.model
    def get_defaults(self):
        self._check_rights()
        today = fields.Date.context_today(self)
        return {
            # last 30 days: on the 1st of a month «this month» would open empty
            "date_from": fields.Date.to_string(today - timedelta(days=29)),
            "date_to": fields.Date.to_string(today),
            "company_ids": self.env.companies.ids,
            "currency": self.env.company.currency_id.name,
        }

    @api.model
    def _parse(self, options):
        options = dict(options or {})
        today = fields.Date.context_today(self)
        date_from = fields.Date.to_date(options.get("date_from")) or today.replace(day=1)
        date_to = fields.Date.to_date(options.get("date_to")) or today
        allowed = self.env.user.company_ids.ids
        company_ids = [c for c in (options.get("company_ids") or self.env.companies.ids) if c in allowed]
        return {
            "date_from": date_from,
            "date_to": date_to,
            "company_ids": company_ids or self.env.companies.ids,
            "warehouse_ids": options.get("warehouse_ids") or [],
            "categ_ids": options.get("categ_ids") or [],
            "partner_ids": options.get("partner_ids") or [],
            "user_ids": options.get("user_ids") or [],
            "services": options.get("services", True),
            "group_by": options.get("group_by") if options.get("group_by") in GROUP_BYS else "product",
        }

    @api.model
    def _utc_bounds(self, date_from, date_to):
        """The period's first and last moment in the user's timezone, as naive UTC."""
        tz = pytz.timezone(self.env.user.tz or self.env.context.get("tz") or "Asia/Tashkent")

        def utc(day, moment):
            return tz.localize(datetime.combine(day, moment)).astimezone(pytz.UTC).replace(tzinfo=None)

        return utc(date_from, time.min), utc(date_to, time.max)

    # ------------------------------------------------------------------
    # collection
    # ------------------------------------------------------------------
    @api.model
    def _entries(self, opts):
        """One dict per sold / returned piece of business:
        kind, product, order, partner, user, doc, qty, amount, cost."""
        env = self.env(su=True)
        start, end = self._utc_bounds(opts["date_from"], opts["date_to"])
        display_ccy = self.env.company.currency_id
        rates = {}

        def convert(amount, currency, company, date):
            if not amount or currency == display_ccy:
                return amount
            key = (currency.id, company.id, date)
            if key not in rates:
                rates[key] = currency._convert(1.0, display_ccy, company, date, round=False)
            return amount * rates[key]

        domain = [
            ("state", "=", "done"),
            ("date", ">=", start), ("date", "<=", end),
            ("company_id", "in", opts["company_ids"]),
            "|",
            "&", ("location_dest_id.usage", "=", "customer"), ("location_id.usage", "!=", "customer"),
            "&", ("location_id.usage", "=", "customer"), ("location_dest_id.usage", "!=", "customer"),
        ]
        if opts["categ_ids"]:
            domain.append(("product_id.categ_id", "child_of", opts["categ_ids"]))
        moves = env["stock.move"].search(domain, order="date, id")
        out = []
        for move in moves:
            is_return = move.location_id.usage == "customer"
            warehouse = (move.location_dest_id if is_return else move.location_id).warehouse_id
            if opts["warehouse_ids"] and warehouse.id not in opts["warehouse_ids"]:
                continue
            line = move.sale_line_id
            order = line.order_id or move.picking_id.sale_id
            if not line and order:
                # extra goods added at the gate travel without an order line
                line = order.order_line.filtered(
                    lambda l, p=move.product_id: l.product_id == p and not l.display_type)[:1]
            partner = (order.partner_id or move.picking_id.partner_id).commercial_partner_id
            if opts["partner_ids"] and partner.id not in opts["partner_ids"]:
                continue
            if opts["user_ids"] and order.user_id.id not in opts["user_ids"]:
                continue
            product = move.product_id
            qty = move.product_uom._compute_quantity(move.quantity, product.uom_id, rounding_method="HALF-UP")
            amount = 0.0
            if line and line.product_uom_qty:
                line_qty = move.product_uom._compute_quantity(move.quantity, line.product_uom_id,
                                                              rounding_method="HALF-UP")
                amount = line.price_subtotal / line.product_uom_qty * line_qty
                amount = convert(amount, line.order_id.currency_id, move.company_id, move.date.date())
            cost = convert(abs(move.value or 0.0), move.company_id.currency_id, move.company_id, move.date.date())
            out.append({
                "kind": "return" if is_return else "sale",
                "product": product, "order": order, "partner": partner, "user": order.user_id,
                "doc": ("order", order.id) if order and not is_return else ("picking", move.picking_id.id),
                "qty": qty, "amount": amount, "cost": cost,
                "date": fields.Datetime.context_timestamp(self, move.date).date(),
            })
        if opts["services"]:
            out += self._service_entries(opts, start, end, convert)
        return out

    @api.model
    def _service_entries(self, opts, start, end, convert):
        env = self.env(su=True)
        domain = [
            ("order_id.state", "=", "sale"),
            ("order_id.date_order", ">=", start), ("order_id.date_order", "<=", end),
            ("order_id.company_id", "in", opts["company_ids"]),
            ("product_id.type", "=", "service"),
            ("display_type", "=", False),
            ("is_downpayment", "=", False),
        ]
        if opts["categ_ids"]:
            domain.append(("product_id.categ_id", "child_of", opts["categ_ids"]))
        if opts["partner_ids"]:
            domain.append(("order_id.partner_id.commercial_partner_id", "in", opts["partner_ids"]))
        if opts["user_ids"]:
            domain.append(("order_id.user_id", "in", opts["user_ids"]))
        if opts["warehouse_ids"]:
            domain.append(("order_id.warehouse_id", "in", opts["warehouse_ids"]))
        out = []
        for line in env["sale.order.line"].search(domain):
            order = line.order_id
            product = line.product_id
            day = order.date_order.date()
            qty = line.product_uom_id._compute_quantity(line.product_uom_qty, product.uom_id,
                                                        rounding_method="HALF-UP")
            cost = product.with_company(order.company_id).standard_price * qty
            out.append({
                "kind": "sale",
                "product": product, "order": order, "partner": order.partner_id.commercial_partner_id,
                "user": order.user_id, "doc": ("order", order.id), "date": day,
                "qty": qty,
                "amount": convert(line.price_subtotal, order.currency_id, order.company_id, day),
                "cost": convert(cost, order.company_id.currency_id, order.company_id, day),
            })
        return out

    # ------------------------------------------------------------------
    # aggregation
    # ------------------------------------------------------------------
    @api.model
    def _key(self, entry, group_by):
        if group_by == "partner":
            partner = entry["partner"]
            return ("partner", partner.id), {"name": partner.name or _("Mijozsiz")}
        if group_by == "user":
            user = entry["user"]
            return ("user", user.id), {"name": user.name or _("Sotuvchisiz")}
        product = entry["product"]
        if group_by == "category":
            categ = product.categ_id
            return ("category", categ.id), {"name": categ.complete_name or _("Kategoriyasiz")}
        return ("product", product.id), {
            "name": product.product_tmpl_id.name or product.display_name,
            "char": product.cst_characteristic or "",
            "code": product.default_code or "",
            "uom": product.uom_id.name or "",
            "barcode": product.barcode or "",
        }

    @api.model
    def _finish(self, row):
        qty, ret_qty = row["qty"], row["ret_qty"]
        row["price"] = row["amount"] / qty if qty else 0.0
        row["unit_cost"] = row["cost"] / qty if qty else 0.0
        row["ret_price"] = row["ret_amount"] / ret_qty if ret_qty else 0.0
        row["ret_unit_cost"] = row["ret_cost"] / ret_qty if ret_qty else 0.0
        net_amount = row["amount"] - row["ret_amount"]
        net_cost = row["cost"] - row["ret_cost"]
        row["profit"] = net_amount - net_cost
        row["markup"] = row["profit"] / net_cost * 100.0 if net_cost else None
        row["margin"] = row["profit"] / net_amount * 100.0 if net_amount else None
        return row

    @api.model
    def _aggregate(self, entries, group_by):
        rows = {}
        total = {"qty": 0.0, "amount": 0.0, "cost": 0.0, "ret_qty": 0.0, "ret_amount": 0.0,
                 "ret_cost": 0.0, "docs": set(), "ret_docs": set()}
        for entry in entries:
            key, head = self._key(entry, group_by)
            row = rows.get(key)
            if row is None:
                row = rows[key] = dict(head, key="%s_%s" % key, res_id=key[1],
                                       qty=0.0, amount=0.0, cost=0.0, ret_qty=0.0, ret_amount=0.0, ret_cost=0.0,
                                       docs=set(), ret_docs=set(), order_ids=set())
            prefix = "ret_" if entry["kind"] == "return" else ""
            for target in (row, total):
                target[prefix + "qty"] += entry["qty"]
                target[prefix + "amount"] += entry["amount"]
                target[prefix + "cost"] += entry["cost"]
                target[prefix + "docs"].add(entry["doc"])
            if entry["order"]:
                row["order_ids"].add(entry["order"].id)
        result = []
        for row in rows.values():
            row["docs"], row["ret_docs"] = len(row["docs"]), len(row["ret_docs"])
            row["order_ids"] = sorted(row["order_ids"])
            result.append(self._finish(row))
        total["docs"], total["ret_docs"] = len(total["docs"]), len(total["ret_docs"])
        result.sort(key=lambda r: -r["amount"])
        return result, self._finish(total)

    @api.model
    def get_data(self, options):
        self._check_rights()
        opts = self._parse(options)
        rows, total = self._aggregate(self._entries(opts), opts["group_by"])
        return {
            "rows": rows,
            "total": total,
            "group_by": opts["group_by"],
            "currency": self.env.company.currency_id.name,
            "currency_symbol": self.env.company.currency_id.symbol or "",
            "date_from": fields.Date.to_string(opts["date_from"]),
            "date_to": fields.Date.to_string(opts["date_to"]),
        }

    @api.model
    def action_open_orders(self, order_ids, title=None):
        """Row drill-down: the sale orders behind the figures."""
        self._check_rights()
        return {
            "type": "ir.actions.act_window",
            "name": title or _("Buyurtmalar"),
            "res_model": "sale.order",
            "views": [(False, "list"), (False, "form")],
            "domain": [("id", "in", list(order_ids or []))],
            "target": "current",
        }
