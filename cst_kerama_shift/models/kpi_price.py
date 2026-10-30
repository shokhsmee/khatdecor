from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CstShiftKpiPrice(models.Model):
    """«KPI narxi» -- what one worker earns for a shift whose plan is met 100%.

    The shift's KPI is this price × how much of the plan the worker did
    (319 done of a 233.33 share = 136.71 % → 30 000 × 1.3671 = 41 014.29).
    Dated: a new price is a new row from its date on, so a shift keeps the
    price of its own day. Per department -- a worker may stand in two.
    """

    _name = "cst.shift.kpi.price"
    _description = "Xodim KPI narxi"
    _order = "department_id, employee_name, date_from desc, id desc"

    department_id = fields.Many2one("cst.production.department", string="Bo'lim", required=True, index=True,
                                    ondelete="cascade")
    employee_id = fields.Many2one("hr.employee", string="Xodim", required=True, index=True, ondelete="cascade")
    # stored: the shift admin reads the list without access to employee records
    employee_name = fields.Char(string="Xodim ismi", compute="_compute_employee_name", store=True, compute_sudo=True)
    amount = fields.Monetary(string="KPI narxi (reja 100%)", currency_field="currency_id", required=True)
    company_id = fields.Many2one(related="department_id.company_id", store=True)
    currency_id = fields.Many2one(related="company_id.cst_payroll_currency_id")
    date_from = fields.Date(string="Amal qilish boshi", required=True, default=fields.Date.context_today)
    note = fields.Char(string="Izoh")

    _price_uniq = models.Constraint(
        "unique(department_id, employee_id, date_from)", "Bir kunda xodimga bitta narx bo'ladi.")

    @api.depends("employee_id")
    def _compute_employee_name(self):
        for price in self:
            price.employee_name = price.employee_id.name

    @api.constrains("amount")
    def _check_amount(self):
        if any(price.amount < 0 for price in self):
            raise ValidationError(_("KPI narxi manfiy bo'lmaydi."))

    @api.model
    def _prices_for(self, employees, department, day):
        """{employee id: price in force on ``day``}: the department's own price,
        else the latest price the worker has in any department."""
        if not employees or not day:
            return {}
        rows = self.sudo().search([("employee_id", "in", employees.ids), ("date_from", "<=", day)],
                                  order="date_from desc, id desc")
        own, other = {}, {}
        for row in rows:
            target = own if row.department_id == department else other
            target.setdefault(row.employee_id.id, row.amount)
        return {e.id: own.get(e.id, other.get(e.id, 0.0)) for e in employees}

    # ------------------------------------------------------------------ the «KPI narxlari» screen
    def _check_can_edit(self):
        if not self.env["cst.production.shift.worker"]._can_edit_kpi():
            raise UserError(_("KPI narxlarini faqat HR o'zgartiradi."))

    @api.model
    def kpi_price_board(self):
        """Every department of the current company with its people: the
        department's own staff and anyone who has a price there, each with
        the price in force today."""
        company = self.env.company
        today = fields.Date.context_today(self)
        Price = self.sudo()
        departments = self.env["cst.production.department"].sudo().search([("company_id", "=", company.id)])
        result = []
        for department in departments:
            prices = Price.search([("department_id", "=", department.id)], order="date_from desc, id desc")
            current, counts = {}, {}
            for price in prices:
                counts[price.employee_id.id] = counts.get(price.employee_id.id, 0) + 1
                if price.date_from <= today:
                    current.setdefault(price.employee_id.id, price)
            # a price set from a later date shows until it is in force
            for price in prices:
                current.setdefault(price.employee_id.id, price)
            people = department.employee_ids | prices.employee_id
            rows = []
            for employee in people.sorted(lambda e: (e.name or "").lower()):
                price = current.get(employee.id)
                rows.append({
                    "employee_id": employee.id,
                    "name": employee.name,
                    "amount": price.amount if price else 0.0,
                    "date_from": fields.Date.to_string(price.date_from) if price else False,
                    "history": counts.get(employee.id, 0),
                    "staff": employee in department.employee_ids,
                })
            result.append({"id": department.id, "name": department.name, "rows": rows})
        currency = company.cst_payroll_currency_id or company.currency_id
        return {
            "company": company.name,
            "currency": currency.name,
            "today": fields.Date.to_string(today),
            "month_start": fields.Date.to_string(today.replace(day=1)),
            "can_edit": self.env["cst.production.shift.worker"]._can_edit_kpi(),
            "departments": result,
        }

    @api.model
    def kpi_price_save(self, department_id, rows):
        """``rows``: [{employee_id, amount, date_from}] -- only the changed ones.
        A price from a new date opens a new row; the same date corrects it."""
        self._check_can_edit()
        department = self.env["cst.production.department"].browse(department_id).exists()
        if not department:
            raise UserError(_("Bo'lim topilmadi."))
        Price = self.sudo()
        for row in rows:
            amount = float(row.get("amount") or 0.0)
            day = fields.Date.to_date(row.get("date_from")) or fields.Date.context_today(self)
            employee = self.env["hr.employee"].sudo().browse(int(row["employee_id"])).exists()
            if not employee:
                continue
            same_day = Price.search([("department_id", "=", department.id), ("employee_id", "=", employee.id),
                                     ("date_from", "=", day)], limit=1)
            if same_day:
                same_day.amount = amount
            else:
                Price.create({"department_id": department.id, "employee_id": employee.id,
                              "amount": amount, "date_from": day})
        return self.kpi_price_board()

    @api.model
    def kpi_price_history(self, department_id, employee_id):
        prices = self.sudo().search([("department_id", "=", department_id), ("employee_id", "=", employee_id)],
                                    order="date_from desc, id desc")
        return [{
            "id": price.id,
            "date_from": fields.Date.to_string(price.date_from),
            "amount": price.amount,
            "user": price.write_uid.name or "",
            "note": price.note or "",
        } for price in prices]

    @api.model
    def kpi_price_delete(self, price_id):
        self._check_can_edit()
        self.sudo().browse(price_id).exists().unlink()
        return True

    @api.model
    def kpi_price_employees(self, department_id, query, exclude_ids=None):
        """People to add to a department's price list: search by name."""
        domain = [("company_id", "in", [False, self.env.company.id])]
        if query:
            domain.append(("name", "ilike", query))
        if exclude_ids:
            domain.append(("id", "not in", exclude_ids))
        employees = self.env["hr.employee"].sudo().search(domain, limit=12, order="name")
        return [{"id": e.id, "name": e.name} for e in employees]
