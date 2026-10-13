from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models

_EXPENSE_STATES = ("approved", "posted", "in_payment", "paid")

MRF_STATE_LABELS = {
    "draft": "Draft",
    "to_approve": "To Approve",
    "approved": "Approved",
    "assigned": "Assigned",
    "purchased": "Ordered",
    "done": "Done",
    "cancel": "Cancelled",
}

MO_STATE_LABELS = {
    "draft": "Draft",
    "confirmed": "Confirmed",
    "progress": "In Progress",
    "to_close": "To Close",
    "done": "Done",
    "cancel": "Cancelled",
}


class KeramaProjectDashboard(models.AbstractModel):
    _name = "kerama.project.dashboard"
    _description = "Khatdecor Project Dashboard Data Provider"

    # ------------------------------------------------------------------
    #  Filter helpers
    # ------------------------------------------------------------------
    @api.model
    def get_currency_options(self):
        """Currencies a dashboard can be read in."""
        currencies = self.env["res.currency"].search([("active", "=", True)])
        company_currency = self.env.company.currency_id
        return {
            "currencies": [
                {"id": c.id, "name": c.name, "symbol": c.symbol or c.name}
                for c in currencies.sorted(lambda c: (c != company_currency, c.name))
            ],
            "company_currency_id": company_currency.id,
        }

    def _cst_currency(self, filters, company):
        """The currency the figures are read in: the chosen one, else the company's."""
        currency_id = (filters or {}).get("currency_id")
        if currency_id:
            currency = self.env["res.currency"].browse(int(currency_id)).exists()
            if currency:
                return currency
        return company.currency_id

    def _period_start(self, period):
        today = fields.Date.context_today(self)
        if period == "month":
            return today.replace(day=1)
        if period == "quarter":
            quarter = (today.month - 1) // 3
            return today.replace(month=quarter * 3 + 1, day=1)
        if period == "year":
            return today.replace(month=1, day=1)
        if period == "last12":
            first = today.replace(day=1)
            month = first.month - 11
            year = first.year
            while month <= 0:
                month += 12
                year -= 1
            return first.replace(year=year, month=month)
        return False

    def _date_bounds(self, filters):
        """(start, end) as dates; either side may be False for 'open ended'."""
        period = filters.get("period", "all")
        if period == "custom":
            start = filters.get("date_from") and fields.Date.to_date(filters["date_from"])
            end = filters.get("date_to") and fields.Date.to_date(filters["date_to"])
            return start or False, end or False
        return self._period_start(period), False

    def _bucket(self, date_value, granularity):
        if not date_value:
            return "—"
        if hasattr(date_value, "date"):
            date_value = date_value.date()
        if granularity == "week":
            monday = date_value - timedelta(days=date_value.weekday())
            return monday.strftime("%Y-W%V")
        return date_value.strftime("%Y-%m")

    def _expense_states(self, include_draft):
        if not include_draft:
            return list(_EXPENSE_STATES)
        selection = self.env["hr.expense"]._fields["state"].selection
        if callable(selection):
            return list(_EXPENSE_STATES)
        return [key for key, _label in selection if key not in ("refused", "cancel")]

    def _domain_dates(self, field, start, end, as_datetime=True):
        domain = []
        if start:
            value = fields.Datetime.to_datetime(start) if as_datetime else start
            domain.append((field, ">=", value))
        if end:
            if as_datetime:
                domain.append((field, "<=", fields.Datetime.to_datetime(end) + timedelta(
                    hours=23, minutes=59, seconds=59)))
            else:
                domain.append((field, "<=", end))
        return domain

    def _component_unit_costs(self, products, company, project=False, quantities=None):
        """Unit cost per product, in company currency and in the product UoM.

        Materials bought for the project are valued at what the project paid
        for them (average price over the project's purchase orders); anything
        taken from our own warehouses is valued at its cost price.  When
        ``quantities`` (product id -> consumed qty) is given and a product was
        used beyond what the project bought, the two rates are blended.
        """
        comp_ccy = company.currency_id
        today = fields.Date.context_today(self)
        costs = {p.id: (p.with_company(company).standard_price or 0.0) for p in products}
        if not project or not costs:
            return costs

        bought = {}  # product id -> [qty, value] purchased for this project
        lines = self.env["purchase.order.line"].search([
            ("product_id", "in", list(costs)),
            ("order_id.project_id", "=", project.id),
            ("order_id.state", "in", ("purchase", "done")),
        ])
        for line in lines:
            product = line.product_id
            qty = line.product_uom_id._compute_quantity(line.product_qty, product.uom_id)
            if not qty:
                continue
            order = line.order_id
            value = line.price_subtotal
            if order.currency_id and order.currency_id != comp_ccy:
                rate_date = order.date_order and order.date_order.date() or today
                value = order.currency_id._convert(value, comp_ccy, company, rate_date)
            entry = bought.setdefault(product.id, [0.0, 0.0])
            entry[0] += qty
            entry[1] += value

        for product_id, (qty, value) in bought.items():
            if not value:
                continue
            purchase_rate = value / qty
            used = (quantities or {}).get(product_id) or 0.0
            if used > qty:
                # part of it came out of our own stock, valued at cost price
                costs[product_id] = (
                    qty * purchase_rate + (used - qty) * costs[product_id]) / used
            else:
                costs[product_id] = purchase_rate
        return costs

    # ------------------------------------------------------------------
    #  Cross-project overview (Dashboard > Projects)
    # ------------------------------------------------------------------
    @api.model
    def get_project_overview(self, filters=None):
        """All figures for the Projects dashboard, in company currency.

        filters: {'period': 'all' | 'year' | 'quarter' | 'month' | 'last12'}
        """
        filters = filters or {}
        company = self.env.company
        comp_ccy = company.currency_id
        target = self._cst_currency(filters, company)
        start = self._period_start(filters.get("period", "all"))
        today = fields.Date.context_today(self)

        def convert(amount, currency, date=None):
            currency = currency or comp_ccy
            if not amount or currency == target:
                return amount
            return currency._convert(amount, target, company, date or today)

        # ---- per-project accumulators (company currency) ----------------
        per_project = defaultdict(lambda: {
            "income": 0.0, "paid": 0.0, "due": 0.0,
            "purchases": 0.0, "expenses": 0.0,
        })
        month_income = defaultdict(float)
        month_cost = defaultdict(float)

        so_domain = [("project_id", "!=", False), ("state", "=", "sale")]
        if start:
            so_domain.append(("date_order", ">=", fields.Datetime.to_datetime(start)))
        for order in self.env["sale.order"].search(so_domain):
            rate_date = order.date_order and order.date_order.date() or today
            income = convert(order.amount_total, order.currency_id, rate_date)
            due = convert(order.payment_amount_due, order.currency_id, rate_date)
            bucket = per_project[order.project_id.id]
            bucket["income"] += income
            bucket["due"] += due
            bucket["paid"] += income - due
            month_income[order.date_order.strftime("%Y-%m") if order.date_order else "—"] += income

        po_domain = [("project_id", "!=", False), ("state", "=", "purchase")]
        if start:
            po_domain.append(("date_order", ">=", fields.Datetime.to_datetime(start)))
        po_count = 0
        for po in self.env["purchase.order"].search(po_domain):
            po_count += 1
            rate_date = po.date_order and po.date_order.date() or today
            amount = convert(po.amount_total, po.currency_id, rate_date)
            per_project[po.project_id.id]["purchases"] += amount
            month_cost[po.date_order.strftime("%Y-%m") if po.date_order else "—"] += amount

        exp_domain = [("project_id", "!=", False), ("state", "in", _EXPENSE_STATES)]
        if start:
            exp_domain.append(("date", ">=", start))
        for exp in self.env["hr.expense"].search(exp_domain):
            # total_amount is written in the currency of the expense's own company
            amount = convert(exp.total_amount, exp.company_currency_id or comp_ccy, exp.date)
            per_project[exp.project_id.id]["expenses"] += amount
            month_cost[exp.date.strftime("%Y-%m") if exp.date else "—"] += amount

        # ---- rows + totals ----------------------------------------------
        projects = self.env["project.project"].browse(list(per_project))
        names = {p.id: p.display_name for p in projects}
        rows, totals = [], defaultdict(float)
        for project_id, vals in per_project.items():
            margin = vals["income"] - vals["purchases"] - vals["expenses"]
            row = {"id": project_id, "name": names.get(project_id, "?"),
                   "margin": margin, **vals}
            rows.append(row)
            for key in ("income", "paid", "due", "purchases", "expenses"):
                totals[key] += vals[key]
            totals["margin"] += margin
        rows.sort(key=lambda r: r["margin"], reverse=True)

        # ---- income vs cost over time ------------------------------------
        months = sorted(set(month_income) | set(month_cost))
        over_time = {
            "labels": months,
            "income": [round(month_income.get(m, 0.0), 2) for m in months],
            "cost": [round(month_cost.get(m, 0.0), 2) for m in months],
        }

        # ---- dues by project (top 10) -------------------------------------
        due_rows = sorted((r for r in rows if r["due"] > 0),
                          key=lambda r: r["due"], reverse=True)[:10]

        # ---- MRF statistics ----------------------------------------------
        mrf_domain = []
        if start:
            mrf_domain.append(("date_request", ">=", start))
        mrf_by_state = {}
        open_mrfs = 0
        for state, count in self.env["cst.material.request"]._read_group(
                mrf_domain, groupby=["state"], aggregates=["__count"]):
            mrf_by_state[MRF_STATE_LABELS.get(state, state)] = count
            if state not in ("done", "cancel"):
                open_mrfs += count

        line_domain = [("qty_to_buy", ">", 0)]
        if start:
            line_domain.append(("request_id.date_request", ">=", start))
        mrf_lines = self.env["cst.material.request.line"].search(line_domain)
        materials = {
            "to_buy": len(mrf_lines.filtered(lambda l: not l.purchase_line_id)),
            "ordered": len(mrf_lines.filtered("purchase_line_id")),
        }

        # ---- manufacturing -------------------------------------------------
        mo_domain = [("project_id", "!=", False), ("state", "!=", "cancel")]
        if start:
            mo_domain.append(("date_start", ">=", fields.Datetime.to_datetime(start)))
        productions = self.env["mrp.production"].search(mo_domain)
        mo_by_state = defaultdict(int)
        for production in productions:
            mo_by_state[MO_STATE_LABELS.get(production.state, production.state)] += 1
        consumed = sum(
            move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)
            for move in productions.move_raw_ids if move.state == "done")
        manufacturing = {
            "mos": len(productions),
            "open": len(productions.filtered(
                lambda p: p.state in ("confirmed", "progress", "to_close"))),
            "qty_planned": round(sum(productions.mapped("product_qty")), 2),
            "qty_produced": round(sum(productions.mapped("qty_produced")), 2),
            "qty_consumed": round(consumed, 2),
            "material_cost": round(convert(
                sum(productions.mapped("cst_material_cost")), comp_ccy), 2),
            "by_state": dict(mo_by_state),
        }

        return {
            "currency": target.name,
            "currency_id": target.id,
            "currency_symbol": target.symbol or target.name,
            "period": filters.get("period", "all"),
            "totals": {k: round(v, 2) for k, v in totals.items()},
            "counts": {
                "projects": len(rows),
                "purchase_orders": po_count,
                "mrfs": sum(mrf_by_state.values()),
                "open_mrfs": open_mrfs,
                "mos": manufacturing["mos"],
            },
            "projects": rows,
            "over_time": over_time,
            "cost_split": {
                "purchases": round(totals["purchases"], 2),
                "expenses": round(totals["expenses"], 2),
            },
            "due_by_project": [{"name": r["name"], "due": round(r["due"], 2)} for r in due_rows],
            "mrf_by_state": mrf_by_state,
            "materials": materials,
            "manufacturing": manufacturing,
        }

    # ------------------------------------------------------------------
    #  Single-project hub
    # ------------------------------------------------------------------
    @api.model
    def get_project_list(self):
        """Lightweight project picker for the hub dashboard."""
        projects = self.env["project.project"].search([("is_template", "=", False)])
        return [{"id": p.id, "name": p.display_name} for p in projects]

    @api.model
    def get_project_detail(self, project_id, filters=None):
        """Everything about one project: sales, purchases, manufacturing, expenses."""
        filters = filters or {}
        project = self.env["project.project"].browse(int(project_id)).exists()
        if not project:
            return {"error": "not_found"}

        company = project.company_id or self.env.company
        comp_ccy = company.currency_id
        target = self._cst_currency(filters, company) if filters.get("currency_id") \
            else (project.cst_display_currency_id or comp_ccy)
        today = fields.Date.context_today(self)
        start, end = self._date_bounds(filters)
        granularity = filters.get("granularity", "month")
        include_draft = bool(filters.get("include_draft"))

        def convert(amount, currency, date=None):
            currency = currency or comp_ccy
            if not amount or currency == target:
                return amount
            return currency._convert(amount, target, company, date or today)

        bucket_income = defaultdict(float)
        bucket_cost = defaultdict(float)

        # ---- sales --------------------------------------------------------
        sale_states = ["sale"] + (["draft", "sent"] if include_draft else [])
        so_domain = [("project_id", "=", project.id), ("state", "in", sale_states)]
        so_domain += self._domain_dates("date_order", start, end)
        sales, income = [], {"total": 0.0, "paid": 0.0, "due": 0.0}
        for order in self.env["sale.order"].search(so_domain, order="date_order desc"):
            rate_date = order.date_order and order.date_order.date() or today
            total = convert(order.amount_total, order.currency_id, rate_date)
            due = convert(order.payment_amount_due, order.currency_id, rate_date)
            confirmed = order.state == "sale"
            if confirmed:
                income["total"] += total
                income["due"] += due
                income["paid"] += total - due
                bucket_income[self._bucket(order.date_order, granularity)] += total
            sales.append({
                "id": order.id,
                "name": order.name,
                "date": order.date_order and fields.Datetime.to_string(order.date_order)[:10],
                "partner": order.partner_id.display_name,
                "amount": round(total, 2),
                "paid": round(total - due, 2),
                "due": round(due, 2),
                "state": order.state,
                "state_label": dict(order._fields["state"].selection).get(order.state, order.state),
            })

        # ---- purchases ----------------------------------------------------
        po_states = ["purchase", "done"] + (["draft", "sent"] if include_draft else [])
        po_domain = [("project_id", "=", project.id), ("state", "in", po_states)]
        po_domain += self._domain_dates("date_order", start, end)
        purchases, purchase_total = [], 0.0
        for po in self.env["purchase.order"].search(po_domain, order="date_order desc"):
            rate_date = po.date_order and po.date_order.date() or today
            amount = convert(po.amount_total, po.currency_id, rate_date)
            if po.state in ("purchase", "done"):
                purchase_total += amount
                bucket_cost[self._bucket(po.date_order, granularity)] += amount
            purchases.append({
                "id": po.id,
                "name": po.name,
                "date": po.date_order and fields.Datetime.to_string(po.date_order)[:10],
                "partner": po.partner_id.display_name,
                "amount": round(amount, 2),
                "state": po.state,
                "state_label": dict(po._fields["state"].selection).get(po.state, po.state),
                "buyer": po.user_id.display_name or "",
            })

        # ---- expenses -----------------------------------------------------
        exp_domain = [("project_id", "=", project.id),
                      ("state", "in", self._expense_states(include_draft))]
        exp_domain += self._domain_dates("date", start, end, as_datetime=False)
        expenses, expense_total = [], 0.0
        for expense in self.env["hr.expense"].search(exp_domain, order="date desc"):
            # total_amount is written in the currency of the expense's own company
            amount = convert(expense.total_amount, expense.company_currency_id or comp_ccy, expense.date)
            if expense.state in _EXPENSE_STATES:
                expense_total += amount
                bucket_cost[self._bucket(expense.date, granularity)] += amount
            expenses.append({
                "id": expense.id,
                "name": expense.name,
                "date": expense.date and fields.Date.to_string(expense.date),
                "employee": expense.employee_id.display_name or "",
                "amount": round(amount, 2),
                "state": expense.state,
                "state_label": dict(expense._fields["state"].selection).get(
                    expense.state, expense.state),
            })

        # ---- manufacturing -------------------------------------------------
        mo_states = ["confirmed", "progress", "to_close", "done"] + (
            ["draft"] if include_draft else [])
        mo_domain = [("project_id", "=", project.id), ("state", "in", mo_states)]
        mo_domain += self._domain_dates("date_start", start, end)
        productions = self.env["mrp.production"].search(mo_domain, order="date_start desc")

        mo_rows, mo_by_state = [], defaultdict(int)
        used = defaultdict(lambda: {"qty": 0.0, "cost": 0.0, "uom": ""})
        ready = defaultdict(lambda: {"qty": 0.0, "planned": 0.0, "uom": ""})
        consumed_qty = defaultdict(float)
        for move in productions.move_raw_ids:
            if move.state == "done":
                consumed_qty[move.product_id.id] += move.product_uom._compute_quantity(
                    move.quantity, move.product_id.uom_id)
        unit_costs = self._component_unit_costs(
            productions.move_raw_ids.product_id, company, project, consumed_qty)
        material_cost = 0.0
        for production in productions:
            mo_by_state[MO_STATE_LABELS.get(production.state, production.state)] += 1
            row = {
                "id": production.id,
                "name": production.name,
                "product": production.product_id.cst_base_name(),
                "characteristic": production.product_id.cst_characteristic or "",
                "qty": round(production.product_qty, 2),
                "produced": round(production.qty_produced, 2),
                "uom": production.product_uom_id.display_name,
                "date": production.date_start and fields.Datetime.to_string(
                    production.date_start)[:10],
                "state": production.state,
                "state_label": MO_STATE_LABELS.get(production.state, production.state),
                "cost": 0.0,
                "availability": production.components_availability or "",
                # what the shifts counted on this order
                "second": round(production.cst_second_qty, 2),
                "scrap": round(production.cst_scrap_qty, 2),
            }
            mo_rows.append(row)
            finished = ready[production.product_id.id]
            finished["name"] = production.product_id.cst_base_name()
            finished["characteristic"] = production.product_id.cst_characteristic or ""
            finished["uom"] = production.product_uom_id.display_name
            finished["qty"] += production.qty_produced
            finished["planned"] += production.product_qty
            mo_cost = 0.0
            for move in production.move_raw_ids:
                if move.state != "done":
                    continue
                product = move.product_id
                qty = move.product_uom._compute_quantity(move.quantity, product.uom_id)
                value = convert(qty * unit_costs.get(product.id, 0.0), comp_ccy,
                                production.date_start and production.date_start.date())
                entry = used[product.id]
                entry["name"] = product.cst_base_name()
                entry["characteristic"] = product.cst_characteristic or ""
                entry["uom"] = product.uom_id.display_name
                entry["qty"] += qty
                entry["cost"] += value
                mo_cost += value
            row["cost"] = round(mo_cost, 2)
            material_cost += mo_cost

        materials_used = sorted(
            ({"id": pid, "name": v.get("name", "?"), "qty": round(v["qty"], 2),
              "uom": v["uom"], "cost": round(v["cost"], 2),
              "characteristic": v.get("characteristic", "")}
             for pid, v in used.items() if v["qty"]),
            key=lambda r: r["cost"], reverse=True)
        products_ready = sorted(
            ({"id": pid, "name": v.get("name", "?"), "qty": round(v["qty"], 2),
              "planned": round(v["planned"], 2), "uom": v["uom"],
              "characteristic": v.get("characteristic", "")}
             for pid, v in ready.items()),
            key=lambda r: r["qty"], reverse=True)

        qty_planned = sum(productions.mapped("product_qty"))
        qty_produced = sum(productions.mapped("qty_produced"))
        qty_consumed = sum(r["qty"] for r in materials_used)

        # ---- material requests ---------------------------------------------
        mrf_domain = [("project_id", "=", project.id)]
        mrf_domain += self._domain_dates("date_request", start, end, as_datetime=False)
        mrfs = self.env["cst.material.request"].search(mrf_domain, order="id desc")
        mrf_rows = [{
            "id": mrf.id,
            "name": mrf.name,
            "date": mrf.date_request and fields.Date.to_string(mrf.date_request),
            "state": mrf.state,
            "state_label": MRF_STATE_LABELS.get(mrf.state, mrf.state),
            "lines": len(mrf.line_ids),
            "to_buy": mrf.buy_line_count,
            "to_manufacture": mrf.manufacture_line_count,
            "pos": mrf.purchase_count,
            "mos": mrf.production_count,
        } for mrf in mrfs]

        # ---- material tracking lines ----------------------------------------
        material_rows = [{
            "id": line.id,
            # the base name and the characteristic in columns of their own, so a
            # product bought in three finishes reads as three lines, not one
            "product": line.product_id.cst_base_name(),
            "characteristic": line.product_id.cst_characteristic or "",
            "kind": line.kind,
            "required": round(line.product_qty, 2),
            "available": round(line.qty_available, 2),
            "to_buy": round(line.qty_to_buy, 2),
            "to_produce": round(line.qty_to_produce, 2),
            "uom": line.product_uom_id.display_name,
            "where": line.stock_by_location or "",
            "po": line.purchase_order_id.name or "",
            "po_id": line.purchase_order_id.id or False,
            "po_state": line.purchase_state or "",
            "mo": line.production_id.name or "",
            "mo_id": line.production_id.id or False,
            "mo_state": line.production_state or "",
        } for line in mrfs.line_ids]

        # ---- ready to manufacture ---------------------------------------------
        ready_lines = project._cst_manufacture_lines()
        plan_entries = project._cst_manufacture_plan()
        plan_missing = project._cst_manufacture_missing_list(plan_entries)

        # ---- time series ------------------------------------------------------
        labels = sorted(set(bucket_income) | set(bucket_cost))
        # same rule as the project form and the overview dashboard: the material
        # was already paid for under Purchases, so it is reported but not
        # subtracted a second time
        margin = income["total"] - purchase_total - expense_total

        return {
            "project": {
                "id": project.id,
                "name": project.display_name,
                "partner": project.partner_id.display_name or "",
                "manager": project.user_id.display_name or "",
                "company": company.display_name,
                "date_start": project.date_start and fields.Date.to_string(project.date_start),
                "date_end": project.date and fields.Date.to_string(project.date),
                "tasks": project.task_count,
                "can_manufacture": bool(ready_lines),
                "ready_products": ", ".join(
                    ready_lines.mapped("product_id.display_name")[:4]),
                # the whole plan, not only what a material request asked for:
                # a project whose materials were in stock from the start never
                # raised a request, and still has products to make
                "plan_count": len(plan_entries),
                "plan_products": ", ".join(
                    e["product"].display_name for e in plan_entries[:4]),
                "plan_missing": ", ".join(plan_missing),
                "manufacture_ready": bool(plan_entries) and not plan_missing,
            },
            "currency": target.name,
            "currency_id": target.id,
            "currency_symbol": target.symbol or target.name,
            "filters": {
                "period": filters.get("period", "all"),
                "date_from": filters.get("date_from"),
                "date_to": filters.get("date_to"),
                "include_draft": include_draft,
                "granularity": granularity,
            },
            "kpis": {
                "income": round(income["total"], 2),
                "paid": round(income["paid"], 2),
                "due": round(income["due"], 2),
                "purchases": round(purchase_total, 2),
                "expenses": round(expense_total, 2),
                "materials": round(material_cost, 2),
                "cost": round(purchase_total + expense_total, 2),
                "margin": round(margin, 2),
                "margin_pct": round(margin / income["total"] * 100, 1) if income["total"] else 0.0,
                "material_cost": round(material_cost, 2),
                "qty_planned": round(qty_planned, 2),
                "qty_produced": round(qty_produced, 2),
                "qty_consumed": round(qty_consumed, 2),
                "produced_pct": round(qty_produced / qty_planned * 100, 1) if qty_planned else 0.0,
                "collected_pct": round(
                    income["paid"] / income["total"] * 100, 1) if income["total"] else 0.0,
            },
            "counts": {
                "sales": len(sales),
                "purchases": len(purchases),
                "expenses": len(expenses),
                "mos": len(mo_rows),
                "mos_open": len(productions.filtered(
                    lambda p: p.state in ("confirmed", "progress", "to_close"))),
                "mrfs": len(mrf_rows),
                "mrf_open": len([r for r in mrf_rows if r["state"] not in ("done", "cancel")]),
                "materials": len(material_rows),
                "ready_to_make": len(ready_lines),
            },
            "over_time": {
                "labels": labels,
                "income": [round(bucket_income.get(k, 0.0), 2) for k in labels],
                "cost": [round(bucket_cost.get(k, 0.0), 2) for k in labels],
            },
            "cost_split": {
                "materials": round(material_cost, 2),
                "expenses": round(expense_total, 2),
            },
            "mo_by_state": dict(mo_by_state),
            "sales": sales,
            "purchases": purchases,
            "expenses": expenses,
            "productions": mo_rows,
            "materials_used": materials_used,
            "products_ready": products_ready,
            "mrfs": mrf_rows,
            "materials": material_rows,
        }
