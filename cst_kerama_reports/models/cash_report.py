from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models

EXPENSE_TYPES = ("expense", "expense_depreciation")
DIRECT_COST_TYPES = ("expense_direct_cost",)


class CstCashReport(models.AbstractModel):
    """«Pullar harakati» — every cash box and bank account over a period.

    A journal's money lives on its default account; the report reads that
    account's posted journal items. Amounts are in the journal's own currency
    (a USD cash box is read in dollars, the so'm box in so'm) — the company
    currency figure sits next to it so the boxes can still be added up.
    """

    _name = "cst.cash.report"
    _description = "Pullar harakati"

    @api.model
    def _journals(self, journal_ids=None, company_ids=None):
        companies = self.env.companies
        if company_ids:
            companies = companies.filtered(lambda c: c.id in company_ids) or companies
        domain = [("type", "in", ("cash", "bank")), ("company_id", "in", companies.ids)]
        if journal_ids:
            domain.append(("id", "in", journal_ids))
        return self.env["account.journal"].search(domain, order="company_id, type desc, sequence, id")

    @api.model
    def _amount(self, journal, line):
        """Journal-currency amount and company-currency amount of one item."""
        if journal.currency_id and journal.currency_id != journal.company_id.currency_id:
            return line.amount_currency or 0.0, line.balance or 0.0
        return line.balance or 0.0, line.balance or 0.0

    @api.model
    def _label(self, line):
        move = line.move_id
        bits = [move.name if move.name and move.name != "/" else ""]
        if line.partner_id:
            bits.append(line.partner_id.display_name)
        detail = line.name or move.ref or ""
        if detail:
            bits.append(detail)
        return " · ".join(b for b in bits if b)

    @api.model
    def journal_block(self, journal, date_from, date_to, detail=True):
        Line = self.env["account.move.line"].sudo()
        base = [("account_id", "=", journal.default_account_id.id),
                ("parent_state", "=", "posted"),
                ("company_id", "=", journal.company_id.id)]
        opening = opening_cc = 0.0
        for line in Line.search(base + [("date", "<", date_from)]):
            amount, amount_cc = self._amount(journal, line)
            opening += amount
            opening_cc += amount_cc
        lines = Line.search(base + [("date", ">=", date_from), ("date", "<=", date_to)],
                            order="date, id")
        rows, balance = [], opening
        inflow = outflow = inflow_cc = outflow_cc = 0.0
        for line in lines:
            amount, amount_cc = self._amount(journal, line)
            balance += amount
            if amount >= 0:
                inflow += amount
                inflow_cc += amount_cc
            else:
                outflow += -amount
                outflow_cc += -amount_cc
            if detail:
                rows.append({
                    "line": line, "date": line.date, "label": self._label(line),
                    "inflow": amount if amount > 0 else 0.0,
                    "outflow": -amount if amount < 0 else 0.0,
                    "balance": balance,
                })
        return {
            "journal": journal,
            "currency": journal.currency_id or journal.company_id.currency_id,
            "opening": opening, "inflow": inflow, "outflow": outflow, "closing": balance,
            "opening_cc": opening_cc, "inflow_cc": inflow_cc, "outflow_cc": outflow_cc,
            "closing_cc": opening_cc + inflow_cc - outflow_cc,
            "rows": rows,
        }

    @api.model
    def build(self, date_from, date_to, journal_ids=None, company_ids=None, detail=True):
        result = []
        for journal in self._journals(journal_ids, company_ids):
            block = self.journal_block(journal, date_from, date_to, detail=detail)
            if not any((block["opening"], block["inflow"], block["outflow"])):
                continue
            company = journal.company_id
            entry = next((r for r in result if r["company"] == company), None)
            if not entry:
                entry = {"company": company, "journals": [],
                         "opening_cc": 0.0, "inflow_cc": 0.0, "outflow_cc": 0.0,
                         "closing_cc": 0.0}
                result.append(entry)
            entry["journals"].append(block)
            for key in ("opening_cc", "inflow_cc", "outflow_cc", "closing_cc"):
                entry[key] += block[key]
        return result


class CstExpenseReport(models.AbstractModel):
    """«Xarajatlar hisoboti» — expense accounts by group, optionally only the
    ones paid straight from the cash desk, optionally in dollars."""

    _name = "cst.expense.report"
    _description = "Xarajatlar hisoboti"

    @api.model
    def build(self, date_from, date_to, company_ids=None, journal_types=None,
              display_currency=None, include_direct_cost=False, detail=False):
        companies = self.env.companies
        if company_ids:
            companies = companies.filtered(lambda c: c.id in company_ids) or companies
        types = EXPENSE_TYPES + (DIRECT_COST_TYPES if include_direct_cost else ())
        domain = [
            ("parent_state", "=", "posted"),
            ("company_id", "in", companies.ids),
            ("account_id.account_type", "in", types),
            ("date", ">=", date_from), ("date", "<=", date_to),
        ]
        if journal_types:
            domain.append(("journal_id.type", "in", list(journal_types)))
        lines = self.env["account.move.line"].sudo().search(domain, order="date, id")

        result = []
        for company in companies:
            target = display_currency or company.currency_id
            groups = {}
            total = 0.0
            for line in lines.filtered(lambda l: l.company_id == company):
                amount = company.currency_id._convert(
                    line.balance or 0.0, target, company, line.date or date_to)
                account = line.account_id
                group = account.group_id
                gkey = group.id if group else 0
                g = groups.setdefault(gkey, {
                    "group": group, "name": group.name if group else "Guruhsiz",
                    "accounts": {}, "amount": 0.0})
                a = g["accounts"].setdefault(account.id, {
                    "account": account, "amount": 0.0, "rows": []})
                a["amount"] += amount
                g["amount"] += amount
                total += amount
                if detail:
                    a["rows"].append({
                        "line": line, "date": line.date,
                        "partner": line.partner_id.display_name or "",
                        "label": line.name or line.move_id.ref or line.move_id.name or "",
                        "journal": line.journal_id.name,
                        "amount": amount,
                    })
            if not groups:
                continue
            for g in groups.values():
                g["accounts"] = sorted(g["accounts"].values(),
                                       key=lambda a: a["account"].code or "")
            result.append({
                "company": company,
                "currency": target,
                "groups": sorted(groups.values(), key=lambda g: g["name"] or ""),
                "amount": total,
            })
        return result


class CstDirectorDashboard(models.AbstractModel):
    """Data behind «Rahbar oynasi».

    One call returns everything the screen shows: the cash position and its
    history, money in and out, sales against last month, expenses by group,
    debts both ways with their age, what the warehouse is worth, what the
    shop floor made, what is owed to staff. Read as superuser, then clamped to
    the companies the user may enter — the director reads figures, not journal
    items, and the menu itself is group-restricted.

    Two clocks on purpose: the *period* (7/30/90 days, the filter row) drives
    the cash history and the flow totals; *this month against last month* is a
    fixed comparison every tile with a delta uses, because "bu oy" is how the
    company talks about its results.
    """

    _name = "cst.director.dashboard"
    _description = "Rahbar oynasi"

    WEEKDAYS = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]
    MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust",
              "sentabr", "oktabr", "noyabr", "dekabr"]

    @api.model
    def get_data(self, filters=None):
        filters = filters or {}
        companies = self.env.companies
        wanted = [c for c in (filters.get("company_ids") or []) if c in companies.ids]
        if wanted:
            companies = companies.filtered(lambda c: c.id in wanted)
        currency = companies[:1].currency_id or self.env.company.currency_id
        today = fields.Date.context_today(self)
        days = int(filters.get("days") or 30)
        days = days if days in (7, 30, 90) else 30
        since = today - timedelta(days=days - 1)
        month_start = fields.Date.start_of(today, "month")
        prev_start = fields.Date.start_of(month_start - timedelta(days=1), "month")
        prev_end = month_start - timedelta(days=1)

        cash = self._cash(companies, since, today, month_start, prev_start, prev_end)
        return {
            "meta": {
                "today": fields.Date.to_string(today),
                "today_label": "%d-%s %d, %s" % (today.day, self.MONTHS[today.month - 1],
                                                 today.year, self.WEEKDAYS[today.weekday()]),
                "generated_at": fields.Datetime.context_timestamp(
                    self, fields.Datetime.now()).strftime("%H:%M"),
                "currency": currency.name,
                "symbol": currency.symbol,
                "days": days,
                "since": fields.Date.to_string(since),
                "month_label": self.MONTHS[today.month - 1],
                "prev_month_label": self.MONTHS[prev_start.month - 1],
                "companies": [{"id": c.id, "name": c.name} for c in self.env.companies],
                "selected_company_ids": companies.ids,
            },
            "cash": cash,
            "sales": self._sales(companies, since, today, month_start, prev_start, prev_end),
            "expenses": self._expenses(companies, since, today, month_start, prev_start, prev_end),
            "debts": self._debts(companies, today),
            "stock": self._stock(companies, month_start),
            "production": self._production(companies, month_start, prev_start, prev_end),
            "payroll": self._payroll(companies, month_start),
        }

    # ------------------------------------------------------------------ cash
    @api.model
    def _cash(self, companies, since, today, month_start, prev_start, prev_end):
        Cash = self.env["cst.cash.report"]
        journals = Cash._journals(company_ids=companies.ids)
        Line = self.env["account.move.line"].sudo()
        accounts = journals.default_account_id
        base = [("account_id", "in", accounts.ids), ("parent_state", "=", "posted")]

        def flows(date_from, date_to):
            inflow = outflow = 0.0
            for row in Line.search_read(
                    base + [("date", ">=", date_from), ("date", "<=", date_to)], ["balance"]):
                if row["balance"] > 0:
                    inflow += row["balance"]
                else:
                    outflow += -row["balance"]
            return inflow, outflow

        boxes, total_cc = [], 0.0
        for journal in journals:
            block = Cash.journal_block(journal, today, today, detail=True)
            total_cc += block["closing_cc"]
            boxes.append({
                "id": journal.id, "name": journal.name, "company": journal.company_id.name,
                "type": journal.type,
                "currency": block["currency"].name, "symbol": block["currency"].symbol,
                "balance": block["closing"], "balance_cc": block["closing_cc"],
                "today_in": block["inflow"], "today_out": block["outflow"],
            })
        boxes.sort(key=lambda b: -abs(b["balance_cc"]))
        today_in, today_out = flows(today, today)
        period_in, period_out = flows(since, today)
        month_in, month_out = flows(month_start, today)
        prev_in, prev_out = flows(prev_start, prev_end)
        series = self._cash_series(journals, since, today)
        return {
            "total": total_cc, "boxes": boxes,
            "today_in": today_in, "today_out": today_out,
            "period_in": period_in, "period_out": period_out,
            "month_in": month_in, "month_out": month_out,
            "prev_month_in": prev_in, "prev_month_out": prev_out,
            "period_delta": (series["balance"][-1] - series["balance"][0]) if series["balance"] else 0.0,
            "series": series,
        }

    @api.model
    def _cash_series(self, journals, since, today):
        """Daily closing cash, all boxes together, in company currency."""
        Line = self.env["account.move.line"].sudo()
        accounts = journals.default_account_id
        opening = Line._read_group(
            [("account_id", "in", accounts.ids), ("parent_state", "=", "posted"),
             ("date", "<", since)], aggregates=["balance:sum"])[0][0] or 0.0
        per_day = defaultdict(lambda: [0.0, 0.0])
        for row in Line.search_read(
                [("account_id", "in", accounts.ids), ("parent_state", "=", "posted"),
                 ("date", ">=", since), ("date", "<=", today)], ["date", "balance"]):
            bucket = per_day[row["date"]]
            if row["balance"] > 0:
                bucket[0] += row["balance"]
            else:
                bucket[1] += -row["balance"]
        labels, dates, balances, inflows, outflows = [], [], [], [], []
        running, day = opening, since
        while day <= today:
            inflow, outflow = per_day.get(day, (0.0, 0.0))
            running += inflow - outflow
            labels.append(day.strftime("%d.%m"))
            dates.append(fields.Date.to_string(day))
            balances.append(round(running, 2))
            inflows.append(round(inflow, 2))
            outflows.append(round(outflow, 2))
            day += timedelta(days=1)
        return {"labels": labels, "dates": dates, "balance": balances,
                "inflow": inflows, "outflow": outflows}

    # ----------------------------------------------------------------- sales
    @api.model
    def _sales(self, companies, since, today, month_start, prev_start, prev_end):
        Order = self.env["sale.order"].sudo()
        base = [("company_id", "in", companies.ids), ("state", "=", "sale")]

        def between(d1, d2):
            row = Order._read_group(
                base + [("date_order", ">=", fields.Datetime.to_datetime(d1)),
                        ("date_order", "<=", fields.Datetime.to_datetime(d2).replace(
                            hour=23, minute=59, second=59))],
                aggregates=["amount_total:sum", "__count"])[0]
            return {"amount": row[0] or 0.0, "count": row[1] or 0}

        # daily series for the sparkline, period long
        daily = defaultdict(float)
        for row in Order.search_read(
                base + [("date_order", ">=", fields.Datetime.to_datetime(since))],
                ["date_order", "amount_total"]):
            daily[fields.Datetime.context_timestamp(self, row["date_order"]).date()] += row["amount_total"]
        series, day = [], since
        while day <= today:
            series.append(round(daily.get(day, 0.0), 2))
            day += timedelta(days=1)

        by_company = [
            {"name": company.name, "amount": amount or 0.0, "count": count or 0}
            for company, amount, count in Order._read_group(
                base + [("date_order", ">=", fields.Datetime.to_datetime(month_start))],
                groupby=["company_id"], aggregates=["amount_total:sum", "__count"])]
        by_company.sort(key=lambda r: -r["amount"])

        SoLine = self.env["sale.order.line"].sudo()
        products = SoLine._read_group(
            [("order_id.company_id", "in", companies.ids), ("order_id.state", "=", "sale"),
             ("order_id.date_order", ">=", fields.Datetime.to_datetime(month_start)),
             ("product_id", "!=", False), ("display_type", "=", False)],
            groupby=["product_id"], aggregates=["product_uom_qty:sum", "price_subtotal:sum"])
        # grouped by variant, so each characteristic ranks on its own line
        top_products = sorted(
            ({"id": p.id, "name": p.cst_base_name(),
              "characteristic": p.cst_characteristic or "",
              "qty": q or 0.0, "amount": a or 0.0}
             for p, q, a in products), key=lambda r: -r["amount"])[:6]

        sellers = Order._read_group(
            base + [("date_order", ">=", fields.Datetime.to_datetime(month_start))],
            groupby=["user_id"], aggregates=["amount_total:sum", "__count"])
        top_sellers = sorted(
            ({"id": u.id if u else 0, "name": u.name if u else "—", "amount": a or 0.0, "count": c or 0}
             for u, a, c in sellers), key=lambda r: -r["amount"])[:6]

        month, prev = between(month_start, today), between(prev_start, prev_end)
        return {
            "month": month, "prev_month": prev,
            "today": between(today, today),
            "period": between(since, today),
            "delta_pct": self._pct(month["amount"], prev["amount"]),
            "series": series,
            "by_company": by_company,
            "top_products": top_products,
            "top_sellers": top_sellers,
        }

    # -------------------------------------------------------------- expenses
    @api.model
    def _expenses(self, companies, since, today, month_start, prev_start, prev_end):
        Line = self.env["account.move.line"].sudo()
        base = [("parent_state", "=", "posted"), ("company_id", "in", companies.ids),
                ("account_id.account_type", "in", EXPENSE_TYPES)]

        def total(d1, d2):
            return Line._read_group(base + [("date", ">=", d1), ("date", "<=", d2)],
                                    aggregates=["balance:sum"])[0][0] or 0.0

        groups = defaultdict(float)
        for line in Line.search(base + [("date", ">=", month_start), ("date", "<=", today)]):
            group = line.account_id.group_id
            groups[group.name if group else (line.account_id.name or "Boshqa")] += line.balance or 0.0
        by_group = sorted(({"name": n, "amount": a} for n, a in groups.items() if a),
                          key=lambda r: -r["amount"])
        head, tail = by_group[:6], by_group[6:]
        if tail:
            head.append({"name": "Boshqa", "amount": sum(r["amount"] for r in tail)})

        daily = defaultdict(float)
        for date, amount in Line._read_group(
                base + [("date", ">=", since), ("date", "<=", today)],
                groupby=["date:day"], aggregates=["balance:sum"]):
            daily[fields.Date.to_date(date)] += amount or 0.0
        series, day = [], since
        while day <= today:
            series.append(round(daily.get(day, 0.0), 2))
            day += timedelta(days=1)

        month, prev = total(month_start, today), total(prev_start, prev_end)
        return {"month": month, "prev_month": prev, "delta_pct": self._pct(month, prev),
                "period": total(since, today), "by_group": head, "series": series}

    # ----------------------------------------------------------------- debts
    @api.model
    def _debts(self, companies, today):
        """Who owes whom, from the documents: a confirmed order is a debt from
        the day it is confirmed, invoiced or not; payments, kassa entries and
        invoices / bills typed without an order come from the journal. The
        invoices of an order are left out (the order already counts).
        Company currency, like the rest of the dashboard."""
        engine = self.env["cst.partner.statement"]
        Line = self.env["account.move.line"].sudo()
        base = [("parent_state", "=", "posted"), ("company_id", "in", companies.ids),
                ("move_id", "not in", engine._order_linked_moves(companies.ids))]
        recv = defaultdict(float)
        pay = defaultdict(float)
        for kind, target in (("asset_receivable", recv), ("liability_payable", pay)):
            for partner, amount in Line._read_group(
                    base + [("account_id.account_type", "=", kind)],
                    groupby=["partner_id"], aggregates=["balance:sum"]):
                target[partner.id] += amount or 0.0

        orders_by_partner = defaultdict(list)
        for order in self.env["sale.order"].sudo().search(
                [("state", "=", "sale"), ("company_id", "in", companies.ids)], order="date_order, id"):
            value = order.amount_total / (order.currency_rate or 1.0)
            partner = order.partner_id.commercial_partner_id
            recv[partner.id] += value
            orders_by_partner[partner.id].append((order, value))
        for order in self.env["purchase.order"].sudo().search(
                [("state", "in", ("purchase", "done")), ("company_id", "in", companies.ids)]):
            pay[order.partner_id.commercial_partner_id.id] -= order.amount_total / (order.currency_rate or 1.0)

        # aging: what a client still owes sits on their newest orders (the
        # money that came in paid the oldest ones first)
        buckets = [("0–30 kun", 0, 30), ("31–60", 31, 60), ("61–90", 61, 90), ("90+ kun", 91, 10 ** 6)]
        aging = {label: 0.0 for label, _a, _b in buckets}
        current = overdue = 0.0
        overdue_orders = []
        for pid, owed in recv.items():
            if owed <= 0.005:
                continue
            for order, value in reversed(orders_by_partner.get(pid, [])):
                if owed <= 0.005:
                    break
                part = min(value, owed)
                owed -= part
                due = fields.Datetime.context_timestamp(self, order.date_order).date() + \
                    timedelta(days=self._term_days(order.payment_term_id))
                late = (today - due).days
                if late <= 0:
                    current += part
                    continue
                overdue += part
                overdue_orders.append(order.id)
                for label, lo, hi in buckets:
                    if lo <= late <= hi:
                        aging[label] += part
                        break
            if owed > 0.005:  # debt with no order behind it (journal entries)
                current += owed

        Partner = self.env["res.partner"].sudo()
        debtors = sorted(
            ({"id": pid, "name": Partner.browse(pid).display_name, "amount": a}
             for pid, a in recv.items() if pid and a > 0.005),
            key=lambda r: -r["amount"])[:6]
        return {
            "receivable": sum(a for a in recv.values()),
            "payable": -sum(a for a in pay.values()),
            "overdue": overdue, "overdue_count": len(overdue_orders), "not_due": current,
            "overdue_order_ids": overdue_orders,
            "aging": [{"label": label, "amount": aging[label]} for label, _a, _b in buckets],
            "top_debtors": debtors,
        }

    @api.model
    def _term_days(self, term):
        """Days until the last instalment of a payment term (0 = due at once)."""
        if not term:
            return 0
        days = [getattr(line, "nb_days", 0) or 0 for line in term.line_ids]
        return max(days or [0])

    # ----------------------------------------------------------------- stock
    @api.model
    def _stock(self, companies, month_start):
        Move = self.env["stock.move"].sudo()
        base = [("state", "=", "done"), ("company_id", "in", companies.ids)]
        value_in = Move._read_group(base + [("is_in", "=", True)], aggregates=["value:sum"])[0][0] or 0.0
        value_out = Move._read_group(base + [("is_out", "=", True)], aggregates=["value:sum"])[0][0] or 0.0
        writeoffs = Move._read_group(
            base + [("location_dest_id.usage", "=", "inventory"), ("is_inventory", "=", False),
                    ("date", ">=", fields.Datetime.to_datetime(month_start))],
            aggregates=["value:sum", "__count"])[0]
        return {
            "value": value_in - value_out,
            "low_stock": self.env["stock.warehouse.orderpoint"].sudo().search_count(
                [("company_id", "in", companies.ids), ("qty_to_order", ">", 0)]),
            "writeoff_month_value": abs(writeoffs[0] or 0.0),
            "writeoff_month_count": writeoffs[1] or 0,
        }

    # ------------------------------------------------------------ production
    @api.model
    def _production(self, companies, month_start, prev_start, prev_end):
        MO = self.env["mrp.production"].sudo()
        base = [("company_id", "in", companies.ids)]

        def done(d1, d2):
            row = MO._read_group(
                base + [("state", "=", "done"),
                        ("date_finished", ">=", fields.Datetime.to_datetime(d1)),
                        ("date_finished", "<=", fields.Datetime.to_datetime(d2).replace(
                            hour=23, minute=59, second=59))],
                aggregates=["product_qty:sum", "__count"])[0]
            return {"qty": row[0] or 0.0, "count": row[1] or 0}

        return {
            "month": done(month_start, fields.Date.context_today(self)),
            "prev_month": done(prev_start, prev_end),
            "in_progress": MO.search_count(base + [("state", "in", ("confirmed", "progress", "to_close"))]),
        }

    # --------------------------------------------------------------- payroll
    @api.model
    def _payroll(self, companies, month_start):
        if "cst.payroll.line" not in self.env:
            return {"owed": 0.0, "month_accrued": 0.0}
        Line = self.env["cst.payroll.line"].sudo()
        base = [("company_id", "in", companies.ids), ("state", "in", ("confirmed", "posted")),
                ("kind", "in", ("accrual", "deduction"))]
        owed = sum(Line.search(base).mapped("signed_amount"))
        accrued = Line._read_group(
            base + [("kind", "=", "accrual"), ("date", ">=", month_start)],
            aggregates=["amount:sum"])[0][0] or 0.0
        return {"owed": owed, "month_accrued": accrued}

    @api.model
    def _pct(self, now, before):
        if not before:
            return None
        return round((now - before) / abs(before) * 100.0, 1)
