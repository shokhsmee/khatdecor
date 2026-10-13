from odoo import _, api, fields, models


class CstProductionShiftReport(models.TransientModel):
    """Smena registri: every shift of a period with its people, output, brak, fund.

    The list is the register the shop kept by hand (bo'lim · smena · menejer ·
    xodimlar · miqdor · brak · jarima · bonus); the workbook is the same rows.
    """

    _name = "cst.production.shift.report"
    _description = "Smena registri"

    date_from = fields.Date(string="Boshlanish", required=True,
                            default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(string="Tugash", required=True, default=fields.Date.context_today)
    department_ids = fields.Many2many("cst.production.department", string="Bo'limlar")
    include_open = fields.Boolean(string="Ochiq smenalar ham", default=True)

    def _domain(self):
        self.ensure_one()
        domain = [("date", ">=", self.date_from), ("date", "<=", self.date_to),
                  ("state", "in", ("open", "closed") if self.include_open else ("closed",))]
        if self.department_ids:
            domain.append(("department_id", "in", self.department_ids.ids))
        return domain

    def _rows(self):
        self.ensure_one()
        rows = []
        for shift in self.env["cst.production.shift"].search(self._domain(), order="date, department_id, template_id"):
            products = {}
            for line in shift.line_ids:
                key = line.product_id.display_name
                p = products.setdefault(key, [0.0, 0.0, 0.0])
                p[0] += line.qty_good; p[1] += line.qty_second; p[2] += line.qty_scrap
            rows.append({
                "shift": shift,
                "date": shift.date, "department": shift.department_id.name, "template": shift.template_id.name,
                "manager": shift.manager_id.name, "employees": ", ".join(shift.employee_ids.mapped("name")),
                "employee_count": len(shift.employee_ids), "orders": len(shift.line_ids),
                "planned": shift.qty_planned, "good": shift.qty_good, "second": shift.qty_second, "scrap": shift.qty_scrap,
                "kpi": shift.kpi_total, "per_employee": shift.kpi_per_employee, "penalty": shift.penalty_total,
                "state": dict(shift._fields["state"].selection)[shift.state],
                "products": "; ".join("%s: %g / %g / %g" % (k, v[0], v[1], v[2]) for k, v in products.items()),
            })
        return rows

    def action_view(self):
        """The register on screen: the shift list, filtered and grouped."""
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("cst_kerama_shift.action_shifts")
        action["domain"] = self._domain()
        action["context"] = {"search_default_group_department": 1, "search_default_group_date": 1}
        action["name"] = _("Smena registri %s – %s", self.date_from.strftime("%d.%m.%Y"), self.date_to.strftime("%d.%m.%Y"))
        return action

    def action_xlsx(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "target": "self",
                "url": "/cst_shift/register/xlsx/%d" % self.id}
