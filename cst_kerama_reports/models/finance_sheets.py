"""«Foyda va zarar» and «Balans» in the shape of the company's own Excel sheets.

Most of the business lives in the operational documents rather than in the
ledger (orders, kassa operations, payroll lines, stock valuation), so each row
of the two sheets reads the document that owns the figure, and every document
belongs to exactly one row:

Foyda va zarar
 1  goods delivered to clients at the order price (returns = expense side)
 2  stock value of those deliveries minus the value of the returns
 3  write-offs (scraps and moves to an inventory-loss location, fuel excepted;
   a 2-sort regrade counts with the value of its twin, i.e. the loss only)
 4  kassa expense operations (by the modda's «Foyda/zarar qatori»)
 5  payroll accruals minus penalties
 6  employer payroll taxes + kassa moddas marked as taxes
 7  posted depreciation entries
 8  bills of «Kommunal xizmatlar» suppliers + kassa moddas marked utilities
 9  services: sold on orders (income), bought on orders or stand-alone bills
10  fuel issued from stock (fuel logs and fuel scraps)
11  inventory counts — surplus / shortage (the Excel stock loads excepted)
12  other kassa income
13  kassa count differences + kassa moddas marked corrections
14  expense lines of bank journals + kassa moddas marked bank
15  kassa moddas marked credit interest
16  exchange gain / loss accounts

Balans: each row has an opening, a turnover and a closing; a balance above zero
is *haqqimiz* (asset), below zero *qarzimiz*. Debit = Kirim, credit = Chiqim.
Capital (row 14) opens at assets − liabilities and moves by the period's
profit plus the capital corrections (opening loads of stock and balances);
whatever still does not tie is shown in row 15 so the columns always balance.
"""
import re
from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

PL_LINES = [
    ("kassa", "4. Kassadan xarajatlar"),
    ("tax", "6. Hisoblangan soliqlar"),
    ("utility", "8. Kommunal xizmatlar"),
    ("service", "9. Xizmatlar sotib olish va sotish"),
    ("other_income", "12. Qo'shimcha daromadlar"),
    ("correction", "13. Hisob-kitobni korrektirovka qilish"),
    ("bank", "14. Bank xarajatlari"),
    ("interest", "15. Kredit foizlari"),
    ("salary", "Balans: ish haqi to'lovi"),
    ("tax_payment", "Balans: soliq to'lovi"),
    ("loan", "Balans: kredit olish / qaytarish"),
    ("organization", "Balans: tashkilotlar"),
    ("founder", "Balans: ta'sischilar"),
    ("opening", "Balans: boshlang'ich qoldiq (kapital)"),
]

PL_ROWS = [
    ("sales", "Mahsulot sotishdan"),
    ("cogs", "Mahsulot tannarxi"),
    ("writeoff", "Hisobdan chiqarish"),
    ("kassa", "Kassadan xarajatlar"),
    ("salary", "Hisoblangan ish haqi"),
    ("tax", "Hisoblangan soliqlar"),
    ("depreciation", "AV eskirishi"),
    ("utility", "Hisoblangan kommunal xizmatlar"),
    ("service", "Xizmatlar sotib olish va sotish"),
    ("fuel", "Sarflangan yoqilg'i summasi"),
    ("inventory", "Inventarizatsiya natijasida"),
    ("other_income", "Qo'shimcha daromadlar"),
    ("correction", "Hisob-kitobni korrektirovka qilish"),
    ("bank", "Bank xarajatlari"),
    ("interest", "Kredit foizlari"),
    ("fx", "Belgilangan kursga nisbatan foyda yoki zarar"),
]

BS_ROWS = [
    ("assets", "Asosiy vositalar balans qiymati"),
    ("stock", "Xom ashyo va tayyor mahsulotlar"),
    ("reserved", "Bron qilingan tovarlar"),
    ("customers", "Xaridorlar bilan hisob-kitoblar"),
    ("cash", "Pul mablag'lari"),
    ("salary", "Ish haqi hisob-kitobi"),
    ("suppliers", "Ta'minotchilar bilan hisob-kitoblar"),
    ("tax", "Soliqlar"),
    ("utility", "Kommunal to'lovlar"),
    ("third_party", "Turli shaxslar"),
    ("loan", "Kredit qoldig'i (bank krediti)"),
    ("organization", "Tashkilotlar"),
    ("founder", "Ta'sischilar"),
    ("capital", "Zarar yoki foyda"),
    ("residual", "Kurs farqidan zarar yoki foyda"),
]

# rows of counterparties: their Kirim/Chiqim follow the akt sverka (see get_data)
COUNTERPARTY_ROWS = ("customers", "suppliers", "utility", "third_party", "organization", "founder")

# payroll deductions that are a payment of the salary, a tax withheld from it,
# or (anything else) a penalty that lowers the salary cost
PAYMENT_CODES = re.compile(r"AVANS|PLASTIK|KARTA|CARD", re.I)
WITHHELD_TAX = ("tax_income", "tax_pension")

# the stock loads from the company's Excel counts: capital, not profit
OPENING_STOCK_PARAM = "cst_kerama_reports.opening_stock_refs"
OPENING_STOCK_DEFAULT = "Qoldiq %|ТМ ombori yopildi%"

FLOW_LABELS = {
    ("supplier", "internal"): "Ta'minotchidan kirim",
    ("internal", "supplier"): "Ta'minotchiga qaytarish",
    ("production", "internal"): "Ishlab chiqarilgan mahsulot",
    ("internal", "production"): "Ishlab chiqarishga sarf",
    ("internal", "customer"): "Mijozga sotilgan",
    ("customer", "internal"): "Mijozdan qaytgan",
    ("inventory", "internal"): "Inventarizatsiya (ortiqcha) / kirim",
    ("internal", "inventory"): "Inventarizatsiya (kam) / hisobdan chiqarish",
}


class KassaCategory(models.Model):
    _inherit = "cst.kassa.category"

    cst_pl_line = fields.Selection(
        PL_LINES, string="Foyda/zarar qatori",
        help="Which row of «Foyda va zarar» / «Balans» this modda feeds. Empty: a cash-out modda "
             "is «Kassadan xarajatlar», a cash-in modda «Qo'shimcha daromadlar». The «Balans:» "
             "choices are not an expense at all (salary or tax paid, a loan, money to another "
             "organisation or a founder) and only move that balance row.")


class CstFinanceSheet(models.AbstractModel):
    """Shared plumbing of the two sheets."""

    _name = "cst.finance.sheet"
    _description = "Foyda va zarar / Balans (umumiy)"

    @api.model
    def _check_rights(self):
        if not self.env.user.has_group("account.group_account_readonly"):
            raise AccessError(_("Moliyaviy hisobotlarni ko'rishga ruxsatingiz yo'q."))

    @api.model
    def get_defaults(self):
        self._check_rights()
        today = fields.Date.context_today(self)
        return {
            "date_from": fields.Date.to_string(today.replace(day=1)),
            "date_to": fields.Date.to_string(today),
            "company_ids": [self.env.company.id],
            "companies": [{"id": c.id, "name": c.name} for c in self.env.user.company_ids],
        }

    @api.model
    def _parse(self, options):
        options = dict(options or {})
        today = fields.Date.context_today(self)
        date_from = fields.Date.to_date(options.get("date_from")) or today.replace(day=1)
        date_to = fields.Date.to_date(options.get("date_to")) or today
        if date_to < date_from:
            date_from, date_to = date_to, date_from
        allowed = self.env.user.company_ids
        companies = allowed.filtered(lambda c: c.id in (options.get("company_ids") or []))
        return {
            "date_from": date_from,
            "date_to": date_to,
            "companies": companies or self.env.company,
        }

    @api.model
    def _bounds(self, date_from, date_to):
        return self.env["cst.profitability.report"]._utc_bounds(date_from, date_to)

    @api.model
    def _converter(self, company):
        """``convert(amount, currency, date)`` into the company currency, rates cached."""
        target = company.currency_id
        cache = {}

        def convert(amount, currency, day):
            if not amount or not currency or currency == target:
                return amount or 0.0
            key = (currency.id, day)
            if key not in cache:
                cache[key] = currency._convert(1.0, target, company, day or fields.Date.today(), round=False)
            return amount * cache[key]

        return convert

    @api.model
    def _local_date(self, value):
        if not value:
            return False
        if hasattr(value, "hour"):
            return fields.Datetime.context_timestamp(self, value).date()
        return value

    @api.model
    def _opening_stock_refs(self):
        raw = self.env["ir.config_parameter"].sudo().get_param(OPENING_STOCK_PARAM, OPENING_STOCK_DEFAULT)
        return [p.strip() for p in (raw or "").split("|") if p.strip()]

    @api.model
    def _kassa_ops(self, company, date_from, date_to, types=("expense", "other_in")):
        Operation = self.env["cst.kassa.operation"].sudo()
        domain = [("state", "=", "done"), ("company_id", "=", company.id), ("operation_type", "in", list(types))]
        if date_from:
            domain.append(("date", ">=", date_from))
        if date_to:
            domain.append(("date", "<=", date_to))
        return Operation.search(domain, order="date, id")

    @api.model
    def _kassa_line(self, op):
        line = op.category_id.cst_pl_line
        if line:
            return line
        return "other_income" if op.direction == "in" else "kassa"

    @api.model
    def _detail(self, day, label, currency, amount, value, model=False, res_id=False, partner=""):
        return {
            "date": fields.Date.to_string(day) if day else "",
            "label": label or "",
            "partner": partner or "",
            "currency": (currency.name if currency else "") or "",
            "amount": amount,
            "value": value,
            "model": model or "",
            "res_id": res_id or 0,
        }


class CstPlSheet(models.AbstractModel):
    _name = "cst.pl.sheet"
    _inherit = "cst.finance.sheet"
    _description = "Foyda va zarar (Excel shakli)"

    @api.model
    def get_data(self, options):
        self._check_rights()
        opts = self._parse(options)
        blocks = [self.company_block(company, opts["date_from"], opts["date_to"]) for company in opts["companies"]]
        currency = opts["companies"][0].currency_id
        return {
            "date_from": fields.Date.to_string(opts["date_from"]),
            "date_to": fields.Date.to_string(opts["date_to"]),
            "currency": currency.name,
            "companies": blocks,
            "income": sum(b["income"] for b in blocks),
            "expense": sum(b["expense"] for b in blocks),
            "profit": sum(b["profit"] for b in blocks),
        }

    @api.model
    def company_block(self, company, date_from, date_to):
        """One company: its 16 rows, each with the documents behind it."""
        rows = {key: {"no": i + 1, "key": key, "name": name, "income": 0.0, "expense": 0.0,
                      "details": []}
                for i, (key, name) in enumerate(PL_ROWS)}
        ctx = {
            "company": company,
            "date_from": date_from,
            "date_to": date_to,
            "bounds": self._bounds(date_from, date_to),
            "convert": self._converter(company),
        }

        def add(key, income=0.0, expense=0.0, detail=None):
            row = rows[key]
            row["income"] += income
            row["expense"] += expense
            if detail is not None:
                detail["income"] = income
                detail["expense"] = expense
                row["details"].append(detail)

        self._pl_sales(ctx, add)
        self._pl_stock(ctx, add)
        self._pl_kassa(ctx, add)
        self._pl_payroll(ctx, add)
        self._pl_depreciation(ctx, add)
        self._pl_bills(ctx, add)
        self._pl_ledger(ctx, add)

        result = []
        for key, _name in PL_ROWS:
            row = rows[key]
            row["details"].sort(key=lambda d: (d["date"], d["label"]))
            result.append(row)
        income = sum(r["income"] for r in result)
        expense = sum(r["expense"] for r in result)
        return {
            "id": company.id,
            "name": company.name,
            "currency": company.currency_id.name,
            "rows": result,
            "income": income,
            "expense": expense,
            "profit": income - expense,
        }

    # ------------------------------------------------------------------
    # 1, 2, 9 (income) — what the clients received
    # ------------------------------------------------------------------
    @api.model
    def _pl_sales(self, ctx, add):
        company = ctx["company"]
        engine = self.env["cst.profitability.report"]
        opts = {
            "date_from": ctx["date_from"], "date_to": ctx["date_to"], "company_ids": [company.id],
            "warehouse_ids": [], "categ_ids": [], "partner_ids": [], "user_ids": [], "services": False,
        }
        docs = {}
        for entry in engine._entries(opts):
            key = (entry["kind"],) + entry["doc"]
            doc = docs.get(key)
            if doc is None:
                order = entry["order"]
                if entry["doc"][0] == "order":
                    model, res_id, label = "sale.order", order.id, order.name
                else:
                    picking = self.env["stock.picking"].sudo().browse(entry["doc"][1])
                    model, res_id = "stock.picking", picking.id
                    label = "%s%s" % (picking.name or "", " (%s)" % order.name if order else "")
                doc = docs[key] = {"kind": entry["kind"], "date": entry["date"], "label": label,
                                   "partner": entry["partner"].name or "", "model": model, "res_id": res_id,
                                   "amount": 0.0, "cost": 0.0}
            doc["amount"] += entry["amount"]
            doc["cost"] += entry["cost"]
            doc["date"] = min(doc["date"], entry["date"])
        currency = company.currency_id
        for doc in docs.values():
            returned = doc["kind"] == "return"
            label = _("Qaytarish: %s", doc["label"]) if returned else doc["label"]
            detail = self._detail(doc["date"], label, currency, doc["amount"], doc["amount"],
                                  doc["model"], doc["res_id"], doc["partner"])
            if returned:
                add("sales", expense=doc["amount"], detail=detail)
                add("cogs", expense=-doc["cost"], detail=dict(detail, amount=-doc["cost"], value=-doc["cost"]))
            else:
                add("sales", income=doc["amount"], detail=detail)
                add("cogs", expense=doc["cost"], detail=dict(detail, amount=doc["cost"], value=doc["cost"]))
        start, end = ctx["bounds"]
        for entry in engine._service_entries(dict(opts, services=True), start, end,
                                             lambda a, cur, comp, day: ctx["convert"](a, cur, day)):
            order = entry["order"]
            add("service", income=entry["amount"], detail=self._detail(
                entry["date"], "%s · %s" % (order.name, entry["product"].display_name), currency,
                entry["amount"], entry["amount"], "sale.order", order.id, entry["partner"].name))

    # ------------------------------------------------------------------
    # 3, 10, 11 — stock leaving or arriving outside of sales
    # ------------------------------------------------------------------
    @api.model
    def _pl_stock(self, ctx, add):
        company = ctx["company"]
        start, end = ctx["bounds"]
        Move = self.env["stock.move"].sudo()
        currency = company.currency_id
        moves = Move.search([
            ("state", "=", "done"), ("company_id", "=", company.id),
            ("date", ">=", start), ("date", "<=", end),
            "|", ("location_id.usage", "in", ("inventory", "production")),
            ("location_dest_id.usage", "in", ("inventory", "production")),
        ], order="date, id")
        resets = self._opening_stock_refs()

        resets = [re.compile(".*".join(map(re.escape, p.split("%"))), re.I | re.S) for p in resets]

        def is_reset(move):
            return any(p.fullmatch(move.reference or "") for p in resets)

        for move in moves:
            src, dst = move.location_id.usage, move.location_dest_id.usage
            value = abs(move.value or 0.0)
            fuel = move.product_id.product_tmpl_id.cst_is_fuel
            day = self._local_date(move.date)
            label = "%s · %s" % (move.reference or move.picking_id.name or "", move.product_id.display_name)
            qty_note = "%s %s" % (self.env["cst.partner.statement"]._fmt(move.quantity), move.product_uom.name)

            def detail(amount):
                return self._detail(day, label, currency, amount, amount, "stock.move", move.id, qty_note)

            if fuel and src == "internal" and dst in ("inventory", "production") and not move.is_inventory:
                add("fuel", expense=value, detail=detail(value))
            elif move.is_inventory:
                if is_reset(move):
                    continue  # an opening load: capital, see the balance sheet
                if dst == "internal":
                    add("inventory", income=value, detail=detail(value))
                elif src == "internal":
                    add("inventory", expense=value, detail=detail(value))
            elif src == "internal" and dst == "inventory":
                add("writeoff", expense=value, detail=detail(value))
            elif src == "inventory" and dst == "internal":
                # the 2-sort twin of a regraded piece, or a scrap put back: the loss is the difference
                add("writeoff", expense=-value, detail=detail(-value))

    # ------------------------------------------------------------------
    # 4, 6, 8, 9, 12, 13, 14, 15 — kassa operations by their modda
    # ------------------------------------------------------------------
    @api.model
    def _pl_kassa(self, ctx, add):
        rows = {key for key, _n in PL_ROWS}
        for op in self._kassa_ops(ctx["company"], ctx["date_from"], ctx["date_to"]):
            line = self._kassa_line(op)
            if line not in rows:
                continue  # a balance-only modda
            value = op.amount_company or 0.0
            sign = 1 if op.direction == "out" else -1
            if line == "other_income":
                sign = -sign
            label = " · ".join(b for b in (op.name, op.category_id.name, op.memo) if b)
            detail = self._detail(op.date, label, op.currency_id, op.amount, value,
                                  "cst.kassa.operation", op.id, op.partner_id.name or op.employee_id.name or "")
            if line == "other_income":
                add(line, income=sign * value, detail=detail)
            else:
                add(line, expense=sign * value, detail=detail)

    # ------------------------------------------------------------------
    # 5, 6 — payroll
    # ------------------------------------------------------------------
    @api.model
    def _pl_payroll(self, ctx, add):
        company = ctx["company"]
        lines = self.env["cst.payroll.line"].sudo().search([
            ("company_id", "=", company.id), ("state", "!=", "cancel"),
            ("date", ">=", ctx["date_from"]), ("date", "<=", ctx["date_to"]),
        ], order="date, id")
        for line in lines:
            component = line.component_id
            value = ctx["convert"](line.amount, line.currency_id, line.date)
            label = "%s · %s" % (component.name, line.name or "")
            detail = self._detail(line.date, label, line.currency_id, line.amount, value,
                                  "cst.payroll.line", line.id, line.employee_id.name)
            if line.kind == "accrual":
                add("salary", expense=value, detail=detail)
            elif line.kind == "employer":
                add("tax", expense=value, detail=detail)
            elif (line.kind == "deduction" and component.computation not in WITHHELD_TAX
                  and not PAYMENT_CODES.search(component.code or "")):
                # a penalty: the employee gets less, the salary cost is lower
                add("salary", expense=-value, detail=dict(detail, amount=-line.amount, value=-value))

    # ------------------------------------------------------------------
    # 7 — depreciation
    # ------------------------------------------------------------------
    @api.model
    def _pl_depreciation(self, ctx, add):
        company = ctx["company"]
        moves = self.env["account.move"].sudo().search([
            ("company_id", "=", company.id), ("state", "=", "posted"), ("asset_id", "!=", False),
            ("asset_move_type", "=", "depreciation"),
            ("date", ">=", ctx["date_from"]), ("date", "<=", ctx["date_to"]),
        ], order="date, id")
        for move in moves:
            value = move.depreciation_value
            add("depreciation", expense=value, detail=self._detail(
                move.date, "%s · %s" % (move.name, move.asset_id.name), company.currency_id, value, value,
                "account.move", move.id))

    # ------------------------------------------------------------------
    # 8, 9 (expense) — bought services and utility bills
    # ------------------------------------------------------------------
    @api.model
    def _utility_partners(self):
        tag = self.env.ref("cst_kerama_reports.partner_category_utilities", raise_if_not_found=False)
        if not tag:
            return self.env["res.partner"]
        return self.env["res.partner"].sudo().with_context(active_test=False).search(
            [("category_id", "in", tag.ids)])

    @api.model
    def _pl_bills(self, ctx, add):
        company = ctx["company"]
        start, end = ctx["bounds"]
        utilities = set(self._utility_partners().ids)
        currency = company.currency_id
        # services ordered from suppliers — the order is the document, as everywhere
        po_lines = self.env["purchase.order.line"].sudo().search([
            ("order_id.state", "in", ("purchase", "done")),
            ("order_id.company_id", "=", company.id),
            ("order_id.date_approve", ">=", start), ("order_id.date_approve", "<=", end),
            ("product_id.type", "=", "service"), ("display_type", "=", False),
        ])
        for line in po_lines:
            order = line.order_id
            day = self._local_date(order.date_approve)
            partner = order.partner_id.commercial_partner_id
            value = ctx["convert"](line.price_subtotal, order.currency_id, day)
            add("utility" if partner.id in utilities else "service", expense=value, detail=self._detail(
                day, "%s · %s" % (order.name, line.product_id.display_name), order.currency_id,
                line.price_subtotal, value, "purchase.order", order.id, partner.name))
        # stand-alone bills: not from an order, not a landed cost, not fuel bought into stock
        excluded = set()
        for model in ("cst.picking.expense", "cst.fuel.log"):
            if model in self.env:
                excluded |= set(self.env[model].sudo().search([("bill_id", "!=", False)]).bill_id.ids)
        if "stock.landed.cost" in self.env:
            excluded |= set(self.env["stock.landed.cost"].sudo().search([("vendor_bill_id", "!=", False)])
                            .vendor_bill_id.ids)
        lines = self.env["account.move.line"].sudo().search([
            ("company_id", "=", company.id), ("parent_state", "=", "posted"),
            ("move_id.move_type", "in", ("in_invoice", "in_refund", "in_receipt")),
            ("display_type", "=", "product"), ("purchase_line_id", "=", False),
            ("account_id.account_type", "in", ("expense", "expense_direct_cost")),
            ("date", ">=", ctx["date_from"]), ("date", "<=", ctx["date_to"]),
            ("move_id", "not in", list(excluded)),
        ], order="date, id")
        for line in lines:
            if "is_landed_costs_line" in line._fields and line.is_landed_costs_line:
                continue
            partner = line.move_id.partner_id.commercial_partner_id
            add("utility" if partner.id in utilities else "service", expense=line.balance, detail=self._detail(
                line.date, "%s · %s" % (line.move_id.name, line.name or ""), line.currency_id,
                line.amount_currency, line.balance, "account.move", line.move_id.id, partner.name))

    # ------------------------------------------------------------------
    # 13, 14, 16 — straight from the ledger
    # ------------------------------------------------------------------
    @api.model
    def _pl_ledger(self, ctx, add):
        company = ctx["company"]
        currency = company.currency_id
        Line = self.env["account.move.line"].sudo()
        period = [("company_id", "=", company.id), ("parent_state", "=", "posted"),
                  ("date", ">=", ctx["date_from"]), ("date", "<=", ctx["date_to"])]
        kassa_moves = self.env["cst.kassa.operation"].sudo().search(
            [("company_id", "=", company.id), ("move_id", "!=", False)]).move_id

        def detail(line):
            return self._detail(line.date, "%s · %s" % (line.move_id.name, line.name or ""), line.currency_id,
                                line.amount_currency, -line.balance, "account.move", line.move_id.id,
                                line.partner_id.name or "")

        # 16 exchange differences
        fx_accounts = company.income_currency_exchange_account_id | company.expense_currency_exchange_account_id
        for line in Line.search(period + [("account_id", "in", fx_accounts.ids)], order="date, id"):
            gain = -line.balance
            if gain >= 0:
                add("fx", income=gain, detail=dict(detail(line), value=gain))
            else:
                add("fx", expense=-gain, detail=dict(detail(line), value=-gain))
        # 13 cash count differences of confirmed kassa days
        diff_moves = self.env["cst.kassa.day"].sudo().search(
            [("company_id", "=", company.id), ("difference_move_id", "!=", False)]).difference_move_id
        if diff_moves:
            for line in Line.search(period + [
                    ("move_id", "in", diff_moves.ids),
                    ("account_id.account_type", "in", ("income", "income_other", "expense"))]):
                gain = -line.balance
                if gain >= 0:
                    add("correction", income=gain, detail=dict(detail(line), value=gain))
                else:
                    add("correction", expense=-gain, detail=dict(detail(line), value=-gain))
        # 14 bank fees: expenses booked inside bank journals, outside the kassa
        for line in Line.search(period + [
                ("journal_id.type", "=", "bank"),
                ("account_id.account_type", "in", ("expense", "expense_direct_cost")),
                ("move_id", "not in", kassa_moves.ids)], order="date, id"):
            add("bank", expense=line.balance, detail=dict(detail(line), value=line.balance))
        # 6 taxes assessed by hand (05.11): a journal entry in «Soliq deklaratsiyalari» or any
        # general journal that charges a tax account and books the cost to an expense account
        # (Dt soliq xarajati / Kt Ер солиғи…).  What reaches the profit is the expense line.
        # Payroll and kassa entries are left out: _pl_payroll and _pl_kassa count them already;
        # so are exchange and cash-count differences (their own rows above).
        tax_accounts = self.env["cst.tax.report"].sudo().default_accounts(company)
        payroll_moves = (self.env["cst.payroll.line"].sudo().search(
            [("company_id", "=", company.id), ("move_id", "!=", False)]).move_id
            | self.env["cst.payroll.period"].sudo().search(
                [("company_id", "=", company.id), ("move_id", "!=", False)]).move_id)
        if tax_accounts:
            for line in Line.search(period + [
                    ("journal_id.type", "=", "general"),
                    ("account_id.account_type", "in", ("expense", "expense_direct_cost")),
                    ("account_id", "not in", fx_accounts.ids),
                    ("move_id.line_ids.account_id", "in", tax_accounts.ids),
                    ("move_id", "not in", (kassa_moves | payroll_moves | diff_moves).ids)], order="date, id"):
                add("tax", expense=line.balance, detail=dict(detail(line), value=line.balance))


class CstBalanceSheet(models.AbstractModel):
    _name = "cst.balance.sheet"
    _inherit = "cst.finance.sheet"
    _description = "Balans (Excel shakli)"

    @api.model
    def get_data(self, options):
        self._check_rights()
        opts = self._parse(options)
        company = opts["companies"][:1]
        date_from, date_to = opts["date_from"], opts["date_to"]
        start, end = self._bounds(date_from, date_to)
        ctx = {
            "company": company,
            "date_from": date_from,
            "date_to": date_to,
            "start": start,
            "end": end,
            "convert": self._converter(company),
        }
        rows = {key: {"no": i + 1, "key": key, "name": name, "open": 0.0, "debit": 0.0, "credit": 0.0,
                      "details": []}
                for i, (key, name) in enumerate(BS_ROWS)}

        def add(key, label, opening=0.0, debit=0.0, credit=0.0, model=False, res_id=False):
            row = rows[key]
            row["open"] += opening
            row["debit"] += debit
            row["credit"] += credit
            if any(abs(v) > 0.005 for v in (opening, debit, credit)):
                row["details"].append({"label": label, "open": opening, "debit": debit, "credit": credit,
                                       "close": opening + debit - credit, "model": model or "",
                                       "res_id": res_id or 0})

        self._bs_assets(ctx, add)
        self._bs_stock(ctx, add)
        self._bs_reserved(ctx, add)
        self._bs_partners(ctx, add)
        self._bs_cash(ctx, add)
        self._bs_payroll(ctx, add)
        self._bs_ledger(ctx, add)
        self._bs_kassa(ctx, add)

        pl = self.env["cst.pl.sheet"].company_block(company, date_from, date_to)
        balance_keys = [k for k, _n in BS_ROWS if k not in ("capital", "residual")]
        open_capital = -sum(rows[k]["open"] for k in balance_keys)
        add("capital", _("Davr boshidagi sarmoya"), opening=open_capital)
        add("capital", _("Davr daromadlari (Foyda va zarar)"), credit=pl["income"])
        add("capital", _("Davr xarajatlari (Foyda va zarar)"), debit=pl["expense"])
        self._bs_capital_corrections(ctx, add)

        # assets above liabilities + capital (closing > 0): the capital grows by the gap
        closing = sum(rows[k]["open"] + rows[k]["debit"] - rows[k]["credit"] for k in balance_keys + ["capital"])
        residual = rows["residual"]
        if abs(closing) > 0.005:
            production = self._production_difference(ctx)
            parts = [(_("Ishlab chiqarishda tannarx farqi"), production, False, 0)] \
                if abs(production) > 0.005 else []
            parts += self._receipts_without_order(ctx)
            explained = sum(p[1] for p in parts)
            # clickable (05.11): opens the period's exchange-difference journal items
            parts.append((_("Valyuta kursi farqi va boshqa farqlar"), closing - explained,
                          "fx:%s:%s" % (date_from, date_to), company.id))
            for label, amount, model, res_id in parts:
                add("residual", label, debit=max(-amount, 0.0), credit=max(amount, 0.0),
                    model=model, res_id=res_id)
            for detail in residual["details"]:
                detail["close"] = 0.0  # the row keeps no balance, the capital takes it

        result = []
        for key, _name in BS_ROWS:
            row = rows[key]
            row["close"] = row["open"] + row["debit"] - row["credit"]
            if key == "capital":
                row["close"] += residual["debit"] - residual["credit"]
            if key == "residual":
                row["close"] = 0.0
            row["details"].sort(key=lambda d: -abs(d["close"]) - abs(d["debit"]) - abs(d["credit"]))
            if key in COUNTERPARTY_ROWS:
                # 05.11: a counterparty reads like its akt sverka / harakat report —
                # Kirim = what came from them (payment, goods), Chiqim = what went to
                # them.  Balances are unchanged; only the two turnover columns swap.
                row["debit"], row["credit"] = row["credit"], row["debit"]
                for detail in row["details"]:
                    detail["debit"], detail["credit"] = detail["credit"], detail["debit"]
            result.append(row)

        def side(value, positive):
            return value if (value > 0) == positive and abs(value) > 0.005 else 0.0

        for row in result:
            row["open_dr"], row["open_cr"] = side(row["open"], True), -side(row["open"], False)
            row["close_dr"], row["close_cr"] = side(row["close"], True), -side(row["close"], False)
        totals = {k: sum(r[k] for r in result)
                  for k in ("open_dr", "open_cr", "debit", "credit", "close_dr", "close_cr")}
        capital = rows["capital"]
        return {
            "company": {"id": company.id, "name": company.name},
            "currency": company.currency_id.name,
            "date_from": fields.Date.to_string(date_from),
            "date_to": fields.Date.to_string(date_to),
            "rows": result,
            "totals": totals,
            "cards": {
                "open_capital": -open_capital,
                "profit": pl["profit"],
                "loan": -rows["loan"]["close"],
                "close_capital": -capital["close"],
                "corrections": sum(d["credit"] - d["debit"] for d in capital["details"]
                                   if d.get("model") == "correction"),
            },
        }

    # ------------------------------------------------------------------
    # 1 fixed assets
    # ------------------------------------------------------------------
    @api.model
    def _bs_assets(self, ctx, add):
        company = ctx["company"]
        if "account.asset" not in self.env:
            return
        Asset = self.env["account.asset"].sudo()
        assets = Asset.search([("company_id", "=", company.id), ("state", "not in", ("draft", "model")),
                               ("acquisition_date", "<=", ctx["date_to"])])

        def book_value(asset, day):
            if not asset.acquisition_date or asset.acquisition_date > day:
                return 0.0
            if asset.disposal_date and asset.disposal_date <= day:
                return 0.0
            value = asset.currency_id._convert(asset.original_value, company.currency_id, company,
                                               asset.acquisition_date)
            done = asset.depreciation_move_ids.filtered(lambda m: m.state == "posted" and m.date <= day)
            # assets brought in with their old-system depreciation (opening balance)
            imported = asset.currency_id._convert(asset.already_depreciated_amount_import, company.currency_id,
                                                  company, asset.acquisition_date)
            return value - imported - sum(done.mapped("depreciation_value"))

        before = ctx["date_from"] - timedelta(days=1)
        for asset in assets:
            opening, closing = book_value(asset, before), book_value(asset, ctx["date_to"])
            debit = 0.0
            if asset.acquisition_date >= ctx["date_from"]:
                debit = asset.currency_id._convert(asset.original_value, company.currency_id, company,
                                                   asset.acquisition_date)
            credit = opening + debit - closing  # depreciation and disposals
            add("assets", asset.name, opening=opening, debit=debit, credit=credit,
                model="account.asset", res_id=asset.id)

    # ------------------------------------------------------------------
    # 2 stock at its valuation (stock.move.value of every valued move)
    # ------------------------------------------------------------------
    @api.model
    def _bs_stock(self, ctx, add):
        company = ctx["company"]
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT ls.usage, ld.usage, m.is_in,
                   SUM(CASE WHEN m.date < %(start)s THEN m.value ELSE 0 END),
                   SUM(CASE WHEN m.date >= %(start)s AND m.date <= %(end)s THEN m.value ELSE 0 END)
              FROM stock_move m
              JOIN stock_location ls ON ls.id = m.location_id
              JOIN stock_location ld ON ld.id = m.location_dest_id
             WHERE m.state = 'done' AND m.company_id = %(company)s
               AND (m.is_in OR m.is_out) AND m.date <= %(end)s
          GROUP BY 1, 2, 3
        """, {"start": ctx["start"], "end": ctx["end"], "company": company.id})
        for src, dst, is_in, before, during in self.env.cr.fetchall():
            before, during = before or 0.0, during or 0.0
            label = FLOW_LABELS.get((src, dst), "%s → %s" % (src, dst))
            if is_in:
                add("stock", label, opening=before, debit=during)
            else:
                add("stock", label, opening=-before, credit=during)

    # ------------------------------------------------------------------
    # 3 orders taken but not yet delivered / received
    # ------------------------------------------------------------------
    @api.model
    def _open_order_values(self, ctx, moment):
        """(goods owed to clients on confirmed sales orders, goods owed to us
        on confirmed purchase orders) at ``moment``, at the order price — the
        counterparty balances count an order in full from its date."""
        company = ctx["company"]
        self.env.flush_all()
        result = {}
        for kind, table, line_table, date_col, qty_col, usage in (
                ("sale", "sale_order", "sale_order_line", "date_order", "product_uom_qty", "customer"),
                ("purchase", "purchase_order", "purchase_order_line", "date_approve", "product_qty", "supplier")):
            link = "sale_line_id" if kind == "sale" else "purchase_line_id"
            self.env.cr.execute(f"""
                SELECT l.id, o.id, o.name, o.{date_col}, o.currency_id, l.price_total, l.{qty_col},
                       COALESCE((SELECT SUM(CASE WHEN ld.usage = %(usage)s THEN m.quantity
                                                 ELSE -m.quantity END)
                                   FROM stock_move m
                                   JOIN stock_location ls ON ls.id = m.location_id
                                   JOIN stock_location ld ON ld.id = m.location_dest_id
                                  WHERE m.{link} = l.id AND m.state = 'done' AND m.date <= %(moment)s
                                    AND (ld.usage = %(usage)s) <> (ls.usage = %(usage)s)), 0)
                  FROM {line_table} l
                  JOIN {table} o ON o.id = l.order_id
                  JOIN product_product pp ON pp.id = l.product_id
                  JOIN product_template pt ON pt.id = pp.product_tmpl_id
                 WHERE o.company_id = %(company)s AND o.state IN ('sale', 'purchase', 'done')
                   AND o.{date_col} <= %(moment)s AND pt.type <> 'service'
                   AND l.display_type IS NULL AND l.{qty_col} > 0
            """, {"usage": usage, "moment": moment, "company": company.id})
            orders = {}
            Currency = self.env["res.currency"]
            for _lid, oid, name, day, currency_id, total, ordered, moved in self.env.cr.fetchall():
                # a delivery in the client's direction counts as done; the move quantity
                # is in the line's unit for nearly every line here (same uom on both)
                if kind == "purchase":
                    moved = -moved
                left = max(0.0, ordered - max(0.0, moved))
                if not left:
                    continue
                value = ctx["convert"](total * left / ordered, Currency.browse(currency_id),
                                       self._local_date(day))
                entry = orders.setdefault(oid, [name, 0.0])
                entry[1] += value
            result[kind] = orders
        return result

    @api.model
    def _bs_reserved(self, ctx, add):
        before = self._open_order_values(ctx, ctx["start"] - timedelta(microseconds=1))
        after = self._open_order_values(ctx, ctx["end"])
        for kind, sign, model in (("sale", -1, "sale.order"), ("purchase", 1, "purchase.order")):
            for oid in set(before[kind]) | set(after[kind]):
                name = (before[kind].get(oid) or after[kind].get(oid))[0]
                opening = sign * before[kind].get(oid, [name, 0.0])[1]
                closing = sign * after[kind].get(oid, [name, 0.0])[1]
                change = closing - opening
                if abs(closing) <= 0.005 and abs(opening) > 0.005:
                    # 05.11: delivered / received inside the period — the row only shows the movement
                    label = _("%s — davr ichida mijozga berildi", name) if kind == "sale" else \
                        _("%s — davr ichida ta'minotchidan keldi", name)
                else:
                    label = _("%s — mijozga berilmagan tovar", name) if kind == "sale" else \
                        _("%s — ta'minotchidan kelmagan tovar", name)
                add("reserved", label, opening=opening, debit=max(change, 0.0), credit=max(-change, 0.0),
                    model=model, res_id=oid)

    # ------------------------------------------------------------------
    # 4, 7, 9, 10, 12, 13 counterparties
    # ------------------------------------------------------------------
    @api.model
    def _partner_buckets(self, company):
        """Every counterparty of the company in exactly one row."""
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT DISTINCT p.commercial_partner_id
              FROM account_move_line l
              JOIN account_account a ON a.id = l.account_id
              JOIN res_partner p ON p.id = l.partner_id
             WHERE l.company_id = %(c)s AND l.parent_state = 'posted'
               AND a.account_type IN ('asset_receivable', 'liability_payable')
            UNION
            SELECT DISTINCT p.commercial_partner_id FROM sale_order o JOIN res_partner p ON p.id = o.partner_id
             WHERE o.company_id = %(c)s AND o.state IN ('sale', 'done')
            UNION
            SELECT DISTINCT p.commercial_partner_id FROM purchase_order o JOIN res_partner p ON p.id = o.partner_id
             WHERE o.company_id = %(c)s AND o.state IN ('purchase', 'done')
        """, {"c": company.id})
        Partner = self.env["res.partner"].sudo().with_context(active_test=False)
        partners = Partner.browse([r[0] for r in self.env.cr.fetchall() if r[0]])
        group = set(self.env["res.company"].sudo().search([]).partner_id.commercial_partner_id.ids)
        employees = set(self.env["hr.employee"].sudo().with_context(active_test=False).search(
            [("work_contact_id", "!=", False)]).work_contact_id.ids)

        def tag(xmlid):
            record = self.env.ref(xmlid, raise_if_not_found=False)
            return record.id if record else 0

        founder = tag("cst_kerama_reports.partner_category_founders")
        utility = tag("cst_kerama_reports.partner_category_utilities")
        third = tag("cst_kerama_reports.partner_category_third_party")
        buckets = defaultdict(list)
        for partner in partners:
            tags = set(partner.category_id.ids)
            if partner.id in group:
                key = "organization"
            elif founder in tags:
                key = "founder"
            elif utility in tags:
                key = "utility"
            elif third in tags:
                key = "third_party"
            elif partner.customer_rank > 0:
                key = "customers"
            elif partner.supplier_rank > 0:
                key = "suppliers"
            elif partner.id in employees:
                continue  # salary advances: the payroll row has them
            else:
                key = "third_party"
            buckets[key].append(partner.id)
        return buckets

    @api.model
    def _bs_partners(self, ctx, add):
        company = ctx["company"]
        engine = self.env["cst.partner.statement"].sudo().with_company(company)
        for key, partner_ids in self._partner_buckets(company).items():
            blocks = engine.movement_rows(None, ctx["date_from"], ctx["date_to"], partner_ids=partner_ids,
                                          company_ids=[company.id], hide_empty=True,
                                          display_currency=company.currency_id)
            for block in blocks:
                for prow in block["partners"]:
                    partner = prow["partner"]
                    for cur in prow["currencies"]:
                        add(key, partner.name, opening=cur["open_they_owe"] - cur["open_we_owe"],
                            debit=cur["outflow"], credit=cur["inflow"], model="res.partner", res_id=partner.id)

    # ------------------------------------------------------------------
    # 5 money, 8 taxes, 11 loans — read from the ledger
    # ------------------------------------------------------------------
    @api.model
    def _ledger_sums(self, ctx, accounts, exclude_moves=()):
        if not accounts:
            return []
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT l.account_id,
                   SUM(CASE WHEN l.date < %(df)s THEN l.balance ELSE 0 END),
                   SUM(CASE WHEN l.date >= %(df)s THEN l.debit ELSE 0 END),
                   SUM(CASE WHEN l.date >= %(df)s THEN l.credit ELSE 0 END)
              FROM account_move_line l
             WHERE l.company_id = %(c)s AND l.parent_state = 'posted' AND l.date <= %(dt)s
               AND l.account_id = ANY(%(acc)s) AND NOT (l.move_id = ANY(%(ex)s))
          GROUP BY 1
        """, {"df": ctx["date_from"], "dt": ctx["date_to"], "c": ctx["company"].id,
              "acc": list(accounts.ids), "ex": list(exclude_moves)})
        Account = self.env["account.account"].sudo().with_company(ctx["company"])
        return [(Account.browse(aid), o or 0.0, d or 0.0, c or 0.0) for aid, o, d, c in self.env.cr.fetchall()]

    @api.model
    def _cash_accounts(self, company):
        Account = self.env["account.account"].sudo()
        accounts = Account.search([("company_ids", "in", company.ids), ("account_type", "=", "asset_cash")])
        journals = self.env["account.journal"].sudo().search(
            [("company_id", "=", company.id), ("type", "in", ("cash", "bank"))])
        for journal in journals:
            accounts |= journal._get_journal_inbound_outstanding_payment_accounts()
            accounts |= journal._get_journal_outbound_outstanding_payment_accounts()
        return accounts | company.transfer_account_id

    @api.model
    def _bs_cash(self, ctx, add):
        """5 «Pul mablag'lari» — only our own kassa and bank accounts (05.11).

        Money that Odoo still keeps on a journal's outstanding receipts /
        payments account is that journal's money, so it is added to the
        journal's own account instead of showing «To'lanmagan tushumlar» as a
        separate account.  The liquidity transfer account shows only while it
        holds a balance (money in transit between our kassas)."""
        company = ctx["company"]
        journals = self.env["account.journal"].sudo().search(
            [("company_id", "=", company.id), ("type", "in", ("cash", "bank"))])
        own = self.env["account.account"].sudo().search(
            [("company_ids", "in", company.ids), ("account_type", "=", "asset_cash")]) | journals.default_account_id
        outstanding = self.env["account.account"].sudo()
        for journal in journals:
            outstanding |= journal._get_journal_inbound_outstanding_payment_accounts()
            outstanding |= journal._get_journal_outbound_outstanding_payment_accounts()
        outstanding -= own
        transfer = company.transfer_account_id - own - outstanding

        sums = {account.id: [account, opening, debit, credit]
                for account, opening, debit, credit in self._ledger_sums(ctx, own)}
        loose = defaultdict(lambda: [0.0, 0.0, 0.0])
        for journal, account, opening, debit, credit in self._ledger_sums_by_journal(ctx, outstanding):
            target = journal.default_account_id if journal and journal.default_account_id in own else False
            if target:
                entry = sums.setdefault(target.id, [target, 0.0, 0.0, 0.0])
                entry[1] += opening
                entry[2] += debit
                entry[3] += credit
            else:
                entry = loose[account]
                entry[0] += opening
                entry[1] += debit
                entry[2] += credit
        for account, opening, debit, credit in sums.values():
            add("cash", "%s %s" % (account.code or "", account.name), opening=opening, debit=debit,
                credit=credit, model="account.account", res_id=account.id)
        # outstanding money no journal claims (should not happen): keep it visible
        for account, (opening, debit, credit) in loose.items():
            add("cash", "%s %s" % (account.code or "", account.name), opening=opening, debit=debit,
                credit=credit, model="account.account", res_id=account.id)
        for account, opening, debit, credit in self._ledger_sums(ctx, transfer):
            if abs(opening) > 0.005 or abs(opening + debit - credit) > 0.005:
                add("cash", "%s %s" % (account.code or "", account.name), opening=opening, debit=debit,
                    credit=credit, model="account.account", res_id=account.id)

    @api.model
    def _ledger_sums_by_journal(self, ctx, accounts):
        if not accounts:
            return []
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT l.journal_id, l.account_id,
                   SUM(CASE WHEN l.date < %(df)s THEN l.balance ELSE 0 END),
                   SUM(CASE WHEN l.date >= %(df)s THEN l.debit ELSE 0 END),
                   SUM(CASE WHEN l.date >= %(df)s THEN l.credit ELSE 0 END)
              FROM account_move_line l
             WHERE l.company_id = %(c)s AND l.parent_state = 'posted' AND l.date <= %(dt)s
               AND l.account_id = ANY(%(acc)s)
          GROUP BY 1, 2
        """, {"df": ctx["date_from"], "dt": ctx["date_to"], "c": ctx["company"].id, "acc": list(accounts.ids)})
        Journal = self.env["account.journal"].sudo()
        Account = self.env["account.account"].sudo().with_company(ctx["company"])
        return [(Journal.browse(jid) if jid else Journal, Account.browse(aid), o or 0.0, d or 0.0, c or 0.0)
                for jid, aid, o, d, c in self.env.cr.fetchall()]

    @api.model
    def _payroll_moves(self, company):
        lines = self.env["cst.payroll.line"].sudo().search([("company_id", "=", company.id), ("move_id", "!=", False)])
        periods = self.env["cst.payroll.period"].sudo().search([("move_id", "!=", False)])
        return set((lines.move_id | periods.move_id).ids)

    @api.model
    def _bs_ledger(self, ctx, add):
        company = ctx["company"]
        payroll_moves = self._payroll_moves(company)
        tax_accounts = self.env["cst.tax.report"].sudo().default_accounts(company)
        for account, opening, debit, credit in self._ledger_sums(ctx, tax_accounts, payroll_moves):
            add("tax", "%s %s" % (account.code or "", account.name), opening=opening, debit=debit,
                credit=credit, model="account.account", res_id=account.id)
        loans = self.env["account.account"].sudo().search(
            [("company_ids", "in", company.ids), ("account_type", "=", "liability_non_current")])
        for account, opening, debit, credit in self._ledger_sums(ctx, loans - tax_accounts):
            add("loan", "%s %s" % (account.code or "", account.name), opening=opening, debit=debit,
                credit=credit, model="account.account", res_id=account.id)

    # ------------------------------------------------------------------
    # 6 salary, 8 payroll taxes
    # ------------------------------------------------------------------
    @api.model
    def _bs_payroll(self, ctx, add):
        company = ctx["company"]
        lines = self.env["cst.payroll.line"].sudo().search([
            ("company_id", "=", company.id), ("state", "!=", "cancel"), ("date", "<=", ctx["date_to"]),
        ])
        salary = defaultdict(lambda: [0.0, 0.0, 0.0])
        taxes = defaultdict(lambda: [0.0, 0.0, 0.0])
        for line in lines:
            value = ctx["convert"](line.amount, line.currency_id, line.date)
            component = line.component_id
            before = line.date < ctx["date_from"]
            if line.kind == "employer":
                targets = [(taxes, component.name, -value)]
            elif line.kind == "accrual":
                targets = [(salary, line.employee_id.name, -value)]
            else:
                targets = [(salary, line.employee_id.name, value)]
                if component.computation in WITHHELD_TAX:
                    targets.append((taxes, component.name, -value))
            for bucket, name, signed in targets:
                entry = bucket[name or _("Xodimsiz")]
                if before:
                    entry[0] += signed
                elif signed >= 0:
                    entry[1] += signed
                else:
                    entry[2] += -signed
        for name, (opening, debit, credit) in salary.items():
            add("salary", name, opening=opening, debit=debit, credit=credit)
        for name, (opening, debit, credit) in taxes.items():
            add("tax", _("Oylikdan: %s", name), opening=opening, debit=debit, credit=credit)

    # ------------------------------------------------------------------
    # kassa moddas that are not an expense but move a balance row
    # ------------------------------------------------------------------
    @api.model
    def _bs_kassa(self, ctx, add):
        target = {"salary": "salary", "tax_payment": "tax", "loan": "loan",
                  "organization": "organization", "founder": "founder"}
        company = ctx["company"]
        # rows 8 and 11 read these accounts from the ledger already: a modda
        # booked straight onto one of them would be counted twice
        from_ledger = self.env["cst.tax.report"].sudo().default_accounts(company) \
            | self.env["account.account"].sudo().search(
                [("company_ids", "in", company.ids), ("account_type", "=", "liability_non_current")])
        sums = defaultdict(lambda: [0.0, 0.0, 0.0])
        for op in self._kassa_ops(company, False, ctx["date_to"]):
            key = target.get(self._kassa_line(op))
            if not key or op.category_id.account_id in from_ledger:
                continue
            value = op.amount_company or 0.0
            signed = value if op.direction == "out" else -value
            entry = sums[(key, op.category_id.name)]
            if op.date < ctx["date_from"]:
                entry[0] += signed
            elif signed >= 0:
                entry[1] += signed
            else:
                entry[2] += -signed
        for (key, name), (opening, debit, credit) in sums.items():
            add(key, _("Kassa: %s", name), opening=opening, debit=debit, credit=credit)

    # ------------------------------------------------------------------
    # 14 capital corrections, 15 what is left
    # ------------------------------------------------------------------
    @api.model
    def _bs_capital_corrections(self, ctx, add):
        """Opening loads: balances posted against equity, stock loaded from Excel."""
        company = ctx["company"]
        equity = self.env["account.account"].sudo().search(
            [("company_ids", "in", company.ids), ("account_type", "in", ("equity", "equity_unaffected"))])
        # fixed assets loaded against equity: row 1 already carries them from the
        # asset's own acquisition date, so the load is not a capital change
        asset_loads = self.env["account.move.line"].sudo().search([
            ("company_id", "=", company.id), ("parent_state", "=", "posted"),
            ("account_id.account_type", "=", "asset_fixed"), ("move_id.asset_id", "=", False),
        ]).move_id
        for account, _opening, debit, credit in self._ledger_sums(ctx, equity, asset_loads.ids):
            if debit or credit:
                add("capital", _("Boshlang'ich qoldiq yozuvlari: %s %s", account.code or "", account.name),
                    debit=debit, credit=credit, model="correction")
        patterns = self._opening_stock_refs()
        if not patterns:
            return
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT m.reference, SUM(CASE WHEN m.is_in THEN m.value ELSE 0 END),
                   SUM(CASE WHEN m.is_out THEN m.value ELSE 0 END)
              FROM stock_move m
             WHERE m.state = 'done' AND m.company_id = %(c)s AND m.is_inventory
               AND m.date >= %(start)s AND m.date <= %(end)s AND m.reference ILIKE ANY(%(p)s)
          GROUP BY 1
        """, {"c": company.id, "start": ctx["start"], "end": ctx["end"], "p": patterns})
        for reference, gained, lost in self.env.cr.fetchall():
            add("capital", _("Ombor qoldig'i yuklandi: %s", reference), debit=lost or 0.0, credit=gained or 0.0,
                model="correction")

    @api.model
    def _production_difference(self, ctx):
        """Finished goods valued above (below) what they consumed: stock grew without an expense."""
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT COALESCE(SUM(CASE WHEN m.is_in THEN m.value ELSE -m.value END), 0)
              FROM stock_move m
              JOIN stock_location ls ON ls.id = m.location_id
              JOIN stock_location ld ON ld.id = m.location_dest_id
             WHERE m.state = 'done' AND m.company_id = %(c)s
               AND m.date >= %(start)s AND m.date <= %(end)s
               AND 'production' IN (ls.usage, ld.usage) AND (m.is_in OR m.is_out)
        """, {"c": ctx["company"].id, "start": ctx["start"], "end": ctx["end"]})
        return self.env.cr.fetchone()[0] or 0.0

    @api.model
    def _receipts_without_order(self, ctx):
        """Goods taken in from (or sent back to) a supplier with no purchase order
        behind them — stock moved, nobody's balance did."""
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT p.id, p.name, rp.name,
                   SUM(CASE WHEN ls.usage = 'supplier' THEN m.value ELSE -m.value END)
              FROM stock_move m
              JOIN stock_location ls ON ls.id = m.location_id
              JOIN stock_location ld ON ld.id = m.location_dest_id
              LEFT JOIN stock_picking p ON p.id = m.picking_id
              LEFT JOIN res_partner rp ON rp.id = p.partner_id
             WHERE m.state = 'done' AND m.company_id = %(c)s AND m.purchase_line_id IS NULL
               AND m.date >= %(start)s AND m.date <= %(end)s AND (m.is_in OR m.is_out)
               AND 'supplier' IN (ls.usage, ld.usage)
          GROUP BY 1, 2, 3
        """, {"c": ctx["company"].id, "start": ctx["start"], "end": ctx["end"]})
        return [(_("Buyurtmasiz qabul, ta'minotchi qarzi yo'q: %(doc)s %(partner)s",
                   doc=name or "", partner=partner or ""), value, "stock.picking" if pid else False, pid or 0)
                for pid, name, partner, value in self.env.cr.fetchall() if value and abs(value) > 0.005]

    @api.model
    def action_open(self, model, res_id):
        """Row detail drill-down."""
        self._check_rights()
        if isinstance(model, str) and model.startswith("fx:") and res_id:
            return self._action_exchange_difference(model, res_id)
        if model not in ("res.partner", "account.account", "account.asset", "sale.order", "purchase.order",
                         "stock.move", "stock.picking", "account.move", "cst.kassa.operation",
                         "cst.payroll.line") or not res_id:
            return False
        if model == "account.account":
            return {
                "type": "ir.actions.act_window", "name": _("Jurnal yozuvlari"),
                "res_model": "account.move.line", "views": [(False, "list"), (False, "form")],
                "domain": [("account_id", "=", res_id), ("parent_state", "=", "posted")],
            }
        return {"type": "ir.actions.act_window", "res_model": model, "res_id": res_id,
                "views": [(False, "form")], "target": "current"}

    @api.model
    def _action_exchange_difference(self, key, company_id):
        """«Kurs farqini qayerdan otserka qilsam bo'ladi» — the journal items of
        the period on the company's exchange gain/loss accounts and journal,
        grouped by partner, so each so'm debt's rate difference can be checked."""
        _fx, date_from, date_to = key.split(":")
        company = self.env["res.company"].browse(int(company_id))
        accounts = (company.income_currency_exchange_account_id | company.expense_currency_exchange_account_id).ids
        domain = [("company_id", "=", company.id), ("parent_state", "=", "posted"),
                  ("date", ">=", date_from), ("date", "<=", date_to)]
        journal = company.currency_exchange_journal_id
        where = [("account_id", "in", accounts)]
        if journal:
            where = ["|", ("journal_id", "=", journal.id)] + where
        return {
            "type": "ir.actions.act_window",
            "name": _("Kurs farqi yozuvlari %(start)s – %(end)s", start=date_from, end=date_to),
            "res_model": "account.move.line",
            "views": [(False, "list"), (False, "form")],
            "domain": domain + where,
            "context": {"group_by": ["partner_id"], "search_default_posted": 1},
        }
