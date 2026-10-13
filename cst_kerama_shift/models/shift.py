from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CstProductionShift(models.Model):
    """One shift of one department: who came, what was run, what came out.

    Opened by the department's manager, closed by the same screen with the KPI
    fund the manager enters; the fund is split equally between the people who
    worked and written to payroll, brak as a penalty next to it.
    """

    _name = "cst.production.shift"
    _description = "Smena"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(string="Raqam", required=True, copy=False, readonly=True, default=lambda self: _("Yangi"))
    department_id = fields.Many2one(
        "cst.production.department", string="Bo'lim", required=True, index=True, tracking=True,
        ondelete="restrict")
    company_id = fields.Many2one(related="department_id.company_id", store=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    template_id = fields.Many2one(
        "cst.production.shift.template", string="Smena", required=True, tracking=True,
        domain="[('id', 'in', allowed_template_ids)]")
    allowed_template_ids = fields.Many2many(
        "cst.production.shift.template", compute="_compute_allowed_templates")
    date = fields.Date(string="Sana", required=True, default=fields.Date.context_today, tracking=True,
                       help="Smena boshlangan kun. Tungi smena ham boshlangan kuniga yoziladi.")
    date_start = fields.Datetime(string="Boshlanishi", compute="_compute_window", store=True)
    date_end = fields.Datetime(string="Tugashi", compute="_compute_window", store=True)
    manager_id = fields.Many2one(
        "res.users", string="Menejer", required=True, default=lambda self: self.env.user, tracking=True,
        domain=[("share", "=", False)])
    employee_ids = fields.Many2many(
        "hr.employee", "cst_shift_employee_rel", "shift_id", "employee_id",
        string="Smenadagi xodimlar", help="Bugun shu smenada ishlagan xodimlar. KPI fondi ular o'rtasida bo'linadi.")
    employee_count = fields.Integer(compute="_compute_totals")
    attendance_employee_ids = fields.Many2many(
        "hr.employee", compute="_compute_attendance", string="Face ID bo'yicha kelganlar")
    state = fields.Selection([
        ("draft", "Qoralama"),
        ("open", "Ochiq"),
        ("closed", "Yopilgan"),
        ("cancel", "Bekor qilingan"),
    ], default="draft", required=True, tracking=True, copy=False, index=True)
    line_ids = fields.One2many("cst.production.shift.line", "shift_id", string="Buyurtmalar")
    entry_ids = fields.One2many("cst.production.shift.entry", "shift_id", string="Natija yozuvlari")
    line_count = fields.Integer(compute="_compute_totals")
    qty_planned = fields.Float(string="Reja", compute="_compute_totals", digits="Product Unit of Measure")
    qty_good = fields.Float(string="1-sort", compute="_compute_totals", digits="Product Unit of Measure")
    qty_second = fields.Float(string="2-sort", compute="_compute_totals", digits="Product Unit of Measure")
    qty_scrap = fields.Float(string="Brak", compute="_compute_totals", digits="Product Unit of Measure")
    plan_pct = fields.Float(string="Reja %", compute="_compute_totals")
    kpi_total = fields.Monetary(string="KPI fondi", currency_field="currency_id", tracking=True,
                                help="Smena yopilganda menejer kiritadi; xodimlarga bo'linadi.")
    penalty_total = fields.Monetary(string="Brak jarimasi", currency_field="currency_id", tracking=True)
    kpi_per_employee = fields.Monetary(string="Har xodimga", currency_field="currency_id", compute="_compute_totals")
    payroll_line_ids = fields.One2many("cst.payroll.line", compute="_compute_payroll_lines", string="Oylik qatorlari")
    payroll_line_count = fields.Integer(compute="_compute_payroll_lines")
    closed_at = fields.Datetime(string="Yopilgan vaqt", readonly=True, copy=False)
    closed_by = fields.Many2one("res.users", string="Kim yopdi", readonly=True, copy=False)
    note = fields.Text(string="Izoh")

    # ------------------------------------------------------------------ computes
    @api.depends("department_id")
    def _compute_allowed_templates(self):
        for shift in self:
            shift.allowed_template_ids = shift.department_id._templates() if shift.department_id \
                else self.env["cst.production.shift.template"].search([])

    @api.depends("template_id", "template_id.hour_from", "template_id.hour_to", "date", "department_id.tz")
    def _compute_window(self):
        for shift in self:
            if shift.template_id and shift.date:
                shift.date_start, shift.date_end = shift.template_id._window(
                    shift.date, shift.department_id.tz)
            else:
                shift.date_start = shift.date_end = False

    @api.depends("date_start", "date_end", "department_id")
    def _compute_attendance(self):
        """Who Face ID saw arrive for this shift: a check-in from two hours before
        the start up to the end, or an open attendance spanning the start."""
        Attendance = self.env["hr.attendance"].sudo()
        for shift in self:
            if not shift.date_start:
                shift.attendance_employee_ids = False
                continue
            since = shift.date_start - timedelta(hours=2)
            records = Attendance.search([
                ("employee_id.company_id", "in", (shift.company_id.id, False)),
                "|", "&", ("check_in", ">=", since), ("check_in", "<=", shift.date_end),
                "&", "&", ("check_in", "<", shift.date_start),
                "|", ("check_out", "=", False), ("check_out", ">=", shift.date_start),
                ("check_in", ">=", shift.date_start - timedelta(hours=14)),
            ])
            shift.attendance_employee_ids = [(6, 0, records.employee_id.ids)]

    @api.depends("line_ids.planned_qty", "line_ids.qty_good", "line_ids.qty_second", "line_ids.qty_scrap",
                 "employee_ids", "kpi_total")
    def _compute_totals(self):
        for shift in self:
            lines = shift.line_ids
            shift.line_count = len(lines)
            shift.employee_count = len(shift.employee_ids)
            shift.qty_planned = sum(lines.mapped("planned_qty"))
            shift.qty_good = sum(lines.mapped("qty_good"))
            shift.qty_second = sum(lines.mapped("qty_second"))
            shift.qty_scrap = sum(lines.mapped("qty_scrap"))
            shift.plan_pct = (shift.qty_good / shift.qty_planned * 100.0) if shift.qty_planned else 0.0
            shift.kpi_per_employee = (shift.kpi_total / shift.employee_count) if shift.employee_count else 0.0

    @api.depends("state", "closed_at")
    def _compute_payroll_lines(self):
        Line = self.env["cst.payroll.line"]
        for shift in self:
            lines = Line.search([("source_model", "=", self._name), ("source_id", "=", shift.id),
                                 ("state", "!=", "cancel")]) if shift.id else Line
            shift.payroll_line_ids = lines
            shift.payroll_line_count = len(lines)

    @api.depends("name", "department_id.code", "template_id.name", "date")
    def _compute_display_name(self):
        for shift in self:
            bits = [shift.name or ""]
            if shift.department_id:
                bits.append(shift.department_id.name)
            if shift.template_id:
                bits.append(shift.template_id.name)
            if shift.date:
                bits.append(shift.date.strftime("%d.%m.%Y"))
            shift.display_name = " · ".join(b for b in bits if b)

    # ------------------------------------------------------------------ rules
    @api.constrains("state", "department_id")
    def _check_one_open(self):
        for shift in self.filtered(lambda s: s.state == "open"):
            other = self.search_count([
                ("id", "!=", shift.id), ("department_id", "=", shift.department_id.id), ("state", "=", "open")])
            if other:
                raise ValidationError(_(
                    "«%s» bo'limida allaqachon ochiq smena bor. Avval uni yoping.", shift.department_id.name))

    @api.constrains("template_id", "date", "department_id", "state")
    def _check_unique_slot(self):
        for shift in self.filtered(lambda s: s.state != "cancel"):
            twin = self.search_count([
                ("id", "!=", shift.id), ("department_id", "=", shift.department_id.id),
                ("template_id", "=", shift.template_id.id), ("date", "=", shift.date),
                ("state", "!=", "cancel")])
            if twin:
                raise ValidationError(_(
                    "%(dept)s bo'limida %(date)s kuni %(shift)s allaqachon ochilgan.",
                    dept=shift.department_id.name, date=shift.date.strftime("%d.%m.%Y"),
                    shift=shift.template_id.name))

    def _check_manager(self):
        """The current user must run this department, unless they run the shop."""
        if self.env.user.has_group("cst_kerama_shift.group_shift_admin"):
            return
        for shift in self:
            if self.env.user not in shift.department_id.manager_user_ids:
                raise UserError(_(
                    "Siz «%s» bo'limining menejeri emassiz. Faqat bo'lim menejeri smena ochadi va yopadi.",
                    shift.department_id.name))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("Yangi")) == _("Yangi"):
                vals["name"] = self.env["ir.sequence"].next_by_code("cst.production.shift") or _("Yangi")
        return super().create(vals_list)

    # ------------------------------------------------------------------ actions
    def action_open(self):
        for shift in self:
            if shift.state != "draft":
                raise UserError(_("Faqat qoralama smena ochiladi."))
            shift._check_manager()
            if not shift.employee_ids:
                present = shift.attendance_employee_ids
                staff = shift.department_id.employee_ids
                # only this department's staff: Face ID sees the whole factory
                shift.employee_ids = (present & staff) or staff
            shift.write({"state": "open"})
            shift.message_post(body=_("Smena ochildi: %s xodim.", len(shift.employee_ids)))
        return True

    def action_close(self):
        """Open the closing screen: results, the KPI fund to enter, the split."""
        self.ensure_one()
        if self.state != "open":
            raise UserError(_("Faqat ochiq smena yopiladi."))
        self._check_manager()
        return {
            "type": "ir.actions.act_window", "name": _("Smenani yakunlash"),
            "res_model": "cst.production.shift.close", "view_mode": "form", "target": "new",
            "context": {"default_shift_id": self.id},
        }

    def _do_close(self, kpi_total, penalty_total, shares, note=None):
        """Finish the shift: carry unfinished lines, write the fund to payroll.

        ``shares`` is ``[(employee, kpi_amount, penalty_amount)]`` -- the split
        the manager confirmed on the closing screen.
        """
        self.ensure_one()
        if self.state != "open":
            raise UserError(_("Smena ochiq emas."))
        self.line_ids._sync_external()
        for line in self.line_ids.filtered(lambda l: l.state in ("progress", "paused")):
            line.action_carry()
        self._post_payroll(shares)
        self.write({
            "kpi_total": kpi_total, "penalty_total": penalty_total, "state": "closed",
            "closed_at": fields.Datetime.now(), "closed_by": self.env.user.id,
            "note": note or self.note,
        })
        self.invalidate_recordset(["payroll_line_ids", "payroll_line_count"])
        self.message_post(body=_(
            "Smena yopildi. 1-sort %(good)s, 2-sort %(second)s, brak %(scrap)s. KPI fondi %(kpi)s, jarima %(penalty)s.",
            good=self.qty_good, second=self.qty_second, scrap=self.qty_scrap,
            kpi=kpi_total, penalty=penalty_total))
        return True

    def _payroll_period(self):
        """An open payroll period covering the shift date, if the payroll has one."""
        self.ensure_one()
        Period = self.env["cst.payroll.period"]
        periods = Period.search([
            ("company_id", "=", self.company_id.id),
            ("date_from", "<=", self.date), ("date_to", ">=", self.date),
        ], order="id desc")
        open_periods = periods.filtered(lambda p: p.state == "draft") if "state" in Period._fields else periods
        return (open_periods or periods)[:1]

    def _post_payroll(self, shares):
        """One accrual line per worker for the fund, one deduction for the brak."""
        self.ensure_one()
        Line = self.env["cst.payroll.line"].sudo()
        kpi_component = self.env.ref("cst_kerama_shift.component_smena_kpi")
        penalty_component = self.env.ref("cst_kerama_payroll.component_jarima")
        period = self._payroll_period()
        currency = self.currency_id
        shift_code = self.template_id._payroll_code()
        products = ", ".join(sorted(set(self.line_ids.mapped("product_id.display_name"))))[:200]
        vals = []
        for employee, kpi_amount, penalty_amount in shares:
            base = {
                "employee_id": employee.id,
                "company_id": self.company_id.id,
                "date": self.date,
                "period_id": period.id if period else False,
                "is_manual": True,
                "source_model": self._name,
                "source_id": self.id,
                "cst_shift": shift_code,
                "note": products,
            }
            if not currency.is_zero(kpi_amount):
                vals.append(dict(base, component_id=kpi_component.id, amount=abs(kpi_amount),
                                 name=_("Smena KPI — %s", self.display_name)))
            if not currency.is_zero(penalty_amount):
                vals.append(dict(base, component_id=penalty_component.id, amount=abs(penalty_amount),
                                 name=_("Brak jarimasi — %s", self.display_name)))
        return Line.create(vals) if vals else Line

    def action_reopen(self):
        """Take a closed shift back -- the payroll lines still in draft go with it."""
        for shift in self:
            if shift.state != "closed":
                raise UserError(_("Faqat yopilgan smena qayta ochiladi."))
            if not self.env.user.has_group("cst_kerama_shift.group_shift_admin"):
                raise UserError(_("Yopilgan smenani faqat ishlab chiqarish rahbari qayta ochadi."))
            lines = shift.payroll_line_ids
            posted = lines.filtered(lambda l: l.state not in ("draft", "cancel"))
            if posted:
                raise UserError(_(
                    "Bu smenaning oylik qatorlari tasdiqlangan (%s ta); avval oylikda ularni qoralamaga qaytaring.",
                    len(posted)))
            lines.sudo().unlink()
            shift.write({"state": "open", "closed_at": False, "closed_by": False})
            shift.invalidate_recordset(["payroll_line_ids", "payroll_line_count"])
            shift.message_post(body=_("Smena qayta ochildi."))
        return True

    def action_cancel(self):
        for shift in self:
            if shift.state not in ("draft", "open") or shift.line_ids.filtered(lambda l: l.state != "todo"):
                raise UserError(_("Ish boshlangan smenani bekor qilib bo'lmaydi, uni yoping."))
            shift.write({"state": "cancel"})
        return True

    def action_view_payroll_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Oylik qatorlari"),
            "res_model": "cst.payroll.line", "view_mode": "list,form",
            "domain": [("id", "in", self.payroll_line_ids.ids)],
        }

    def action_refresh_attendance(self):
        """Tick whoever Face ID has seen since the shift started."""
        for shift in self.filtered(lambda s: s.state in ("draft", "open")):
            shift.invalidate_recordset(["attendance_employee_ids"])
            shift.employee_ids |= shift.attendance_employee_ids & shift.department_id.employee_ids
        return True
