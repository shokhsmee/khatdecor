from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CstProductionShiftWorker(models.Model):
    """One worker of a closed shift: what they did, their KPI, their brak penalty.

    The crew comes from the shift; the KPI amount is HR's to enter, per person
    and depending on the work done, also after the shift is closed. Every
    change rewrites the shift's draft payroll lines and queues the KPI for the
    cost price of what the shift produced.
    """

    _name = "cst.production.shift.worker"
    _description = "Smena xodimi (KPI)"
    _order = "shift_date desc, shift_id desc, employee_name, id"

    shift_id = fields.Many2one("cst.production.shift", string="Smena", required=True, ondelete="cascade", index=True)
    shift_date = fields.Date(related="shift_id.date", store=True, string="Sana")
    department_id = fields.Many2one(related="shift_id.department_id", store=True, string="Bo'lim")
    template_id = fields.Many2one(related="shift_id.template_id", store=True, string="Smena vaqti")
    shift_state = fields.Selection(related="shift_id.state", string="Smena holati")
    company_id = fields.Many2one(related="shift_id.company_id", store=True)
    currency_id = fields.Many2one(related="shift_id.currency_id")
    employee_id = fields.Many2one("hr.employee", string="Xodim", required=True, index=True)
    # stored so HR and the reports read it without touching the employee record
    employee_name = fields.Char(string="Xodim ismi", compute="_compute_employee_name", store=True, compute_sudo=True)
    worked = fields.Char(string="Qilgan ishi", compute="_compute_work", compute_sudo=True)
    qty_good = fields.Float(string="1-sort (ulushi)", compute="_compute_work", compute_sudo=True,
                            digits="Product Unit of Measure",
                            help="Xodim ishlagan buyurtmalardagi 1-sort, buyurtmadagi xodimlar soniga bo'lingan.")
    minutes = fields.Float(string="Ish vaqti (daq.)", compute="_compute_work", compute_sudo=True)
    kpi_suggested = fields.Monetary(
        string="Stavka bo'yicha", currency_field="currency_id", compute="_compute_work", compute_sudo=True,
        help="KPI stavkalari (Sozlamalar ▸ KPI stavkalari) × xodimning 1-sort ulushi. Faqat taklif.")
    kpi_amount = fields.Monetary(string="KPI", currency_field="currency_id")
    penalty_amount = fields.Monetary(string="Jarima", currency_field="currency_id")
    note = fields.Char(string="Izoh")
    can_edit = fields.Boolean(compute="_compute_can_edit")

    _shift_employee_uniq = models.Constraint("unique(shift_id, employee_id)", "Xodim smenada bir marta bo'ladi.")

    @api.depends("employee_id")
    def _compute_employee_name(self):
        for worker in self:
            worker.employee_name = worker.employee_id.name

    @api.depends("shift_id.line_ids.qty_good", "shift_id.line_ids.employee_ids", "employee_id")
    def _compute_work(self):
        Productivity = self.env["mrp.workcenter.productivity"]
        Rate = self.env["cst.shift.kpi.rate"]
        for worker in self:
            shift = worker.shift_id
            employee = worker.employee_id
            parts, good, suggested = [], 0.0, 0.0
            for line in shift.line_ids:
                crew = line.employee_ids or shift.employee_ids
                if employee not in crew:
                    continue
                share = line.qty_good / len(crew) if crew else 0.0
                good += share
                suggested += share * Rate._rate_for(line)
                parts.append("%s: %g" % (line.product_id.cst_base_name() if hasattr(line.product_id, "cst_base_name")
                                         else line.product_id.display_name, line.qty_good))
            worker.worked = "; ".join(parts)[:250] or "—"
            worker.qty_good = good
            worker.kpi_suggested = shift.currency_id.round(suggested) if shift.currency_id else suggested
            worker.minutes = sum(Productivity.search([
                ("employee_id", "=", employee.id),
                ("workorder_id", "in", shift.line_ids.workorder_id.ids),
            ]).mapped("duration")) if shift.line_ids else 0.0

    @api.model
    def _can_edit_kpi(self):
        user = self.env.user
        return self.env.su or user.has_group("hr.group_hr_user") or user.has_group("base.group_system")

    @api.depends_context("uid")
    def _compute_can_edit(self):
        value = self._can_edit_kpi()
        for worker in self:
            worker.can_edit = value

    def write(self, vals):
        money = {"kpi_amount", "penalty_amount", "employee_id", "shift_id"}
        if money & set(vals) and not self.env.context.get("cst_no_sync"):
            if not self._can_edit_kpi():
                raise UserError(_("Xodimlar KPI va jarimasini faqat HR o'zgartiradi."))
            if any(w.shift_id.state != "closed" for w in self):
                raise UserError(_("KPI yopilgan smenada kiritiladi."))
        result = super().write(vals)
        if money & set(vals) and not self.env.context.get("cst_no_sync"):
            self._cst_after_change(vals)
        return result

    @api.model_create_multi
    def create(self, vals_list):
        workers = super().create(vals_list)
        if not self.env.context.get("cst_no_sync"):
            if not self._can_edit_kpi():
                raise UserError(_("Xodimlar KPI va jarimasini faqat HR o'zgartiradi."))
            workers._cst_after_change({})
        return workers

    def unlink(self):
        shifts = self.shift_id
        if not self.env.context.get("cst_no_sync") and not self._can_edit_kpi():
            raise UserError(_("Xodimlar KPI va jarimasini faqat HR o'zgartiradi."))
        result = super().unlink()
        if not self.env.context.get("cst_no_sync"):
            shifts._cst_workers_changed()
            shifts._cst_sync_payroll()
        return result

    def _cst_after_change(self, vals):
        shifts = self.shift_id
        for worker in self:
            if "kpi_amount" in vals or "penalty_amount" in vals:
                worker.shift_id.sudo().message_post(body=_(
                    "%(who)s: KPI %(kpi)s, jarima %(penalty)s (%(user)s).",
                    who=worker.employee_name, kpi=worker.kpi_amount, penalty=worker.penalty_amount,
                    user=self.env.user.name))
        shifts._cst_workers_changed()
        shifts._cst_sync_payroll()


class CstShiftKpiRate(models.Model):
    """What one 1-sort piece earns the crew, per department, line and product.

    Only a suggestion for HR: the KPI row shows rate × the worker's share of
    the 1-sort pieces, HR decides the amount. The most specific rate wins:
    product + line, product, category + line, category, line, department.
    """

    _name = "cst.shift.kpi.rate"
    _description = "Smena KPI stavkasi"
    _order = "department_id, workcenter_id, product_tmpl_id, categ_id, date_from desc, id desc"

    department_id = fields.Many2one("cst.production.department", string="Bo'lim", required=True, index=True)
    workcenter_id = fields.Many2one(
        "mrp.workcenter", string="Liniya", domain="[('cst_department_id', '=', department_id)]",
        help="Bo'sh = bo'limning hamma liniyalari.")
    product_tmpl_id = fields.Many2one("product.template", string="Mahsulot", help="Bo'sh = hamma mahsulot.")
    categ_id = fields.Many2one("product.category", string="Kategoriya",
                               help="Mahsulot tanlanmagan bo'lsa, shu kategoriyadagi mahsulotlarga.")
    rate = fields.Monetary(string="1 dona 1-sort uchun", currency_field="currency_id", required=True)
    company_id = fields.Many2one(related="department_id.company_id", store=True)
    currency_id = fields.Many2one(related="company_id.cst_payroll_currency_id")
    date_from = fields.Date(string="Amal qiladi (dan)", required=True, default=fields.Date.context_today,
                            help="Stavka o'zgarsa yangi qator qo'shing — eski smenalar eski stavkada qoladi.")
    active = fields.Boolean(default=True)
    note = fields.Char(string="Izoh")

    @api.model
    def _rate_for(self, line):
        """The rate in force for a shift line on its shift's date (0 if none)."""
        if not line.shift_id.date:
            return 0.0
        rates = self.sudo().search([
            ("department_id", "=", line.department_id.id), ("date_from", "<=", line.shift_id.date)])
        if not rates:
            return 0.0
        product = line.product_id.product_tmpl_id
        best, best_key = None, None
        for rate in rates:
            if rate.workcenter_id and rate.workcenter_id != line.workcenter_id:
                continue
            if rate.product_tmpl_id and rate.product_tmpl_id != product:
                continue
            if not rate.product_tmpl_id and rate.categ_id and not (
                    product.categ_id and product.categ_id.parent_path.startswith(rate.categ_id.parent_path)):
                continue
            key = (bool(rate.product_tmpl_id), bool(rate.categ_id), bool(rate.workcenter_id), rate.date_from, rate.id)
            if best_key is None or key > best_key:
                best, best_key = rate, key
        return best.rate if best else 0.0
