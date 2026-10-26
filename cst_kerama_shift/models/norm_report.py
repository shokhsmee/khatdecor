from collections import defaultdict

from odoo import api, fields, models


class CstDepartmentNormReport(models.AbstractModel):
    """«Bo'limlar: norma va brak» (ТЗ hisobot 43) — per department and period:
    what came out (1-sort, 2-sort, brak, material brak), the brak and 2-sort
    share against the department's norm, and the 1-sort output against the
    shift norm × the number of shifts worked."""

    _name = "cst.department.norm.report"
    _description = "Bo'limlar: norma va brak"

    @api.model
    def build(self, date_from, date_to, department_ids=None, by_shift=False):
        Department = self.env["cst.production.department"].sudo()
        departments = Department.browse(department_ids).exists() if department_ids else Department.search([])
        departments = departments.filtered(lambda d: d.company_id in self.env.companies)
        entries = self.env["cst.production.shift.entry"].sudo().search([
            ("department_id", "in", departments.ids),
            ("shift_date", ">=", date_from), ("shift_date", "<=", date_to)])
        per_dept = defaultdict(lambda: defaultdict(lambda: {"good": 0.0, "second": 0.0, "scrap": 0.0, "material": 0.0}))
        for entry in entries:
            cell = per_dept[entry.department_id.id][entry.shift_id]
            cell["good"] += entry.qty_good
            cell["second"] += entry.qty_second
            cell["scrap"] += entry.qty_scrap
            cell["material"] += entry.qty_material
        rows = []
        for department in departments:
            shifts = per_dept.get(department.id, {})
            total = self._figures(department, list(shifts.values()), len(shifts))
            detail = []
            if by_shift:
                for shift in sorted(shifts, key=lambda s: (s.date, s.template_id.hour_from if s.template_id else 0)):
                    figures = self._figures(department, [shifts[shift]], 1)
                    figures["label"] = shift.display_name
                    detail.append(figures)
            total.update({"department": department, "label": department.name, "detail": detail})
            rows.append(total)
        return rows

    @api.model
    def _figures(self, department, cells, shift_count):
        good = sum(c["good"] for c in cells)
        second = sum(c["second"] for c in cells)
        scrap = sum(c["scrap"] for c in cells)
        material = sum(c["material"] for c in cells)
        out = good + second + scrap
        plan = department.cst_norm_per_shift * shift_count
        scrap_pct = scrap / out * 100 if out else 0.0
        second_pct = second / out * 100 if out else 0.0
        return {
            "shifts": shift_count, "good": good, "second": second, "scrap": scrap, "material": material,
            "out": out, "scrap_pct": scrap_pct, "second_pct": second_pct,
            "scrap_norm": department.cst_scrap_norm_pct, "second_norm": department.cst_second_norm_pct,
            "scrap_over": bool(department.cst_scrap_norm_pct and scrap_pct > department.cst_scrap_norm_pct),
            "second_over": bool(department.cst_second_norm_pct and second_pct > department.cst_second_norm_pct),
            "plan": plan, "done_pct": good / plan * 100 if plan else 0.0,
        }


class CstDepartmentNormWizard(models.TransientModel):
    _name = "cst.department.norm.wizard"
    _description = "Bo'limlar: norma va brak"
    _inherit = "cst.period.wizard"
    _report_xmlid = "action_report_department_norm"

    department_ids = fields.Many2many("cst.production.department", string="Bo'limlar")
    by_shift = fields.Boolean(string="Har smena alohida")

    def _report(self, suffix=""):
        self.ensure_one()
        return self.env.ref("cst_kerama_shift.%s%s" % (self._report_xmlid, suffix)).report_action(self)

    def _report_values(self):
        self.ensure_one()
        return {
            "wizard": self, "title": "Bo'limlar: norma va brak foizi",
            "date_from": self.date_from, "date_to": self.date_to,
            "rows": self.env["cst.department.norm.report"].build(
                self.date_from, self.date_to, department_ids=self.department_ids.ids or None,
                by_shift=self.by_shift),
        }
