from collections import defaultdict

from odoo import api, fields, models

TAX_CODE_PREFIXES = ("64", "65")


class AccountAsset(models.Model):
    """The three things the fixed-asset register asks for that Odoo's asset
    card does not carry: an inventory number, when it was made, where it is."""

    _inherit = "account.asset"

    cst_inventory_no = fields.Char(string="Inventar raqami", copy=False)
    cst_manufacture_date = fields.Date(string="Ishlab chiqarilgan sanasi")
    cst_location = fields.Char(string="Qayerda joylashgan",
                               help="Sex, ombor, xona — hisobotda ko'rinadigan joy.")


class CstProductionFactReport(models.AbstractModel):
    """«Ishlab chiqarish fakti» — what came off the line in the period, by
    category, with the characteristic and the quantity."""

    _name = "cst.production.fact.report"
    _description = "Ishlab chiqarish fakti"
    _inherit = "cst.stock.report.base"

    @api.model
    def build(self, date_from, date_to, company_ids=None, product_ids=None):
        companies = self._companies(company_ids)
        domain = [("state", "=", "done"), ("company_id", "in", companies.ids),
                  ("date_finished", ">=", fields.Datetime.to_datetime(date_from)),
                  ("date_finished", "<=", fields.Datetime.to_datetime(date_to).replace(
                      hour=23, minute=59, second=59))]
        if product_ids:
            domain.append(("product_id", "in", product_ids))
        orders = self.env["mrp.production"].sudo().search(domain)
        result = []
        for company in companies:
            categories = {}
            totals = {"quantity": 0.0, "second": 0.0, "scrap": 0.0}
            for mo in orders.filtered(lambda m: m.company_id == company):
                out = self._mo_output(mo)
                cat = categories.setdefault(mo.product_id.categ_id.id, {
                    "category": mo.product_id.categ_id, "products": {},
                    "quantity": 0.0, "second": 0.0, "scrap": 0.0})
                prod = cat["products"].setdefault(mo.product_id.id, {
                    "product": mo.product_id, "characteristic": self._characteristic(mo.product_id),
                    "uom": mo.product_id.uom_id.name, "quantity": 0.0, "second": 0.0,
                    "scrap": 0.0, "orders": 0})
                prod["orders"] += 1
                for key, qty in out.items():
                    prod[key] += qty
                    cat[key] += qty
                    totals[key] += qty
            if not categories:
                continue
            for cat in categories.values():
                cat["products"] = sorted(cat["products"].values(),
                                         key=lambda p: p["product"].display_name or "")
            result.append({
                "company": company,
                "categories": sorted(categories.values(),
                                     key=lambda c: c["category"].complete_name or ""),
                "quantity": totals["quantity"],
                "second": totals["second"],
                "scrap": totals["scrap"],
                "orders": len(orders.filtered(lambda m: m.company_id == company)),
            })
        return result


    @api.model
    def _mo_output(self, mo):
        """Split what an order produced into 1-sort / 2-sort / brak, in the
        product's unit. Brak and 2-sort pieces are produced first and then
        scrapped off the order, so they must come out of the good quantity."""
        uom = mo.product_id.uom_id
        produced = mo.product_uom_id._compute_quantity(mo.qty_produced or mo.product_qty, uom)
        second_tag = self.env.ref("cst_kerama_shift.scrap_reason_second_grade", raise_if_not_found=False)
        second = scrap = 0.0
        for sc in mo.scrap_ids.filtered(lambda s: s.state == "done" and s.product_id == mo.product_id):
            qty = sc.product_uom_id._compute_quantity(sc.scrap_qty, uom)
            if second_tag and second_tag in sc.scrap_reason_tag_ids:
                second += qty
            else:
                scrap += qty
        return {"quantity": max(produced - second - scrap, 0.0), "second": second, "scrap": scrap}


class CstAssetReport(models.AbstractModel):
    """«Asosiy vositalar qoldiq summalari bilan» — the register: cost,
    depreciation so far, book value, plus where each asset stands."""

    _name = "cst.asset.report"
    _description = "Asosiy vositalar"

    @api.model
    def build(self, company_ids=None, include_closed=False):
        companies = self.env.companies
        if company_ids:
            companies = companies.filtered(lambda c: c.id in company_ids) or companies
        states = ["open", "paused"] + (["close"] if include_closed else [])
        assets = self.env["account.asset"].sudo().search(
            [("company_id", "in", companies.ids), ("state", "in", states),
             ("parent_id", "=", False)], order="acquisition_date, id")
        result = []
        for company in companies:
            rows = []
            for asset in assets.filtered(lambda a: a.company_id == company):
                depreciated = (asset.original_value or 0.0) - (asset.book_value or 0.0)
                rows.append({
                    "asset": asset,
                    "inventory_no": asset.cst_inventory_no or "",
                    "manufacture_date": asset.cst_manufacture_date,
                    "acquisition_date": asset.acquisition_date,
                    "location": asset.cst_location or "",
                    "value": asset.original_value or 0.0,
                    "depreciated": depreciated,
                    "book_value": asset.book_value or 0.0,
                    "state": asset.state,
                })
            if not rows:
                continue
            result.append({
                "company": company, "currency": company.currency_id, "rows": rows,
                "value": sum(r["value"] for r in rows),
                "depreciated": sum(r["depreciated"] for r in rows),
                "book_value": sum(r["book_value"] for r in rows),
            })
        return result


class CstTaxReport(models.AbstractModel):
    """«Soliqlar harakati» and «Soliq akt sverkasi» — the running account of
    the tax accounts, the same arithmetic as a counterparty's card: a credit
    balance is what we owe (*qarzimiz*), a debit balance is ours (*haqqimiz*);
    credits in the period are what was assessed (*hisoblandi*), debits what
    was paid (*to'landi*).
    """

    _name = "cst.tax.report"
    _description = "Soliqlar"

    TAX_WORDS = ("tax", "vat", "soliq", "солиқ", "солик", "qqs", "ққс", "ндс", "налог", "inps",
                 "инпс", "pensiya", "пенси", "ijtimoiy", "ижтимоий", "budget", "бюджет", "duties")

    @api.model
    def default_accounts(self, companies):
        """Every account that carries a tax.

        Three sources, because the three companies do not share a chart: the
        accounts the tax definitions post to (archived taxes included — this
        company keeps its VAT taxes switched off), the accounts of the payroll
        tax components, and every balance-sheet account whose code sits in the
        Uzbek 64xx/65xx range or whose name says tax in any of the languages
        the charts are written in.
        """
        Account = self.env["account.account"].sudo()
        accounts = self.env["account.tax"].sudo().with_context(active_test=False).search(
            [("company_id", "in", companies.ids)]).mapped("repartition_line_ids.account_id")
        if "cst.payroll.component" in self.env:
            for component in self.env["cst.payroll.component"].sudo().search(
                    [("computation", "like", "tax_%")]):
                for company in companies:
                    comp = component.with_company(company)
                    accounts |= comp.account_debit_id | comp.account_credit_id
        for company in companies:
            for account in Account.with_company(company).search(
                    [("company_ids", "in", company.id),
                     ("account_type", "in", ("liability_current", "liability_payable",
                                             "asset_current", "asset_receivable"))]):
                code = account.with_company(company).code or ""
                names = " ".join(str(v) for v in (account.name,
                                                  *(account.with_context(lang=l).name for l in ("en_US", "uz_UZ", "ru_RU")))
                                 if v).lower()
                if code.startswith(TAX_CODE_PREFIXES) or any(w in names for w in self.TAX_WORDS):
                    accounts |= account
        return accounts.filtered(lambda a: a.account_type not in ("expense", "income"))

    @api.model
    def _lines(self, accounts, companies, extra):
        return self.env["account.move.line"].sudo().search(
            [("parent_state", "=", "posted"), ("company_id", "in", companies.ids),
             ("account_id", "in", accounts.ids)] + extra, order="date, id")

    @api.model
    def movement(self, date_from, date_to, account_ids=None, company_ids=None):
        companies = self.env.companies
        if company_ids:
            companies = companies.filtered(lambda c: c.id in company_ids) or companies
        accounts = self.env["account.account"].browse(account_ids) if account_ids \
            else self.default_accounts(companies)
        result = []
        for company in companies:
            opening = defaultdict(float)
            for line in self._lines(accounts, company, [("date", "<", date_from)]):
                opening[line.account_id.id] += line.balance or 0.0
            assessed, paid = defaultdict(float), defaultdict(float)
            for line in self._lines(accounts, company,
                                    [("date", ">=", date_from), ("date", "<=", date_to)]):
                if (line.balance or 0.0) < 0:
                    assessed[line.account_id.id] += -line.balance
                else:
                    paid[line.account_id.id] += line.balance
            rows = []
            for account in accounts.sorted(lambda a: a.with_company(company).code or ""):
                opened = opening.get(account.id, 0.0)
                acc, pay = assessed.get(account.id, 0.0), paid.get(account.id, 0.0)
                closed = opened - acc + pay
                if not any((opened, acc, pay, closed)):
                    continue
                rows.append({
                    "account": account, "code": account.with_company(company).code,
                    "open_we_owe": -opened if opened < 0 else 0.0,
                    "open_they_owe": opened if opened > 0 else 0.0,
                    "assessed": acc, "paid": pay,
                    "close_we_owe": -closed if closed < 0 else 0.0,
                    "close_they_owe": closed if closed > 0 else 0.0,
                })
            if rows:
                result.append({"company": company, "currency": company.currency_id, "rows": rows,
                               "totals": {k: sum(r[k] for r in rows) for k in
                                          ("open_we_owe", "open_they_owe", "assessed", "paid",
                                           "close_we_owe", "close_they_owe")}})
        return result

    @api.model
    def statement(self, account, date_from, date_to, company_ids=None):
        companies = self.env.companies
        if company_ids:
            companies = companies.filtered(lambda c: c.id in company_ids) or companies
        result = []
        for company in companies:
            opening = sum(self._lines(account, company, [("date", "<", date_from)]).mapped("balance"))
            balance = opening
            rows = []
            assessed = paid = 0.0
            for line in self._lines(account, company, [("date", ">=", date_from), ("date", "<=", date_to)]):
                amount = line.balance or 0.0
                balance += amount
                if amount < 0:
                    assessed += -amount
                else:
                    paid += amount
                move = line.move_id
                label = " : ".join(p for p in (
                    ("№ %s" % move.name) if move.name and move.name != "/" else "",
                    line.name or move.ref or "") if p)
                rows.append({
                    "line": line, "date": line.date, "label": label,
                    "assessed": -amount if amount < 0 else 0.0,
                    "paid": amount if amount > 0 else 0.0,
                    "we_owe": -balance if balance < 0 else 0.0,
                    "they_owe": balance if balance > 0 else 0.0,
                })
            if not rows and not opening:
                continue
            result.append({
                "company": company, "currency": company.currency_id,
                "code": account.with_company(company).code,
                "open_we_owe": -opening if opening < 0 else 0.0,
                "open_they_owe": opening if opening > 0 else 0.0,
                "assessed": assessed, "paid": paid,
                "close_we_owe": -balance if balance < 0 else 0.0,
                "close_they_owe": balance if balance > 0 else 0.0,
                "rows": rows,
            })
        return result


class CstCardPaymentsReport(models.AbstractModel):
    """«Xodimlar plastik kartasiga tashlangan pullar» — every transfer to a
    staff card in the period: who, how much, for which month, advance or wage."""

    _name = "cst.card.payments.report"
    _description = "Plastik kartaga o'tkazmalar"

    @api.model
    def default_components(self):
        Component = self.env["cst.payroll.component"].sudo()
        return Component.search([("kind", "=", "deduction")]).filtered(
            lambda c: any(k in (c.code or "").upper() for k in ("PLASTIK", "KARTA", "CARD")))

    @api.model
    def build(self, date_from, date_to, component_ids=None, employee_ids=None,
              company_ids=None, include_draft=False):
        companies = self.env.companies
        if company_ids:
            companies = companies.filtered(lambda c: c.id in company_ids) or companies
        components = self.env["cst.payroll.component"].browse(component_ids) if component_ids \
            else self.default_components()
        domain = [("company_id", "in", companies.ids), ("component_id", "in", components.ids),
                  ("state", "in", ("confirmed", "posted") + (("draft",) if include_draft else ())),
                  ("date", ">=", date_from), ("date", "<=", date_to)]
        if employee_ids:
            domain.append(("employee_id", "in", employee_ids))
        lines = self.env["cst.payroll.line"].sudo().search(domain, order="date, employee_id, id")
        rows = []
        for line in lines:
            month = line.period_id.name if line.period_id else line.date.strftime("%m.%Y")
            code = (line.component_id.code or "").upper()
            kind = "Avans" if "AVANS" in code else ("Oylik" if "OYLIK" in code else line.component_id.name)
            rows.append({"line": line, "date": line.date, "employee": line.employee_id,
                         "amount": line.amount, "month": month, "kind": kind,
                         "note": line.name if line.name != line.component_id.name else (line.note or "")})
        per_employee = defaultdict(float)
        for r in rows:
            per_employee[r["employee"]] += r["amount"]
        return {"rows": rows, "total": sum(r["amount"] for r in rows),
                "currency": companies[:1].currency_id,
                "by_employee": sorted(({"employee": e, "amount": a} for e, a in per_employee.items()),
                                      key=lambda r: -r["amount"])}


class CstBankFeeReport(models.AbstractModel):
    """«Bank xarajatlari» — what the banks charged us.

    A bank fee is an expense booked inside a bank journal: the commission line
    of a transfer, a monthly service charge, a card acquiring fee. Every such
    line is listed under its journal, month by month, next to the money that
    passed through the account in the same month, so the fee can be read as
    a share of the turnover — the number the director actually asks for.
    """

    _name = "cst.bank.fee.report"
    _description = "Bank xarajatlari"

    @api.model
    def build(self, date_from, date_to, journal_ids=None, company_ids=None):
        companies = self.env.companies
        if company_ids:
            companies = companies.filtered(lambda c: c.id in company_ids) or companies
        Journal = self.env["account.journal"].sudo()
        jdomain = [("type", "=", "bank"), ("company_id", "in", companies.ids)]
        if journal_ids:
            jdomain.append(("id", "in", journal_ids))
        journals = Journal.search(jdomain, order="company_id, sequence, id")
        Line = self.env["account.move.line"].sudo()
        result = []
        for company in companies:
            blocks = []
            for journal in journals.filtered(lambda j: j.company_id == company):
                fees = Line.search([
                    ("parent_state", "=", "posted"), ("journal_id", "=", journal.id),
                    ("account_id.account_type", "in", ("expense", "expense_depreciation", "expense_direct_cost")),
                    ("date", ">=", date_from), ("date", "<=", date_to)], order="date, id")
                turnover = Line.search_read([
                    ("parent_state", "=", "posted"), ("account_id", "=", journal.default_account_id.id),
                    ("date", ">=", date_from), ("date", "<=", date_to)], ["date", "balance"])
                months = {}
                for row in turnover:
                    m = months.setdefault(row["date"].strftime("%Y-%m"), {"key": row["date"].strftime("%Y-%m"),
                                          "label": row["date"].strftime("%m.%Y"), "fees": 0.0, "inflow": 0.0,
                                          "outflow": 0.0, "rows": []})
                    if row["balance"] > 0:
                        m["inflow"] += row["balance"]
                    else:
                        m["outflow"] += -row["balance"]
                for line in fees:
                    key = line.date.strftime("%Y-%m")
                    m = months.setdefault(key, {"key": key, "label": line.date.strftime("%m.%Y"),
                                                "fees": 0.0, "inflow": 0.0, "outflow": 0.0, "rows": []})
                    m["fees"] += line.balance or 0.0
                    m["rows"].append({
                        "line": line, "date": line.date,
                        "label": " · ".join(p for p in (
                            line.move_id.name if line.move_id.name != "/" else "",
                            line.partner_id.display_name or "", line.name or line.move_id.ref or "") if p),
                        "account": "%s %s" % (line.account_id.with_company(company).code or "", line.account_id.name),
                        "amount": line.balance or 0.0,
                    })
                months = [m for m in sorted(months.values(), key=lambda m: m["key"]) if m["fees"] or m["rows"]]
                if not months:
                    continue
                total_fees = sum(m["fees"] for m in months)
                total_turn = sum(m["inflow"] + m["outflow"] for m in months)
                blocks.append({"journal": journal, "months": months, "fees": total_fees,
                               "inflow": sum(m["inflow"] for m in months),
                               "outflow": sum(m["outflow"] for m in months),
                               "share": (total_fees / total_turn * 100.0) if total_turn else 0.0})
            if blocks:
                result.append({"company": company, "currency": company.currency_id, "journals": blocks,
                               "fees": sum(b["fees"] for b in blocks)})
        return result
