from collections import defaultdict

from odoo import api, fields, models

INCOME_TYPES = ("income", "income_other")
EXPENSE_TYPES = ("expense", "expense_depreciation", "expense_direct_cost")


class KeramaDashboard(models.AbstractModel):
    """Data provider for the Kerama dynamic dashboards.

    Every public ``get_*`` method receives a plain ``filters`` dict from the
    OWL client and returns JSON-serialisable data. Monetary figures are kept
    split by currency name (e.g. ``{"UZS": 1000.0, "USD": 12.5}``) so the UI
    can show the UZS / USD split the business works with.
    """

    _name = "kerama.dashboard"
    _description = "Kerama Dynamic Dashboard data provider"

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------
    @api.model
    def _company_ids(self, filters):
        return filters.get("company_ids") or self.env.companies.ids

    @api.model
    def _company_ccy(self, company_ids):
        """Currency name of the first selected company (sudo-safe)."""
        company = self.env["res.company"].sudo().browse(company_ids[:1])
        return (company.currency_id.name if company else None) or "UZS"

    @api.model
    def _date_bounds(self, filters):
        """Return (date_from, date_to) datetime strings or (None, None)."""
        df = filters.get("date_from")
        dt = filters.get("date_to")
        return (
            df + " 00:00:00" if df else None,
            dt + " 23:59:59" if dt else None,
        )

    @api.model
    def _sale_domain(self, filters, confirmed_only=True, with_currency=True):
        domain = [("company_id", "in", self._company_ids(filters))]
        if confirmed_only:
            domain.append(("state", "=", "sale"))
        else:
            domain.append(("state", "!=", "cancel"))
        df, dt = self._date_bounds(filters)
        if df:
            domain.append(("date_order", ">=", df))
        if dt:
            domain.append(("date_order", "<=", dt))
        if filters.get("salesperson_id"):
            domain.append(("user_id", "=", filters["salesperson_id"]))
        if filters.get("partner_search"):
            domain.append(("partner_id.name", "ilike", filters["partner_search"]))
        if filters.get("so_search"):
            domain.append(("name", "ilike", filters["so_search"]))
        if with_currency and filters.get("currency") in ("UZS", "USD"):
            domain.append(("currency_id.name", "=", filters["currency"]))
        return domain

    # ------------------------------------------------------------------
    # Filter options (dropdowns populated once on load)
    # ------------------------------------------------------------------
    @api.model
    def get_filter_options(self):
        # Only salespeople that actually have orders -> keeps the list short.
        sp_groups = self.env["sale.order"]._read_group(
            [("user_id", "!=", False)], ["user_id"], []
        )
        salespersons = [
            {"id": user.id, "name": user.name} for (user,) in sp_groups
        ]
        # All companies in the system (sudo) — the dashboard is allowed to
        # report on companies the current user has no direct access to. The
        # data methods run sudo so this never raises a company AccessError.
        companies = [
            {"id": c.id, "name": c.name}
            for c in self.env["res.company"].sudo().search([], order="name")
        ]
        # Only payment journals (bank / cash) are useful filters here:
        # Bank, Naqt, Naqt/UZS, Naqt/USD, Click/Payme...
        journals = self.env["account.journal"].search(
            [("company_id", "in", self.env.companies.ids), ("type", "in", ["bank", "cash"])]
        )
        journal_opts = [
            {"id": j.id, "name": f"{j.name} ({j.company_id.name})"} for j in journals
        ]
        warehouses = self.env["stock.warehouse"].search(
            [("company_id", "in", self.env.companies.ids)]
        )
        warehouse_opts = [
            {"id": w.id, "name": f"{w.name} ({w.company_id.name})"} for w in warehouses
        ]
        return {
            "salespersons": sorted(salespersons, key=lambda s: s["name"]),
            "companies": companies,
            "journals": journal_opts,
            "warehouses": warehouse_opts,
            # Default scope for the Stock list: the user's active company.
            "current_company_id": self.env.company.id,
        }

    # ------------------------------------------------------------------
    # SALES dashboard
    # ------------------------------------------------------------------
    @api.model
    def get_sales_data(self, filters=None):
        filters = filters or {}
        SO = self.env["sale.order"]
        domain = self._sale_domain(filters)
        orders = SO.search(domain)

        sales_by_ccy = defaultdict(float)
        debt_by_ccy = defaultdict(float)
        count_by_ccy = defaultdict(int)
        for o in orders:
            name = o.currency_id.name
            sales_by_ccy[name] += o.amount_total
            debt_by_ccy[name] += o.payment_amount_due
            count_by_ccy[name] += 1

        # m² sold: total ordered quantity on square-meter lines.
        sqm_uom = self.env.ref("uom.product_uom_square_meter", raise_if_not_found=False)
        sqm_lines = orders.order_line.filtered(lambda l: l.product_uom_id == sqm_uom)
        m2_sold = sum(sqm_lines.mapped("product_uom_qty"))

        # Cash in: confirmed inbound customer payments in the period.
        cash_by_ccy = defaultdict(float)
        pay_domain = [
            ("company_id", "in", self._company_ids(filters)),
            ("payment_type", "=", "inbound"),
            ("partner_type", "=", "customer"),
            ("state", "=", "paid"),
        ]
        df, dt = self._date_bounds(filters)
        if filters.get("date_from"):
            pay_domain.append(("date", ">=", filters["date_from"]))
        if filters.get("date_to"):
            pay_domain.append(("date", "<=", filters["date_to"]))
        if filters.get("currency") in ("UZS", "USD"):
            pay_domain.append(("currency_id.name", "=", filters["currency"]))
        for pay in self.env["account.payment"].search(pay_domain):
            cash_by_ccy[pay.currency_id.name] += pay.amount

        avg_by_ccy = {
            c: (sales_by_ccy[c] / count_by_ccy[c]) if count_by_ccy[c] else 0.0
            for c in sales_by_ccy
        }

        return {
            "kpis": {
                "total_sales": dict(sales_by_ccy),
                "order_count": len(orders),
                "total_debt": dict(debt_by_ccy),
                "cash_in": dict(cash_by_ccy),
                "m2_sold": round(m2_sold, 2),
                "avg_order": avg_by_ccy,
            },
            "charts": {
                "sales_over_time": self._sales_over_time(domain),
                "top_customers": self._top_customers(domain),
                "top_products": self._top_products(orders.ids),
                "by_salesperson": self._by_salesperson(domain),
                "by_currency": [
                    {"label": c, "value": v} for c, v in sales_by_ccy.items()
                ],
                "by_company": self._by_company(domain),
                "status_funnel": self._status_funnel(filters),
            },
        }

    @api.model
    def _sales_over_time(self, domain):
        groups = self.env["sale.order"]._read_group(
            domain, ["date_order:month", "currency_id"], ["amount_total:sum"]
        )
        months = sorted({m for (m, _ccy, _t) in groups})
        idx = {m: i for i, m in enumerate(months)}
        series = defaultdict(lambda: [0.0] * len(months))
        for month, ccy, total in groups:
            series[ccy.name][idx[month]] += total
        return {
            "labels": [m.strftime("%b %Y") for m in months],
            "series": [{"currency": c, "data": d} for c, d in series.items()],
        }

    @api.model
    def _top_customers(self, domain, limit=10):
        groups = self.env["sale.order"]._read_group(
            domain, ["partner_id"], ["amount_total:sum"],
            order="amount_total:sum desc", limit=limit,
        )
        return [
            {"label": partner.display_name, "value": total}
            for (partner, total) in groups
            if partner
        ]

    @api.model
    def _top_products(self, order_ids, limit=10):
        if not order_ids:
            return []
        groups = self.env["sale.order.line"]._read_group(
            [("order_id", "in", order_ids), ("display_type", "=", False)],
            ["product_id"], ["price_subtotal:sum"],
            order="price_subtotal:sum desc", limit=limit,
        )
        return [
            {"label": product.display_name, "value": total}
            for (product, total) in groups
            if product
        ]

    @api.model
    def _by_salesperson(self, domain):
        groups = self.env["sale.order"]._read_group(
            domain, ["user_id"], ["amount_total:sum"],
            order="amount_total:sum desc",
        )
        return [
            {"label": user.name if user else "—", "value": total}
            for (user, total) in groups
        ]

    @api.model
    def _by_company(self, domain):
        groups = self.env["sale.order"]._read_group(
            domain, ["company_id", "currency_id"], ["amount_total:sum"]
        )
        per_company = {}
        for company, ccy, total in groups:
            per_company.setdefault(company.name, {})
            per_company[company.name][ccy.name] = (
                per_company[company.name].get(ccy.name, 0.0) + total
            )
        labels = list(per_company.keys())
        currencies = sorted({c for vals in per_company.values() for c in vals})
        return {
            "labels": labels,
            "series": [
                {"currency": cur, "data": [per_company[l].get(cur, 0.0) for l in labels]}
                for cur in currencies
            ],
        }

    @api.model
    def _status_funnel(self, filters):
        # Counts across all live states, ignoring the state restriction.
        domain = self._sale_domain(filters, confirmed_only=False)
        groups = self.env["sale.order"]._read_group(domain, ["state"], ["__count"])
        labels = {"draft": "Quotation", "sent": "Sent", "sale": "Confirmed"}
        order = ["draft", "sent", "sale"]
        counts = {state: cnt for (state, cnt) in groups}
        return [
            {"label": labels.get(s, s), "value": counts.get(s, 0)} for s in order
        ]

    # ------------------------------------------------------------------
    # ACCOUNTING dashboard
    # ------------------------------------------------------------------
    @api.model
    def _pos_journal_ids(self):
        """POS journals to exclude from accounting figures.

        point_of_sale may be uninstalled here; fall back to the leftover
        'Point of Sale' journal (code POSS) created by the chart template.
        """
        if "pos.config" in self.env:
            ids = self.env["pos.config"].sudo().search([]).journal_id.ids
            if ids:
                return ids
        return self.env["account.journal"].search([("code", "=", "POSS")]).ids

    @api.model
    def _move_domain(self, filters, move_types):
        # Note: the journal_id filter is intentionally NOT applied here. Only
        # payment journals are selectable, and invoices/bills never live in
        # those; applying it would zero out the document figures.
        domain = [
            ("move_type", "in", move_types),
            ("state", "=", "posted"),
            ("company_id", "in", self._company_ids(filters)),
        ]
        if filters.get("date_from"):
            domain.append(("invoice_date", ">=", filters["date_from"]))
        if filters.get("date_to"):
            domain.append(("invoice_date", "<=", filters["date_to"]))
        if filters.get("partner_search"):
            domain.append(("partner_id.name", "ilike", filters["partner_search"]))
        if filters.get("salesperson_id"):
            domain.append(("invoice_user_id", "=", filters["salesperson_id"]))
        if filters.get("so_search"):
            domain.append(("invoice_origin", "ilike", filters["so_search"]))
        if filters.get("currency") in ("UZS", "USD"):
            domain.append(("currency_id.name", "=", filters["currency"]))
        return domain

    @api.model
    def _aml_expense_domain(self, filters, exclude_purchase=True):
        domain = [
            ("parent_state", "=", "posted"),
            ("company_id", "in", self._company_ids(filters)),
            ("account_id.account_type", "in", list(EXPENSE_TYPES)),
        ]
        if exclude_purchase:
            domain.append(("journal_id.type", "!=", "purchase"))
        pos_ids = self._pos_journal_ids()
        if pos_ids:
            domain.append(("journal_id", "not in", pos_ids))
        if filters.get("date_from"):
            domain.append(("date", ">=", filters["date_from"]))
        if filters.get("date_to"):
            domain.append(("date", "<=", filters["date_to"]))
        return domain

    @api.model
    def _order_linked_moves(self):
        """Invoices / bills / credit notes made from a sales or purchase order:
        the order itself is the document that counts, these would double it."""
        self.env.cr.execute("""
            SELECT DISTINCT l.move_id
              FROM account_move_line l
              JOIN account_move m ON m.id = l.move_id
             WHERE m.move_type IN ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')
               AND (l.purchase_line_id IS NOT NULL
                    OR EXISTS (SELECT 1 FROM sale_order_line_invoice_rel r
                                WHERE r.invoice_line_id = l.id))
        """)
        return [r[0] for r in self.env.cr.fetchall()]

    @api.model
    def _purchase_domain(self, filters):
        domain = [("company_id", "in", self._company_ids(filters)),
                  ("state", "in", ("purchase", "done"))]
        df, dt = self._date_bounds(filters)
        if df:
            domain.append(("date_order", ">=", df))
        if dt:
            domain.append(("date_order", "<=", dt))
        if filters.get("partner_search"):
            domain.append(("partner_id.name", "ilike", filters["partner_search"]))
        if filters.get("currency") in ("UZS", "USD"):
            domain.append(("currency_id.name", "=", filters["currency"]))
        return domain

    @api.model
    def _document_totals(self, filters, side):
        """Sales (or purchases) per currency from the documents: confirmed
        orders, invoiced or not, plus invoices / bills typed without an order."""
        Order = self.env["sale.order" if side == "sale" else "purchase.order"]
        domain = self._sale_domain(filters) if side == "sale" else self._purchase_domain(filters)
        by_ccy = defaultdict(float)
        count = 0
        for ccy, total, cnt in Order._read_group(domain, ["currency_id"], ["amount_total:sum", "__count"]):
            by_ccy[ccy.name] += total or 0.0
            count += cnt
        types = ["out_invoice", "out_refund"] if side == "sale" else ["in_invoice", "in_refund"]
        loose, loose_count = self._invoice_totals(
            self._move_domain(filters, types) + [("id", "not in", self._order_linked_moves())])
        for name, amount in loose.items():
            by_ccy[name] += amount
        return dict(by_ccy), count + loose_count

    @api.model
    def _invoice_totals(self, domain):
        """Net amount per currency (refunds subtracted) and document count."""
        groups = self.env["account.move"]._read_group(
            domain, ["currency_id", "move_type"], ["amount_total:sum", "__count"]
        )
        by_ccy = defaultdict(float)
        count = 0
        for ccy, move_type, total, cnt in groups:
            sign = -1.0 if move_type in ("out_refund", "in_refund") else 1.0
            by_ccy[ccy.name] += sign * total
            count += cnt
        return dict(by_ccy), count

    @api.model
    def get_accounting_data(self, filters=None):
        filters = filters or {}
        AM = self.env["account.move"]
        AML = self.env["account.move.line"]

        inv_amount, inv_count = self._document_totals(filters, "sale")
        bill_amount, bill_count = self._document_totals(filters, "purchase")

        # Expenses (company currency), excluding vendor-bill journals.
        exp_groups = AML._read_group(
            self._aml_expense_domain(filters), [], ["balance:sum"]
        )
        expenses = exp_groups[0][0] or 0.0 if exp_groups else 0.0
        company_ccy = self.env.companies[:1].currency_id.name or "UZS"

        # P&L (full accounting view, company currency).
        pl = self._profit_and_loss(filters)

        # Payments: journal split + cash in/out, all in company currency.
        payments = self._payment_breakdown(filters)

        return {
            "company_currency": company_ccy,
            "kpis": {
                "inv_count": inv_count,
                "inv_amount": inv_amount,
                "bill_count": bill_count,
                "bill_amount": bill_amount,
                "expenses": {company_ccy: expenses},
                "net_cashflow": payments["net_by_ccy"],
                "pl_net": {company_ccy: pl["net"]},
            },
            "charts": {
                "flow_over_time": self._flow_over_time(filters),
                "payments_by_journal": payments["by_journal"],
                "profit_and_loss": [
                    {"label": "Revenue", "value": pl["revenue"]},
                    {"label": "Expenses", "value": pl["expenses"]},
                    {"label": "Net", "value": pl["net"]},
                ],
                "cash_in_out": [
                    {"label": "Cash In", "value": payments["cash_in"]},
                    {"label": "Cash Out", "value": payments["cash_out"]},
                ],
                "top_expenses": self._top_expense_accounts(filters),
            },
        }

    @api.model
    def _profit_and_loss(self, filters):
        AML = self.env["account.move.line"]
        base = [
            ("parent_state", "=", "posted"),
            ("company_id", "in", self._company_ids(filters)),
        ]
        pos_ids = self._pos_journal_ids()
        if pos_ids:
            base.append(("journal_id", "not in", pos_ids))
        if filters.get("date_from"):
            base.append(("date", ">=", filters["date_from"]))
        if filters.get("date_to"):
            base.append(("date", "<=", filters["date_to"]))
        inc = AML._read_group(
            base + [("account_id.account_type", "in", list(INCOME_TYPES))],
            [], ["balance:sum"],
        )
        exp = AML._read_group(
            base + [("account_id.account_type", "in", list(EXPENSE_TYPES))],
            [], ["balance:sum"],
        )
        revenue = -(inc[0][0] or 0.0) if inc else 0.0
        expenses = exp[0][0] or 0.0 if exp else 0.0
        return {
            "revenue": revenue,
            "expenses": expenses,
            "net": revenue - expenses,
        }

    @api.model
    def _payment_breakdown(self, filters):
        domain = [
            ("company_id", "in", self._company_ids(filters)),
            ("state", "=", "paid"),
        ]
        if filters.get("date_from"):
            domain.append(("date", ">=", filters["date_from"]))
        if filters.get("date_to"):
            domain.append(("date", "<=", filters["date_to"]))
        if filters.get("journal_id"):
            domain.append(("journal_id", "=", filters["journal_id"]))

        by_journal = defaultdict(float)
        cash_in = cash_out = 0.0
        net_by_ccy = defaultdict(float)
        for pay in self.env["account.payment"].search(domain):
            company = pay.company_id
            comp_amount = pay.currency_id._convert(
                pay.amount, company.currency_id, company,
                pay.date or fields.Date.context_today(self),
            )
            by_journal[pay.journal_id.name] += comp_amount
            if pay.payment_type == "inbound":
                cash_in += comp_amount
                net_by_ccy[pay.currency_id.name] += pay.amount
            else:
                cash_out += comp_amount
                net_by_ccy[pay.currency_id.name] -= pay.amount
        return {
            "by_journal": [
                {"label": name, "value": val} for name, val in by_journal.items()
            ],
            "cash_in": cash_in,
            "cash_out": cash_out,
            "net_by_ccy": dict(net_by_ccy),
        }

    @api.model
    def _flow_over_time(self, filters):
        AM = self.env["account.move"]
        AML = self.env["account.move.line"]

        linked = self._order_linked_moves()

        def monthly_moves(move_types, sign):
            # invoices / bills without an order; the orders count themselves
            domain = self._move_domain(filters, move_types) + [("id", "not in", linked)]
            groups = AM._read_group(
                domain, ["invoice_date:month"], ["amount_total_signed:sum"]
            )
            return {m: sign * (v or 0.0) for (m, v) in groups if m}

        def monthly_orders(model, domain):
            # company currency, like amount_total_signed above
            out = defaultdict(float)
            for order in self.env[model].search(domain):
                month = fields.Date.start_of(order.date_order.date(), "month")
                out[month] += order.amount_total / (order.currency_rate or 1.0)
            return out

        sales = monthly_moves(["out_invoice", "out_refund"], 1.0)
        for m, v in monthly_orders("sale.order", self._sale_domain(filters, with_currency=False)).items():
            sales[m] = sales.get(m, 0.0) + v
        purchases = monthly_moves(["in_invoice", "in_refund"], -1.0)
        for m, v in monthly_orders("purchase.order", self._purchase_domain(filters)).items():
            purchases[m] = purchases.get(m, 0.0) + v
        exp_groups = AML._read_group(
            self._aml_expense_domain(filters), ["date:month"], ["balance:sum"]
        )
        expenses = {m: (v or 0.0) for (m, v) in exp_groups if m}

        series = {"Sales": sales, "Purchases": purchases, "Expenses": expenses}
        months = sorted({m for s in series.values() for m in s})
        return {
            "labels": [m.strftime("%b %Y") for m in months],
            "datasets": [
                {"label": name, "data": [s.get(m, 0.0) for m in months]}
                for name, s in series.items()
            ],
        }

    @api.model
    def _top_expense_accounts(self, filters, limit=8):
        groups = self.env["account.move.line"]._read_group(
            self._aml_expense_domain(filters),
            ["account_id"], ["balance:sum"],
            order="balance:sum desc", limit=limit,
        )
        return [
            {"label": account.display_name, "value": total}
            for (account, total) in groups
            if account and total
        ]

    # ------------------------------------------------------------------
    # DEBTS dashboard (reuses sale.order.payment_amount_due)
    # ------------------------------------------------------------------
    @api.model
    def get_debts_data(self, filters=None):
        filters = filters or {}
        today = fields.Date.context_today(self)

        def comp_due(order):
            company = order.company_id
            return order.currency_id._convert(
                order.payment_amount_due, company.currency_id, company, today
            )

        # Base set: confirmed orders matching company/currency/client/date,
        # keeping only those that still owe money. so_id is applied later so
        # the dropdown always lists every debt order.
        base = self.env["sale.order"].search(self._sale_domain(filters))
        debt_orders = base.filtered(
            lambda o: o.currency_id.compare_amounts(o.payment_amount_due, 0) > 0
        )
        debt_orders = debt_orders.sorted(key=comp_due, reverse=True)

        dropdown = [
            {
                "id": o.id,
                "name": o.name,
                "label": f"{o.name} · {o.partner_id.name or ''} · "
                         f"{o.payment_amount_due:,.2f} {o.currency_id.name}",
            }
            for o in debt_orders
        ]

        orders = debt_orders
        if filters.get("so_id"):
            orders = orders.filtered(lambda o: o.id == filters["so_id"])

        # KPIs (debt split by order currency)
        debt_by_ccy = defaultdict(float)
        count_by_ccy = defaultdict(int)
        for o in orders:
            debt_by_ccy[o.currency_id.name] += o.payment_amount_due
            count_by_ccy[o.currency_id.name] += 1
        avg_by_ccy = {
            c: debt_by_ccy[c] / count_by_ccy[c] for c in debt_by_ccy if count_by_ccy[c]
        }

        # Charts (company currency for cross-currency comparison)
        debtor_comp = defaultdict(float)
        ccy_comp = defaultdict(float)
        aging = {"0–30": 0.0, "31–60": 0.0, "61–90": 0.0, "90+": 0.0}
        month_comp = defaultdict(float)
        for o in orders:
            cd = comp_due(o)
            debtor_comp[o.partner_id] += cd
            ccy_comp[o.currency_id.name] += cd
            order_day = o.date_order.date() if o.date_order else today
            days = (today - order_day).days
            bucket = (
                "0–30" if days <= 30
                else "31–60" if days <= 60
                else "61–90" if days <= 90
                else "90+"
            )
            aging[bucket] += cd
            if o.date_order:
                month_comp[o.date_order.strftime("%Y-%m")] += cd

        top_debtors = sorted(debtor_comp.items(), key=lambda kv: kv[1], reverse=True)[:10]
        months = sorted(month_comp)

        table = [
            {
                "so": o.name,
                "client": o.partner_id.display_name,
                "date": o.date_order.strftime("%Y-%m-%d") if o.date_order else "",
                "due": o.payment_amount_due,
                "currency": o.currency_id.name,
            }
            for o in orders.sorted(key=comp_due, reverse=True)[:50]
        ]

        return {
            "debt_orders": dropdown,
            "kpis": {
                "debt_count": len(orders),
                "debt_amount": dict(debt_by_ccy),
                "client_count": len(orders.partner_id),
                "avg_debt": avg_by_ccy,
            },
            "charts": {
                "top_debtors": [
                    {"label": p.display_name, "value": v} for p, v in top_debtors
                ],
                "debt_by_currency": [
                    {"label": c, "value": v} for c, v in ccy_comp.items()
                ],
                "aging": [{"label": k, "value": aging[k]} for k in aging],
                "over_time": {
                    "labels": [
                        fields.Date.to_date(m + "-01").strftime("%b %Y") for m in months
                    ],
                    "data": [month_comp[m] for m in months],
                },
            },
            "table": table,
        }

    # ------------------------------------------------------------------
    # INVENTORY dashboard (Odoo stock dashboard, restyled)
    # ------------------------------------------------------------------
    @api.model
    def _storable_domain(self):
        Product = self.env["product.product"]
        return (
            [("is_storable", "=", True)]
            if "is_storable" in Product._fields
            else [("type", "=", "consu")]
        )

    @api.model
    def _qty_context(self, filters, company_ids):
        # NB: in Odoo 19 the `warehouse` context key does not scope
        # qty_available; the warehouse stock `location` does.
        if filters.get("warehouse_id"):
            wh = self.env["stock.warehouse"].browse(filters["warehouse_id"])
            return {"location": wh.lot_stock_id.id}
        return {"allowed_company_ids": company_ids}

    @api.model
    def get_inventory_data(self, filters=None):
        filters = filters or {}
        # Run sudo: the company filter may include companies the user has no
        # access to, and allowed_company_ids would otherwise raise AccessError.
        self = self.sudo()
        company_ids = self._company_ids(filters)
        company_ccy = self._company_ccy(company_ids)
        Product = self.env["product.product"]
        storable = self._storable_domain()

        # On-hand quantities, scoped to the chosen warehouse (or all companies).
        P = Product.with_context(**self._qty_context(filters, company_ids))
        prod_qty = {}
        units_on_hand = m2_on_hand = 0.0
        m2_by_cat = defaultdict(float)
        sqm_uom = self.env.ref("uom.product_uom_square_meter", raise_if_not_found=False)
        for p in P.search(storable):
            qty = p.qty_available
            if qty <= 0:
                continue
            prod_qty[p] = qty
            units_on_hand += qty
            if p.uom_id == sqm_uom:
                m2_on_hand += qty
                m2_by_cat[p.categ_id.name or "—"] += qty

        # Valuation per company (total_value is company-level, not warehouse).
        total_value = 0.0
        for cid in company_ids:
            total_value += sum(
                Product.with_company(cid).search(storable).mapped("total_value")
            )

        top_qty = sorted(prod_qty.items(), key=lambda kv: kv[1], reverse=True)[:10]
        low_stock = self._low_stock(filters, company_ids)
        operations = self._stock_operations(company_ids, filters.get("warehouse_id"))

        return {
            "company_currency": company_ccy,
            "kpis": {
                "stock_value": {company_ccy: round(total_value, 2)},
                "products_in_stock": len(prod_qty),
                "units_on_hand": round(units_on_hand, 2),
                "m2_on_hand": round(m2_on_hand, 2),
                "low_stock_count": len(low_stock),
            },
            "operations": operations,
            "charts": {
                "moves_over_time": self._moves_over_time(filters, company_ids),
                "m2_by_category": [
                    {"label": c, "value": round(v, 2)}
                    for c, v in sorted(m2_by_cat.items(), key=lambda kv: -kv[1])
                ],
                "stock_by_warehouse": self._stock_by_warehouse(company_ids, storable),
                "top_products_qty": [
                    {"label": p.display_name, "value": q} for p, q in top_qty
                ],
            },
            "low_stock": low_stock,
        }

    @api.model
    def _low_stock(self, filters, company_ids):
        Product = self.env["product.product"].with_context(
            **self._qty_context(filters, company_ids)
        )
        # Reorder minimums per product (max across rules).
        min_by_prod = {}
        for op in self.env["stock.warehouse.orderpoint"].search(
            [("company_id", "in", company_ids)]
        ):
            min_by_prod[op.product_id.id] = max(
                min_by_prod.get(op.product_id.id, 0.0), op.product_min_qty
            )
        rows = []
        for p in Product.search(self._storable_domain()):
            qty = p.qty_available
            minq = min_by_prod.get(p.id, 0.0)
            if qty <= 0 and p.sale_ok:
                status = "out"
            elif minq and qty <= minq:
                status = "low"
            else:
                continue
            rows.append({
                "product": p.display_name,
                "on_hand": qty,
                "min": minq,
                "status": status,
            })
        rows.sort(key=lambda r: (r["status"] != "out", r["on_hand"]))
        return rows[:50]

    @api.model
    def _stock_by_warehouse(self, company_ids, storable):
        Product = self.env["product.product"]
        result = []
        for wh in self.env["stock.warehouse"].search([("company_id", "in", company_ids)]):
            total = sum(
                Product.with_context(location=wh.lot_stock_id.id)
                .search(storable).mapped("qty_available")
            )
            if total:
                result.append({"label": wh.name, "value": round(total, 2)})
        return sorted(result, key=lambda r: -r["value"])

    @api.model
    def _moves_over_time(self, filters, company_ids):
        Move = self.env["stock.move"]
        base = [("state", "=", "done"), ("company_id", "in", company_ids)]
        df, dt = self._date_bounds(filters)
        if df:
            base.append(("date", ">=", df))
        if dt:
            base.append(("date", "<=", dt))
        if filters.get("warehouse_id"):
            base.append(("picking_type_id.warehouse_id", "=", filters["warehouse_id"]))

        def monthly(code):
            groups = Move._read_group(
                base + [("picking_type_id.code", "=", code)],
                ["date:month"], ["product_uom_qty:sum"],
            )
            return {m: (v or 0.0) for (m, v) in groups if m}

        incoming, outgoing = monthly("incoming"), monthly("outgoing")
        months = sorted(set(incoming) | set(outgoing))
        return {
            "labels": [m.strftime("%b %Y") for m in months],
            "datasets": [
                {"label": "In", "data": [incoming.get(m, 0.0) for m in months]},
                {"label": "Out", "data": [outgoing.get(m, 0.0) for m in months]},
            ],
        }

    @api.model
    def _stock_operations(self, company_ids, warehouse_id=None):
        Picking = self.env["stock.picking"]
        now = fields.Datetime.now()
        open_states = ["assigned", "confirmed", "waiting"]
        operations = []
        type_domain = [
            ("company_id", "in", company_ids),
            ("code", "in", ["incoming", "outgoing", "internal"]),
        ]
        if warehouse_id:
            type_domain.append(("warehouse_id", "=", warehouse_id))
        types = self.env["stock.picking.type"].search(type_domain)
        for pt in types:
            # Skip POS operation types: the shop sells via sale orders only,
            # and point_of_sale is uninstalled (these are leftover types).
            if "pos" in (pt.name or "").lower():
                continue
            base = [("picking_type_id", "=", pt.id)]
            total = Picking.search_count(base)
            if not total:
                continue
            todo = Picking.search_count(base + [("state", "in", open_states)])
            late = Picking.search_count(
                base + [("state", "in", open_states), ("scheduled_date", "<", now)]
            )
            done = Picking.search_count(base + [("state", "=", "done")])
            operations.append({
                "id": pt.id,
                "name": pt.name,
                "company": pt.company_id.name,
                "code": pt.code,
                "todo": todo,
                "late": late,
                "done": done,
            })
        return operations

    # ------------------------------------------------------------------
    # STOCK list (per-product on-hand browse, company-scoped)
    # ------------------------------------------------------------------
    STOCK_ROW_LIMIT = 500

    @api.model
    def get_stock_data(self, filters=None):
        """Per-product on-hand stock table for the chosen company/warehouse.

        One row per product: on-hand / reserved / available quantity, UoM,
        stock category and valuation. Unlike the Inventory dashboard tab this
        defaults to the user's *active* company (the OWL client seeds
        ``company_ids`` from ``current_company_id``) rather than every company.
        """
        filters = filters or {}
        # Run sudo so companies outside the user's access can still be queried.
        self = self.sudo()
        company_ids = self._company_ids(filters)
        company_ccy = self._company_ccy(company_ids)
        Product = self.env["product.product"]

        domain = self._storable_domain()
        search = (filters.get("product_search") or "").strip()
        if search:
            domain = ["&"] + domain + [
                "|",
                ("name", "ilike", search),
                ("default_code", "ilike", search),
            ]

        # Quantities, scoped to the chosen warehouse (or all selected companies).
        P = Product.with_context(**self._qty_context(filters, company_ids))
        products = P.search(domain)

        # Valuation is company-level (non-stored, per-company) -> sum across the
        # selected companies, browsing in company context for the right cost.
        value_by_product = defaultdict(float)
        for cid in company_ids:
            for p in Product.with_company(cid).browse(products.ids):
                value_by_product[p.id] += p.total_value

        rows = []
        total_value = total_on_hand = total_reserved = total_m2 = 0.0
        sqm_uom = self.env.ref("uom.product_uom_square_meter", raise_if_not_found=False)
        for p in products:
            on_hand = p.qty_available
            free = p.free_qty
            reserved = on_hand - free
            # Skip products with no presence at all (nothing on hand/reserved).
            if not on_hand and not reserved:
                continue
            value = value_by_product.get(p.id, 0.0)
            total_on_hand += on_hand
            total_reserved += reserved
            total_value += value
            if p.uom_id == sqm_uom:
                total_m2 += on_hand
            rows.append({
                "id": p.id,
                "product": p.display_name,
                "code": p.default_code or "",
                "category": p.categ_id.name or "—",
                "uom": p.uom_id.name,
                "on_hand": round(on_hand, 2),
                "reserved": round(reserved, 2),
                "available": round(free, 2),
                "value": round(value, 2),
                "is_m2": p.uom_id == sqm_uom,
            })

        rows.sort(key=lambda r: r["value"], reverse=True)
        total_rows = len(rows)
        rows = rows[: self.STOCK_ROW_LIMIT]

        return {
            "company_currency": company_ccy,
            "kpis": {
                "product_count": total_rows,
                "stock_value": {company_ccy: round(total_value, 2)},
                "units_on_hand": round(total_on_hand, 2),
                "m2_on_hand": round(total_m2, 2),
            },
            "rows": rows,
            "row_limit": self.STOCK_ROW_LIMIT,
            "shown": len(rows),
            "total": total_rows,
        }
