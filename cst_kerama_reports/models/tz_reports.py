from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models


class CstPurchasedGoodsReport(models.AbstractModel):
    """«Sotib olingan mahsulot va xom ashyo» (ТЗ hisobot 16): what was bought in
    the period, how much, at what price, and what it cost with the landed
    costs (transport, customs …) spread onto it.

    Read from the done receipts of purchase orders — goods count when they
    arrive, the order price is the price, in company money at the receipt's
    date. Returns to the supplier subtract. Landed costs are the validated
    adjustment lines that point at those very receipt moves.
    """

    _name = "cst.purchased.goods.report"
    _description = "Sotib olingan mahsulotlar"
    _inherit = "cst.stock.report.base"

    @api.model
    def build(self, date_from, date_to, partner_ids=None, category_ids=None, company_ids=None,
              by_supplier=False):
        companies = self._companies(company_ids)
        domain = [("state", "=", "done"), ("purchase_line_id", "!=", False),
                  ("company_id", "in", companies.ids)] + self._period(date_from, date_to)
        if partner_ids:
            domain.append(("purchase_line_id.order_id.partner_id.commercial_partner_id", "in", partner_ids))
        if category_ids:
            categories = self.env["product.category"].search([("id", "child_of", category_ids)])
            domain.append(("product_id.categ_id", "in", categories.ids))
        moves = self.env["stock.move"].sudo().search(domain, order="date, id")
        landed = defaultdict(float)
        if "stock.valuation.adjustment.lines" in self.env and moves:
            for adj in self.env["stock.valuation.adjustment.lines"].sudo().search([
                    ("move_id", "in", moves.ids), ("cost_id.state", "=", "done")]):
                landed[adj.move_id.id] += adj.additional_landed_cost

        cells = {}
        for move in moves:
            if move.location_dest_id.usage == "internal" and move.location_id.usage != "internal":
                sign = 1
            elif move.location_id.usage == "internal" and move.location_dest_id.usage == "supplier":
                sign = -1
            else:
                continue
            product = move.product_id
            qty = move.product_uom._compute_quantity(move.quantity, product.uom_id) * sign
            po_line = move.purchase_line_id
            unit = self._unit_price(po_line, move)
            partner = po_line.order_id.partner_id.commercial_partner_id
            key = (move.company_id.id, partner.id if by_supplier else 0, product.id)
            cell = cells.setdefault(key, {"qty": 0.0, "amount": 0.0, "landed": 0.0, "docs": set(),
                                          "product": product, "partner": partner, "company": move.company_id})
            cell["qty"] += qty
            cell["amount"] += qty * unit
            cell["landed"] += landed.get(move.id, 0.0) * sign
            cell["docs"].add(move.picking_id.id or move.id)

        result = []
        for company in companies:
            groups = {}
            for (company_id, partner_id, _pid), cell in cells.items():
                if company_id != company.id:
                    continue
                product = cell["product"]
                if by_supplier:
                    gkey, glabel = partner_id, cell["partner"].display_name or _("Ta'minotchisiz")
                else:
                    root, _leaf = self._root_and_leaf(product)
                    gkey, glabel = root.id, self.env["cst.warehouse.report"].category_label(root)
                group = groups.setdefault(gkey, {"label": glabel, "rows": []})
                total = cell["amount"] + cell["landed"]
                group["rows"].append({
                    "product": product,
                    "label": self.env["cst.warehouse.report"].product_label(product),
                    "characteristic": self._characteristic(product),
                    "uom": product.uom_id.name,
                    "qty": cell["qty"],
                    "price": cell["amount"] / cell["qty"] if cell["qty"] else 0.0,
                    "amount": cell["amount"],
                    "landed": cell["landed"],
                    "total": total,
                    "unit_cost": total / cell["qty"] if cell["qty"] else 0.0,
                    "docs": len(cell["docs"]),
                })
            if not groups:
                continue
            for group in groups.values():
                group["rows"].sort(key=lambda r: r["label"] or "")
                group["totals"] = {k: sum(r[k] for r in group["rows"]) for k in ("qty", "amount", "landed", "total")}
            ordered = sorted(groups.values(), key=lambda g: g["label"] or "")
            result.append({
                "company": company, "currency": company.currency_id, "groups": ordered,
                "totals": {k: sum(g["totals"][k] for g in ordered) for k in ("qty", "amount", "landed", "total")},
            })
        return result

    @api.model
    def build_dated(self, date_from, date_to, partner_ids=None, category_ids=None, company_ids=None):
        """The supplier sheet of the client's own Excel: supplier → the
        currency it was bought in → every receipt line by date, at the order
        price in that currency; the landed costs and the unit cost in the same
        currency, and the supplier total in company money."""
        companies = self._companies(company_ids)
        domain = [("state", "=", "done"), ("purchase_line_id", "!=", False),
                  ("company_id", "in", companies.ids)] + self._period(date_from, date_to)
        if partner_ids:
            domain.append(("purchase_line_id.order_id.partner_id.commercial_partner_id", "in", partner_ids))
        if category_ids:
            categories = self.env["product.category"].search([("id", "child_of", category_ids)])
            domain.append(("product_id.categ_id", "in", categories.ids))
        moves = self.env["stock.move"].sudo().search(domain, order="date, id")
        landed = defaultdict(float)
        if "stock.valuation.adjustment.lines" in self.env and moves:
            for adj in self.env["stock.valuation.adjustment.lines"].sudo().search([
                    ("move_id", "in", moves.ids), ("cost_id.state", "=", "done")]):
                landed[adj.move_id.id] += adj.additional_landed_cost
        tz = pytz.timezone(self.env.context.get("tz") or self.env.user.tz or "Asia/Tashkent")

        result = []
        for company in companies:
            company_ccy = company.currency_id
            suppliers = {}
            for move in moves.filtered(lambda m: m.company_id == company):
                if move.location_dest_id.usage == "internal" and move.location_id.usage != "internal":
                    sign = 1
                elif move.location_id.usage == "internal" and move.location_dest_id.usage == "supplier":
                    sign = -1
                else:
                    continue
                product = move.product_id
                po_line = move.purchase_line_id
                order = po_line.order_id
                ccy = order.currency_id or company_ccy
                day = pytz.utc.localize(move.date).astimezone(tz).date()
                qty = move.product_uom._compute_quantity(move.quantity, product.uom_id) * sign
                price = po_line.price_subtotal / po_line.product_qty if po_line.product_qty else po_line.price_unit
                price /= po_line.product_uom_id._compute_quantity(1.0, product.uom_id) or 1.0
                amount = qty * price
                amount_company = ccy._convert(amount, company_ccy, company, day, round=False) \
                    if ccy != company_ccy else amount
                landed_company = landed.get(move.id, 0.0) * sign
                landed_ccy = company_ccy._convert(landed_company, ccy, company, day, round=False) \
                    if ccy != company_ccy else landed_company
                partner = order.partner_id.commercial_partner_id
                supplier = suppliers.setdefault(partner.id, {
                    "partner": partner, "label": partner.display_name or _("Ta'minotchisiz"),
                    "currencies": {}, "total_company": 0.0})
                block = supplier["currencies"].setdefault(ccy.id, {"currency": ccy, "rows": []})
                total = amount + landed_ccy
                block["rows"].append({
                    "date": day,
                    "label": self.env["cst.warehouse.report"].product_label(product),
                    "characteristic": self._characteristic(product),
                    "uom": product.uom_id.name,
                    "qty": qty,
                    "price": price,
                    "amount": amount,
                    "landed": landed_ccy,
                    "total": total,
                    "unit_cost": total / qty if qty else 0.0,
                    "unit_cost_company": (amount_company + landed_company) / qty if qty else 0.0,
                    "doc": move.picking_id.name or order.name,
                })
                supplier["total_company"] += amount_company + landed_company
            if not suppliers:
                continue
            ordered = sorted(suppliers.values(), key=lambda g: g["label"] or "")
            for supplier in ordered:
                blocks = sorted(supplier["currencies"].values(), key=lambda b: b["currency"] != company_ccy)
                for block in blocks:
                    block["totals"] = {k: sum(r[k] for r in block["rows"]) for k in ("qty", "amount", "landed", "total")}
                supplier["currencies"] = blocks
            result.append({"company": company, "currency": company_ccy, "suppliers": ordered,
                           "total_company": sum(g["total_company"] for g in ordered)})
        return result

    @api.model
    def _unit_price(self, po_line, move):
        """Order price (no tax, after discount) per product unit, company money,
        at the receipt's date."""
        order = po_line.order_id
        price = po_line.price_subtotal / po_line.product_qty if po_line.product_qty else po_line.price_unit
        qty_in_product_uom = po_line.product_uom_id._compute_quantity(1.0, po_line.product_id.uom_id) or 1.0
        price = price / qty_in_product_uom
        if order.currency_id != move.company_id.currency_id:
            price = order.currency_id._convert(price, move.company_id.currency_id, move.company_id,
                                               fields.Date.to_date(move.date), round=False)
        return price


class CstEmployeesAtWorkReport(models.AbstractModel):
    """«Ishlayotgan xodimlar» (ТЗ hisobot 17): the active staff by company and
    department — position, табель №, hired on, phone, pay scheme — and for the
    chosen day whether they came (Face ID check-in) and when."""

    _name = "cst.employees.report"
    _description = "Ishlayotgan xodimlar"

    @api.model
    def build(self, day=None, company_ids=None, department_ids=None, presence="all"):
        day = fields.Date.to_date(day) or fields.Date.context_today(self)
        companies = self.env.companies
        if company_ids:
            companies = companies.filtered(lambda c: c.id in company_ids) or companies
        Employee = self.env["hr.employee"].sudo()
        domain = [("company_id", "in", companies.ids)]
        if department_ids:
            domain.append(("department_id", "child_of", department_ids))
        employees = Employee.search(domain)
        tz = pytz.timezone(self.env.user.tz or "Asia/Tashkent")
        start = tz.localize(datetime.combine(day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        end = start + timedelta(days=1)
        attendance = defaultdict(list)
        for att in self.env["hr.attendance"].sudo().search([
                ("employee_id", "in", employees.ids), ("check_in", ">=", start), ("check_in", "<", end)],
                order="check_in"):
            attendance[att.employee_id.id].append(att)
        show_pay = self.env.user.has_group("cst_kerama_payroll.group_payroll_user") \
            or self.env.user.has_group("hr.group_hr_user")
        schemes = dict(self.env["hr.version"]._fields["cst_salary_scheme"]._description_selection(self.env)) \
            if "cst_salary_scheme" in self.env["hr.version"]._fields else {}
        staff_labels = dict(Employee._fields["cst_staff_status"]._description_selection(self.env)) \
            if "cst_staff_status" in Employee._fields else {}

        def local(stamp):
            return pytz.utc.localize(stamp).astimezone(tz).strftime("%H:%M") if stamp else ""

        result = []
        for company in companies:
            groups = {}
            for employee in employees.filtered(lambda e: e.company_id == company):
                atts = attendance.get(employee.id, [])
                came = bool(atts)
                if presence == "present" and not came:
                    continue
                if presence == "absent" and came:
                    continue
                version = employee.version_id
                department = employee.department_id
                group = groups.setdefault(department.id, {
                    "label": department.complete_name if department else _("Bo'limsiz"), "rows": []})
                group["rows"].append({
                    "name": employee.name,
                    "job": employee.job_title or employee.job_id.name or "",
                    "number": employee.cst_personnel_no or "",
                    "staff": employee.cst_staff_status if staff_labels else False,
                    "staff_label": staff_labels.get(employee.cst_staff_status, "") if staff_labels else "",
                    "hired": version.contract_date_start,
                    "phone": employee.mobile_phone or employee.work_phone or "",
                    "scheme": schemes.get(version.cst_salary_scheme, "") if show_pay and schemes else "",
                    "wage": version.wage if show_pay else None,
                    "came": came,
                    "check_in": local(atts[0].check_in) if atts else "",
                    "check_out": local(atts[-1].check_out) if atts and atts[-1].check_out else "",
                    "hours": sum(a.worked_hours or 0.0 for a in atts),
                })
            if not groups:
                continue
            ordered = sorted(groups.values(), key=lambda g: g["label"])
            for group in ordered:
                group["rows"].sort(key=lambda r: r["name"] or "")
                group["present"] = sum(1 for r in group["rows"] if r["came"])
            rows = [r for g in ordered for r in g["rows"]]
            result.append({"company": company, "groups": ordered, "count": len(rows),
                           "present": sum(1 for r in rows if r["came"]),
                           "staff": sum(1 for r in rows if r["staff"] == "staff"),
                           "non_staff": sum(1 for r in rows if r["staff"] == "non_staff"),
                           "unset": sum(1 for r in rows if not r["staff"])})
        totals = {k: sum(c[k] for c in result) for k in ("count", "present", "staff", "non_staff", "unset")}
        return {"day": day, "companies": result, "show_pay": show_pay, "totals": totals}


class CstReportsSetup(models.AbstractModel):
    """One-off settings the reports need, re-applied on every upgrade."""

    _name = "cst.reports.setup"
    _description = "Xisobotlar sozlamasi"

    @api.model
    def _fix_uz_report_variants(self):
        """Khatdecor keeps its books on the generic chart but its fiscal country is
        Uzbekistan, so Odoo picked the Uzbek P&L and Balance Sheet variants for it
        — which read Uzbek account codes and printed zeros. The Uzbek variants
        are kept for the companies that really use the Uzbek chart; everybody
        else gets Odoo's generic P&L / Balance Sheet. Display only: no entry changes."""
        for xmlid in ("l10n_uz_reports.balance_sheet_l10n_uz", "l10n_uz_reports.account_financial_report_l10n_uz_pl"):
            report = self.env.ref(xmlid, raise_if_not_found=False)
            if report and report.availability_condition != "coa":
                report.sudo().write({"availability_condition": "coa", "chart_template": "uz"})
