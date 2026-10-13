from odoo import api, fields, models

# States that count as real money owed.  Draft lines are a proposal until the
# period is confirmed, so they are opt-in.
SETTLED_STATES = ("confirmed", "posted")


class CstPayrollReport(models.AbstractModel):
    """Data provider for «Ходимларга хисобланган иш хаки, бонуслар, жарималар
    ва берилган пуллар буйича хисобот».

    A running account per employee over an arbitrary date range::

        Охирги колдик = Бошлангич колдик + Жами хисобланди - Жами ушланди

    The columns are the *components*, read from the database, so adding a bonus
    type widens the report without touching this file or the OWL template.
    """

    _name = "cst.payroll.report"
    _description = "Payroll Running Account Report"

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------
    @api.model
    def _states(self, filters):
        if filters.get("include_draft"):
            return SETTLED_STATES + ("draft",)
        return SETTLED_STATES

    @api.model
    def _company_ids(self, filters):
        allowed = self.env.companies.ids
        wanted = [cid for cid in (filters.get("company_ids") or []) if cid in allowed]
        return wanted or allowed

    @api.model
    def _dates(self, filters):
        date_from = fields.Date.to_date(filters.get("date_from")) \
            or fields.Date.start_of(fields.Date.context_today(self), "month")
        date_to = fields.Date.to_date(filters.get("date_to")) \
            or fields.Date.context_today(self)
        if date_to < date_from:
            date_from, date_to = date_to, date_from
        return date_from, date_to

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @api.model
    def get_report_data(self, filters=None):
        """Everything the dashboard draws, in one call."""
        filters = filters or {}
        date_from, date_to = self._dates(filters)
        company_ids = self._company_ids(filters)
        states = self._states(filters)

        components = self.env["cst.payroll.component"].search([])
        accruals = components.filtered(lambda c: c.kind == "accrual")
        deductions = components.filtered(lambda c: c.kind == "deduction")

        openings = self._openings(company_ids, date_from, states)
        movements = self._movements(company_ids, date_from, date_to, states)
        employees = self._employees(company_ids, set(openings) | set(movements))

        companies = []
        for company in self.env["res.company"].browse(company_ids):
            rows = []
            for employee in employees.filtered(lambda e: e.company_id == company):
                rows.append(self._employee_row(
                    employee, openings, movements, accruals, deductions))
            rows = [row for row in rows if not filters.get("hide_empty") or row["has_data"]]
            if not rows and filters.get("hide_empty"):
                continue
            companies.append({
                "id": company.id,
                "name": company.display_name,
                "currency": company.currency_id.name,
                "rows": rows,
                "totals": self._sum_rows(rows, accruals, deductions),
            })

        return {
            "date_from": fields.Date.to_string(date_from),
            "date_to": fields.Date.to_string(date_to),
            "include_draft": bool(filters.get("include_draft")),
            "columns": {
                "accruals": [self._column(c) for c in accruals],
                "deductions": [self._column(c) for c in deductions],
            },
            "companies": companies,
            "totals": self._sum_rows(
                [row for company in companies for row in company["rows"]],
                accruals, deductions),
        }

    @api.model
    def _column(self, component):
        return {
            "id": component.id,
            "code": component.code,
            "name": component.name,
        }

    # ------------------------------------------------------------------
    # Figures
    # ------------------------------------------------------------------
    @api.model
    def _openings(self, company_ids, date_from, states):
        """{employee id: balance carried into the period}."""
        groups = self.env["cst.payroll.line"]._read_group(
            [
                ("company_id", "in", company_ids),
                ("state", "in", states),
                ("date", "<", date_from),
            ],
            groupby=["employee_id"],
            aggregates=["signed_amount:sum"],
        )
        return {employee.id: total for employee, total in groups}

    @api.model
    def _movements(self, company_ids, date_from, date_to, states):
        """{employee id: {component id: amount}} inside the period."""
        groups = self.env["cst.payroll.line"]._read_group(
            [
                ("company_id", "in", company_ids),
                ("state", "in", states),
                ("date", ">=", date_from),
                ("date", "<=", date_to),
            ],
            groupby=["employee_id", "component_id"],
            aggregates=["amount:sum"],
        )
        movements = {}
        for employee, component, total in groups:
            movements.setdefault(employee.id, {})[component.id] = total
        return movements

    @api.model
    def _employees(self, company_ids, with_figures):
        """Everyone the report should list.

        Every current employee, so the accountant reads the same row order as
        the workbook this replaces — plus anyone who has figures in the window
        even if they have since left.

        Read as superuser on purpose.  Odoo lets a non-HR user see only the
        fields of ``hr.employee.public``, and the табель раками is not one of
        them — but a payroll officer whose whole job is this report must be
        able to read it.  Nothing widens: ``company_ids`` is already clamped to
        the companies this user is allowed into.
        """
        Employee = self.env["hr.employee"].sudo()
        current = Employee.search([("company_id", "in", company_ids)])
        historic = Employee.with_context(active_test=False).browse(
            sorted(with_figures - set(current.ids))).exists()
        historic = historic.filtered(lambda e: e.company_id.id in company_ids)
        return (current | historic).sorted(lambda e: (e.name or "").lower())

    @api.model
    def _employee_row(self, employee, openings, movements, accruals, deductions):
        moves = movements.get(employee.id, {})
        opening = openings.get(employee.id, 0.0)

        accrued = {str(c.id): moves.get(c.id, 0.0) for c in accruals}
        deducted = {str(c.id): moves.get(c.id, 0.0) for c in deductions}
        accrued_total = sum(accrued.values())
        deducted_total = sum(deducted.values())
        return {
            "id": employee.id,
            "name": employee.display_name,
            "personnel_no": employee.cst_personnel_no or "",
            "active": employee.active,
            "opening": opening,
            "accruals": accrued,
            "accrued_total": accrued_total,
            "deductions": deducted,
            "deducted_total": deducted_total,
            "closing": opening + accrued_total - deducted_total,
            "has_data": bool(opening or accrued_total or deducted_total),
        }

    @api.model
    def _sum_rows(self, rows, accruals, deductions):
        totals = {
            "opening": sum(row["opening"] for row in rows),
            "accruals": {str(c.id): 0.0 for c in accruals},
            "deductions": {str(c.id): 0.0 for c in deductions},
            "accrued_total": 0.0,
            "deducted_total": 0.0,
            "closing": 0.0,
            "count": len(rows),
        }
        for row in rows:
            for key, value in row["accruals"].items():
                totals["accruals"][key] += value
            for key, value in row["deductions"].items():
                totals["deductions"][key] += value
            totals["accrued_total"] += row["accrued_total"]
            totals["deducted_total"] += row["deducted_total"]
            totals["closing"] += row["closing"]
        return totals

    # ------------------------------------------------------------------
    # Drill-down
    # ------------------------------------------------------------------
    @api.model
    def action_open_lines(self, filters, employee_id, component_id=None, opening=False):
        """The movements behind one cell.

        The whole point of the dashboard over the workbook: a number the
        accountant does not believe can be opened.
        """
        filters = filters or {}
        date_from, date_to = self._dates(filters)
        domain = [
            ("company_id", "in", self._company_ids(filters)),
            ("state", "in", self._states(filters)),
            ("employee_id", "=", employee_id),
        ]
        if opening:
            domain.append(("date", "<", fields.Date.to_string(date_from)))
        else:
            domain += [
                ("date", ">=", fields.Date.to_string(date_from)),
                ("date", "<=", fields.Date.to_string(date_to)),
            ]
        if component_id:
            domain.append(("component_id", "=", component_id))
        # Same reason as in _employees: the name is needed for the window
        # title, and the domain below is what actually limits what is shown.
        employee = self.env["hr.employee"].sudo().browse(employee_id)
        return {
            "type": "ir.actions.act_window",
            "name": employee.display_name,
            "res_model": "cst.payroll.line",
            "view_mode": "list,form",
            "views": [[False, "list"], [False, "form"]],
            "domain": domain,
            "context": {"search_default_g_component": 1},
        }
