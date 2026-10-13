from collections import defaultdict

from odoo import api, fields, models

SETTLED_STATES = ("confirmed", "posted")


class CstPayrollComponent(models.Model):
    _inherit = "cst.payroll.component"

    # Which components the bonus/penalty sheet lists. KPI and wage components
    # have reports of their own; advances are neither reward nor punishment.
    # Guessed from the code once (BON_* = bonus, JARIMA = penalty) and kept as
    # a stored, editable value, so a new bonus type is flagged on its form and
    # the payroll module's own noupdate records never have to be touched.
    cst_bonus_report = fields.Selection(
        [("bonus", "Bonus"), ("penalty", "Jarima")],
        string="Bonus/jarima hisobotida",
        compute="_compute_cst_bonus_report", store=True, readonly=False,
        precompute=True,
        help="Belgilangan komponent «Jarimalar va bonuslar» hisobotida "
             "ko'rsatiladi.")

    def init(self):
        """Fill the flag on components that predate it.

        A stored compute is only run when Odoo creates its column; a column
        that already exists (an upgrade that raced the field) stays NULL. Only
        empty flags are touched, so a value someone set by hand survives.
        """
        super().init()
        empty = self.search([("cst_bonus_report", "=", False)])
        if empty:
            empty._compute_cst_bonus_report()

    @api.depends("code", "computation", "kind")
    def _compute_cst_bonus_report(self):
        for component in self:
            code = (component.code or "").upper()
            if component.computation != "manual":
                component.cst_bonus_report = False
            elif code.startswith("BON_") or "BONUS" in code:
                component.cst_bonus_report = "bonus"
            elif code.startswith("JARIMA") or "PENALTY" in code:
                component.cst_bonus_report = "penalty"
            else:
                component.cst_bonus_report = component.cst_bonus_report or False


class CstPayrollReportBase(models.AbstractModel):
    """Shared filters of the payroll sheets built on ``cst.payroll.line``."""

    _name = "cst.payroll.report.base"
    _description = "Payroll report helpers"

    @api.model
    def _states(self, include_draft):
        return SETTLED_STATES + (("draft",) if include_draft else ())

    @api.model
    def _companies(self, company_ids=None):
        allowed = self.env.companies
        if company_ids:
            wanted = allowed.filtered(lambda c: c.id in company_ids)
            if wanted:
                return wanted
        return allowed

    @api.model
    def _line_label(self, line):
        parts = [line.component_id.name or ""]
        detail = line.name or line.note or ""
        if detail and detail != parts[0]:
            parts.append(detail)
        if line.source_ref:
            parts.append(line.source_ref)
        return ": ".join(p for p in parts if p)


class CstEmployeeCardReport(models.AbstractModel):
    """«Xodim oyligi bo'yicha (individual)» — the running card of one employee.

    Every settled payroll line of the period with the balance before and after
    it, the way the running-account sheet reads: accruals add to what the
    company owes the employee, deductions take from it, employer-only costs
    never touch the balance.
    """

    _name = "cst.employee.card.report"
    _description = "Xodim oyligi kartochkasi"
    _inherit = "cst.payroll.report.base"

    @api.model
    def build(self, employee, date_from, date_to, include_draft=False, company_ids=None):
        Line = self.env["cst.payroll.line"].sudo()
        companies = self._companies(company_ids)
        base = [
            ("employee_id", "=", employee.id),
            ("company_id", "in", companies.ids),
            ("state", "in", self._states(include_draft)),
            ("kind", "in", ("accrual", "deduction")),
        ]
        opening = sum(Line.search(base + [("date", "<", date_from)]).mapped("signed_amount"))
        lines = Line.search(base + [("date", ">=", date_from), ("date", "<=", date_to)],
                            order="date, id")
        rows, balance = [], opening
        accrued = deducted = 0.0
        for line in lines:
            before = balance
            balance += line.signed_amount
            if line.kind == "accrual":
                accrued += line.amount
            else:
                deducted += line.amount
            rows.append({
                "line": line,
                "date": line.date,
                "label": self._line_label(line),
                "before": before,
                "accrued": line.amount if line.kind == "accrual" else 0.0,
                "deducted": line.amount if line.kind == "deduction" else 0.0,
                "after": balance,
            })
        return {
            "employee": employee,
            "currency": companies[:1].currency_id,
            "opening": opening,
            "rows": rows,
            "accrued": accrued,
            "deducted": deducted,
            "closing": balance,
        }


class CstBonusPenaltyReport(models.AbstractModel):
    """«Jarimalar va bonuslar hisoboti» — who got what, and the totals by type."""

    _name = "cst.bonus.penalty.report"
    _description = "Jarimalar va bonuslar"
    _inherit = "cst.payroll.report.base"

    @api.model
    def build(self, date_from, date_to, employee_ids=None, company_ids=None,
              include_draft=False):
        Line = self.env["cst.payroll.line"].sudo()
        companies = self._companies(company_ids)
        domain = [
            ("company_id", "in", companies.ids),
            ("state", "in", self._states(include_draft)),
            ("component_id.cst_bonus_report", "!=", False),
            ("date", ">=", date_from), ("date", "<=", date_to),
        ]
        if employee_ids:
            domain.append(("employee_id", "in", employee_ids))
        lines = Line.search(domain, order="employee_id, date, id")

        per_employee, by_type = {}, defaultdict(float)
        for line in lines:
            # a penalty reads as a negative figure on the sheet
            signed = -line.amount if line.component_id.cst_bonus_report == "penalty" \
                else line.amount
            bucket = per_employee.setdefault(line.employee_id.id, {
                "employee": line.employee_id, "lines": [], "total": 0.0})
            bucket["lines"].append({
                "line": line,
                "topic": line.name or line.note or line.component_id.name,
                "type": line.component_id.name,
                "date": line.date,
                "amount": signed,
            })
            bucket["total"] += signed
            by_type[line.component_id] += signed
        employees = sorted(per_employee.values(),
                           key=lambda b: (b["employee"].name or "").lower())
        return {
            "currency": companies[:1].currency_id,
            "employees": employees,
            "by_type": sorted(
                ({"component": c, "amount": a} for c, a in by_type.items()),
                key=lambda r: (r["component"].cst_bonus_report, r["component"].name)),
            "total": sum(b["total"] for b in employees),
        }


class CstKpiReport(models.AbstractModel):
    """«KPI hisoboti» — manager ▸ category ▸ product: quantity, rate, amount."""

    _name = "cst.kpi.report"
    _description = "KPI hisoboti"
    _inherit = "cst.payroll.report.base"

    @api.model
    def build(self, date_from, date_to, computation="kpi_sales", employee_ids=None,
              company_ids=None, include_draft=False):
        Line = self.env["cst.payroll.line"].sudo()
        companies = self._companies(company_ids)
        domain = [
            ("company_id", "in", companies.ids),
            ("state", "in", self._states(include_draft)),
            ("component_id.computation", "=", computation),
            ("date", ">=", date_from), ("date", "<=", date_to),
        ]
        if employee_ids:
            domain.append(("employee_id", "in", employee_ids))
        lines = Line.search(domain, order="company_id, employee_id, id")
        characteristic = self.env["cst.warehouse.report"]._characteristic

        result = []
        for company in companies:
            employees = {}
            for line in lines.filtered(lambda l: l.company_id == company):
                emp = employees.setdefault(line.employee_id.id, {
                    "employee": line.employee_id, "categories": {}, "amount": 0.0})
                categ = line.product_categ_id or line.product_id.categ_id
                cat = emp["categories"].setdefault(categ.id, {
                    "category": categ, "products": {}, "quantity": 0.0, "amount": 0.0})
                key = (line.product_id.id, line.rate)
                prod = cat["products"].setdefault(key, {
                    "product": line.product_id,
                    "name": (self.env["cst.warehouse.report"].product_label(line.product_id) if line.product_id else (line.cst_operation_name or line.name)),
                    "characteristic": characteristic(line.product_id) if line.product_id else "",
                    "quantity": 0.0, "rate": line.rate, "amount": 0.0})
                prod["quantity"] += line.quantity
                prod["amount"] += line.amount
                cat["quantity"] += line.quantity
                cat["amount"] += line.amount
                emp["amount"] += line.amount
            if not employees:
                continue
            rows = []
            for emp in sorted(employees.values(), key=lambda e: (e["employee"].name or "").lower()):
                cats = []
                for cat in sorted(emp["categories"].values(),
                                  key=lambda c: c["category"].complete_name or ""):
                    cat["products"] = sorted(cat["products"].values(), key=lambda p: p["name"] or "")
                    cats.append(cat)
                emp["categories"] = cats
                rows.append(emp)
            result.append({
                "company": company,
                "employees": rows,
                "amount": sum(e["amount"] for e in rows),
            })
        return {"companies": result, "currency": companies[:1].currency_id}
