from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CstProductionShiftClose(models.TransientModel):
    """The closing screen: today's results, the fund the manager enters, the split."""

    _name = "cst.production.shift.close"
    _description = "Smenani yakunlash"

    shift_id = fields.Many2one("cst.production.shift", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="shift_id.company_id")
    currency_id = fields.Many2one(related="shift_id.currency_id")
    department_name = fields.Char(related="shift_id.department_id.name")
    qty_good = fields.Float(related="shift_id.qty_good")
    qty_second = fields.Float(related="shift_id.qty_second")
    qty_scrap = fields.Float(related="shift_id.qty_scrap")
    qty_planned = fields.Float(related="shift_id.qty_planned")
    open_line_count = fields.Integer(compute="_compute_open_lines")
    kpi_total = fields.Monetary(string="Umumiy KPI summasi", currency_field="currency_id", required=True,
                                help="Smena uchun mukofot fondi. Xodimlarga teng bo'linadi; ulushni qo'lda o'zgartirish mumkin.")
    penalty_total = fields.Monetary(string="Brak jarimasi (jami)", currency_field="currency_id")
    line_ids = fields.One2many("cst.production.shift.close.line", "wizard_id", string="Xodimlar")
    note = fields.Text(string="Izoh")
    summary_html = fields.Html(compute="_compute_summary", sanitize=False)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        shift = self.env["cst.production.shift"].browse(values.get("shift_id") or self.env.context.get("default_shift_id"))
        if shift:
            values.setdefault("kpi_total", shift.kpi_total)
            values.setdefault("penalty_total", shift.penalty_total)
            values["line_ids"] = [(0, 0, v) for v in self._employee_lines(
                shift, values["kpi_total"] or 0.0, values["penalty_total"] or 0.0)]
        return values

    @api.model
    def _employee_lines(self, shift, kpi_total, penalty_total):
        employees = shift.employee_ids
        n = len(employees)
        currency = shift.currency_id
        kpi_share = currency.round(kpi_total / n) if n else 0.0
        penalty_share = currency.round(penalty_total / n) if n else 0.0
        Productivity = self.env["mrp.workcenter.productivity"].sudo()
        rows = []
        for i, employee in enumerate(employees):
            lines = shift.line_ids.filtered(lambda l, e=employee: e in l.employee_ids)
            minutes = sum(Productivity.search([
                ("employee_id", "=", employee.id),
                ("workorder_id", "in", shift.line_ids.workorder_id.ids),
            ]).mapped("duration"))
            # the rounding remainder lands on the last worker so the shares add up
            kpi = kpi_share if i < n - 1 else currency.round(kpi_total - kpi_share * (n - 1))
            penalty = penalty_share if i < n - 1 else currency.round(penalty_total - penalty_share * (n - 1))
            rows.append({
                "employee_id": employee.id,
                "worked": ", ".join(lines.mapped("product_id.display_name"))[:120] or "—",
                "minutes": minutes,
                "kpi_amount": kpi,
                "penalty_amount": penalty,
            })
        return rows

    @api.depends("shift_id")
    def _compute_open_lines(self):
        for wizard in self:
            wizard.open_line_count = len(wizard.shift_id.line_ids.filtered(lambda l: l.state in ("progress", "paused")))

    @api.depends("shift_id")
    def _compute_summary(self):
        for wizard in self:
            rows = []
            for line in wizard.shift_id.line_ids:
                rows.append(
                    "<tr><td>%s</td><td class='text-muted'>%s</td><td class='text-end'>%g</td>"
                    "<td class='text-end fw-bold'>%g</td><td class='text-end'>%g</td>"
                    "<td class='text-end text-danger'>%g</td><td>%s</td></tr>" % (
                        line.product_id.display_name, line.workcenter_id.name or "",
                        line.planned_qty, line.qty_good, line.qty_second, line.qty_scrap,
                        dict(line._fields["state"].selection).get(line.state, "")))
            wizard.summary_html = (
                "<table class='table table-sm mb-0'><thead><tr><th>Mahsulot</th><th>Liniya</th>"
                "<th class='text-end'>Reja</th><th class='text-end'>1-sort</th><th class='text-end'>2-sort</th>"
                "<th class='text-end'>Brak</th><th>Holat</th></tr></thead><tbody>%s</tbody></table>"
                % ("".join(rows) or "<tr><td colspan='7' class='text-muted'>Buyurtma yo'q</td></tr>"))

    @api.onchange("kpi_total", "penalty_total")
    def _onchange_totals(self):
        """Split again whenever the manager changes a total."""
        for wizard in self:
            if not wizard.shift_id:
                continue
            rows = wizard._employee_lines(wizard.shift_id, wizard.kpi_total or 0.0, wizard.penalty_total or 0.0)
            by_employee = {r["employee_id"]: r for r in rows}
            for line in wizard.line_ids:
                row = by_employee.get(line.employee_id.id)
                if row:
                    line.kpi_amount = row["kpi_amount"]
                    line.penalty_amount = row["penalty_amount"]

    def action_confirm(self):
        self.ensure_one()
        shift = self.shift_id
        currency = shift.currency_id
        if not self.line_ids:
            raise UserError(_("Smenada xodim yo'q. Avval xodimlarni belgilang."))
        # a manager who typed the totals and never touched the rows meant an equal split
        untouched_kpi = currency.is_zero(sum(self.line_ids.mapped("kpi_amount"))) and not currency.is_zero(self.kpi_total)
        untouched_penalty = currency.is_zero(sum(self.line_ids.mapped("penalty_amount"))) and not currency.is_zero(self.penalty_total or 0.0)
        if untouched_kpi or untouched_penalty:
            rows = {r["employee_id"]: r for r in self._employee_lines(shift, self.kpi_total, self.penalty_total or 0.0)}
            for line in self.line_ids:
                row = rows.get(line.employee_id.id)
                if not row:
                    continue
                if untouched_kpi:
                    line.kpi_amount = row["kpi_amount"]
                if untouched_penalty:
                    line.penalty_amount = row["penalty_amount"]
        kpi_sum = sum(self.line_ids.mapped("kpi_amount"))
        penalty_sum = sum(self.line_ids.mapped("penalty_amount"))
        if currency.compare_amounts(kpi_sum, self.kpi_total) != 0:
            raise UserError(_("Xodimlar ulushlari yig'indisi (%s) umumiy KPI summasiga (%s) teng emas.", kpi_sum, self.kpi_total))
        if currency.compare_amounts(penalty_sum, self.penalty_total or 0.0) != 0:
            raise UserError(_("Jarima ulushlari yig'indisi (%s) umumiy jarimaga (%s) teng emas.", penalty_sum, self.penalty_total))
        shares = [(l.employee_id, l.kpi_amount, l.penalty_amount) for l in self.line_ids]
        shift._do_close(self.kpi_total, self.penalty_total or 0.0, shares, note=self.note)
        return {"type": "ir.actions.act_window_close"}


class CstProductionShiftCloseLine(models.TransientModel):
    _name = "cst.production.shift.close.line"
    _description = "Smenani yakunlash: xodim"

    wizard_id = fields.Many2one("cst.production.shift.close", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    employee_id = fields.Many2one("hr.employee", string="Xodim", required=True)
    worked = fields.Char(string="Qilgan ishi", readonly=True)
    minutes = fields.Float(string="Ish vaqti (daq.)", readonly=True)
    kpi_amount = fields.Monetary(string="KPI ulushi", currency_field="currency_id")
    penalty_amount = fields.Monetary(string="Jarima ulushi", currency_field="currency_id")
