from odoo import _, api, fields, models
from odoo.exceptions import UserError

# what HR types on a row; the automatic recount never overwrites it
MANUAL_FIELDS = {"kpi_done", "kpi_plan", "kpi_price", "kpi_amount"}
# a change of any of these rewrites the shift's payroll lines
GUARDED_FIELDS = {"kpi_amount", "penalty_amount", "employee_id", "shift_id", "present"} | MANUAL_FIELDS


class CstProductionShiftWorker(models.Model):
    """One worker of a closed shift: what they did, their KPI, their brak penalty.

    The crew comes from the shift. Those Face ID saw come share the shift's
    output and its plan equally; the KPI is the worker's «KPI narxi» × the
    share of the plan they did (Smena KPI). HR may correct the numbers of a
    row by hand -- a recount keeps such rows -- and confirms the sheet, which
    writes it to payroll and queues the KPI for the cost price of what the
    shift produced.
    """

    _name = "cst.production.shift.worker"
    _description = "Smena xodimi (KPI)"
    _order = "shift_date desc, shift_id desc, present desc, employee_name, id"

    shift_id = fields.Many2one("cst.production.shift", string="Smena", required=True, ondelete="cascade", index=True)
    shift_date = fields.Date(related="shift_id.date", store=True, string="Sana")
    department_id = fields.Many2one(related="shift_id.department_id", store=True, string="Bo'lim")
    template_id = fields.Many2one(related="shift_id.template_id", store=True, string="Smena vaqti")
    shift_state = fields.Selection(related="shift_id.state", string="Smena holati")
    kpi_state = fields.Selection(related="shift_id.kpi_state", string="KPI holati")
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
    present = fields.Boolean(
        string="Keldi", default=True,
        help="Smena ishi kelganlar o'rtasida bo'linadi. Face ID bo'yicha belgilanadi, HR qo'lda o'zgartira oladi.")
    face_id_seen = fields.Boolean(string="Face ID", compute="_compute_presence", compute_sudo=True)
    presence = fields.Selection([
        ("face", "Keldi"),
        ("manual", "Keldi (qo'lda)"),
        ("excluded", "Chiqarildi (qo'lda)"),
        ("absent", "Face ID dan o'tmagan"),
    ], string="Davomat", compute="_compute_presence", compute_sudo=True)
    kpi_done = fields.Float(string="Bajargan ishlar soni", digits="Product Unit of Measure",
                            help="Smenada chiqarilgan 1-sort + 2-sort, kelgan xodimlarga bo'lingan ulushi.")
    kpi_plan = fields.Float(string="Belgilangan natija", digits="Product Unit of Measure",
                            help="Smena rejasining xodimga tushgan ulushi (reja ÷ kelganlar soni).")
    kpi_ratio = fields.Float(string="Foiz", compute="_compute_kpi_ratio",
                             help="Bajargan ishlar soni ÷ belgilangan natija.")
    kpi_price = fields.Monetary(string="KPI narxi", currency_field="currency_id",
                                help="Reja 100% bajarilganda xodim oladigan summa (Sozlamalar ▸ KPI narxlari).")
    kpi_manual = fields.Boolean(string="Qo'lda o'zgartirilgan", copy=False,
                                help="HR qatorni qo'lda o'zgartirgan: avtomatik qayta hisoblash unga tegmaydi "
                                     "(«Qayta hisoblash» tugmasidan tashqari).")
    kpi_suggested = fields.Monetary(
        string="Stavka bo'yicha", currency_field="currency_id", compute="_compute_kpi_ratio",
        help="KPI narxi × bajarilish foizi.")
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
        for worker in self:
            shift = worker.shift_id
            employee = worker.employee_id
            parts, good = [], 0.0
            for line in shift.line_ids:
                crew = line.employee_ids or shift.employee_ids
                if employee not in crew:
                    continue
                good += line.qty_good / len(crew) if crew else 0.0
                parts.append("%s: %g" % (line.product_id.cst_base_name() if hasattr(line.product_id, "cst_base_name")
                                         else line.product_id.display_name, line.qty_good))
            worker.worked = "; ".join(parts)[:250] or "—"
            worker.qty_good = good
            worker.minutes = sum(Productivity.search([
                ("employee_id", "=", employee.id),
                ("workorder_id", "in", shift.line_ids.workorder_id.ids),
            ]).mapped("duration")) if shift.line_ids else 0.0

    @api.depends("present", "employee_id", "shift_id.attendance_employee_ids")
    def _compute_presence(self):
        for worker in self:
            seen = worker.employee_id in worker.shift_id.attendance_employee_ids
            worker.face_id_seen = seen
            if worker.present:
                worker.presence = "face" if seen else "manual"
            else:
                worker.presence = "excluded" if seen else "absent"

    @api.depends("kpi_done", "kpi_plan", "kpi_price")
    def _compute_kpi_ratio(self):
        for worker in self:
            worker.kpi_ratio = worker.kpi_done / worker.kpi_plan if worker.kpi_plan else 0.0
            worker.kpi_suggested = worker._cst_kpi_formula()

    def _cst_kpi_formula(self):
        """KPI narxi × done ÷ plan, in the payroll currency."""
        self.ensure_one()
        amount = self.kpi_price * self.kpi_done / self.kpi_plan if self.kpi_plan else 0.0
        return self.currency_id.round(amount) if self.currency_id else amount

    @api.onchange("kpi_done", "kpi_plan")
    def _onchange_kpi_numbers(self):
        # the percentage and the KPI follow at once on the sheet
        for worker in self:
            worker.kpi_amount = worker._cst_kpi_formula()

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
        ctx = self.env.context
        auto = ctx.get("cst_no_sync") or ctx.get("cst_kpi_auto")
        touched = GUARDED_FIELDS & set(vals)
        if touched and not auto:
            if not self._can_edit_kpi():
                raise UserError(_("Xodimlar KPI va jarimasini faqat HR o'zgartiradi."))
            if any(w.shift_id.state != "closed" for w in self):
                raise UserError(_("KPI yopilgan smenada kiritiladi."))
            if MANUAL_FIELDS & set(vals):
                vals = dict(vals, kpi_manual=True)
            if "present" in vals:
                # a worker marked in or out is counted again with the others
                vals = dict(vals, kpi_manual=False)
        result = super().write(vals)
        if touched and not auto:
            recount = {"kpi_done", "kpi_plan", "kpi_price"} & set(vals) and "kpi_amount" not in vals
            if recount:
                for worker in self:
                    super(CstProductionShiftWorker, worker).write({"kpi_amount": worker._cst_kpi_formula()})
            if "present" in vals:
                self.shift_id._cst_kpi_recompute()
                self._cst_log_change(vals)
            else:
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

    def _cst_log_change(self, vals):
        for worker in self:
            if "present" in vals:
                worker.shift_id.sudo().message_post(body=_(
                    "%(who)s: %(what)s (%(user)s).", who=worker.employee_name,
                    what=_("keldi deb belgilandi") if worker.present else _("kelmadi deb belgilandi"),
                    user=self.env.user.name))
            elif {"kpi_amount", "penalty_amount", "kpi_done", "kpi_plan"} & set(vals):
                worker.shift_id.sudo().message_post(body=_(
                    "%(who)s: bajardi %(done)s / reja %(plan)s, KPI %(kpi)s, jarima %(penalty)s (%(user)s).",
                    who=worker.employee_name, done=round(worker.kpi_done, 2), plan=round(worker.kpi_plan, 2),
                    kpi=worker.kpi_amount, penalty=worker.penalty_amount, user=self.env.user.name))

    def _cst_after_change(self, vals):
        self._cst_log_change(vals)
        shifts = self.shift_id
        shifts._cst_workers_changed()
        shifts._cst_sync_payroll()

    def action_toggle_present(self):
        """«Keldi» on the KPI sheet: count the worker in or out, the shift's
        work is shared again between those who came."""
        for worker in self:
            worker.write({"present": not worker.present})
        return True


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
