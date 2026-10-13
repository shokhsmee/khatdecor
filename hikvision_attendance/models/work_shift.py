# -*- coding: utf-8 -*-
"""Work shifts kept in one place: «1-smena 08:00–17:00», «2-smena 17:00–02:00».

Every employee stands in one shift. A Face ID entry or exit is then read
against that shift: how many minutes late, how many minutes early, or a day
off. The shift is copied onto each attendance when it is recorded, so moving
an employee to another shift or changing a shift's hours later does not
rewrite what was already counted (unless asked to, with «Qayta hisoblash»).
"""
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

SHOP_TZ = "Asia/Tashkent"
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def fmt_hour(value):
    value = value or 0.0
    hours = int(value) % 24
    minutes = int(round((value - int(value)) * 60))
    if minutes == 60:
        hours, minutes = (hours + 1) % 24, 0
    return "%02d:%02d" % (hours, minutes)


class HikWorkShift(models.Model):
    _name = "hik.work.shift"
    _description = "Ish smenasi"
    _order = "sequence, id"

    name = fields.Char(string="Smena", required=True, translate=False)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer(string="Rang")
    hour_from = fields.Float(string="Ish boshlanishi", required=True, default=8.0)
    hour_to = fields.Float(
        string="Ish tugashi", required=True, default=17.0,
        help="Boshlanishdan kichik bo'lsa smena yarim tundan o'tadi (masalan 17:00–02:00).")
    day_mon = fields.Boolean(string="Du", default=True)
    day_tue = fields.Boolean(string="Se", default=True)
    day_wed = fields.Boolean(string="Ch", default=True)
    day_thu = fields.Boolean(string="Pa", default=True)
    day_fri = fields.Boolean(string="Ju", default=True)
    day_sat = fields.Boolean(string="Sh", default=True)
    day_sun = fields.Boolean(string="Ya", default=False)
    late_tolerance = fields.Integer(
        string="Kechikish bardoshi (daq)", default=5,
        help="Shuncha daqiqagacha kechikish hisoblanmaydi.")
    early_tolerance = fields.Integer(
        string="Erta ketish bardoshi (daq)", default=5,
        help="Shuncha daqiqagacha erta ketish hisoblanmaydi.")
    employee_ids = fields.One2many("hr.employee", "hik_shift_id", string="Xodimlar")
    employee_count = fields.Integer(string="Xodimlar soni", compute="_compute_employee_count")
    time_label = fields.Char(string="Vaqti", compute="_compute_time_label")
    days_label = fields.Char(string="Ish kunlari", compute="_compute_time_label")
    duration = fields.Float(string="Davomiyligi (soat)", compute="_compute_time_label")

    @api.depends("employee_ids")
    def _compute_employee_count(self):
        for shift in self:
            shift.employee_count = len(shift.employee_ids)

    @api.depends("hour_from", "hour_to", *("day_%s" % d for d in WEEKDAYS))
    def _compute_time_label(self):
        names = dict(zip(WEEKDAYS, ("Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya")))
        for shift in self:
            shift.time_label = "%s–%s" % (fmt_hour(shift.hour_from), fmt_hour(shift.hour_to))
            shift.days_label = ", ".join(names[d] for d in WEEKDAYS if shift["day_%s" % d])
            shift.duration = shift._duration()

    @api.constrains("hour_from", "hour_to")
    def _check_hours(self):
        for shift in self:
            if not (0 <= shift.hour_from < 24 and 0 <= shift.hour_to < 24):
                raise ValidationError(_("Soat 00:00 dan 23:59 gacha bo'lishi kerak."))
            if shift.hour_from == shift.hour_to:
                raise ValidationError(_("Boshlanish va tugash vaqti bir xil bo'lmasin."))

    def _duration(self):
        self.ensure_one()
        return (self.hour_to - self.hour_from) % 24 or 24.0

    def is_workday(self, weekday):
        """``weekday``: 0 = Monday, as ``date.weekday()``."""
        self.ensure_one()
        return bool(self["day_%s" % WEEKDAYS[weekday]])

    def plan_for(self, moment):
        """The shift's planned start and end (naive UTC) that ``moment`` (naive
        UTC) belongs to, and the local date the shift started on. The start
        nearest to the moment wins, so a 2-smena entry at 01:00 is a very late
        entry for yesterday's 17:00, not an early one for today's."""
        self.ensure_one()
        tz = pytz.timezone(SHOP_TZ)
        local = pytz.utc.localize(moment).astimezone(tz)
        best = None
        for delta in (-1, 0, 1):
            day = local.date() + timedelta(days=delta)
            start = tz.localize(datetime.combine(day, time()) + timedelta(hours=self.hour_from))
            gap = abs((start - local).total_seconds())
            if best is None or gap < best[0]:
                best = (gap, start, day)
        start_utc = best[1].astimezone(pytz.utc).replace(tzinfo=None)
        return start_utc, start_utc + timedelta(hours=self._duration()), best[2]

    # ------------------------------------------------------------------
    def action_assign_employees(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "hik.work.shift.assign",
            "view_mode": "form", "target": "new",
            "context": {"default_shift_id": self.id},
        }

    def action_view_employees(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": self.name, "res_model": "hr.employee",
            "view_mode": "list,form", "domain": [("hik_shift_id", "=", self.id)],
            "context": {"default_hik_shift_id": self.id},
        }

    def action_recompute_month(self):
        """Re-read this month's attendances of these shifts' employees against
        the current hours -- after a shift's time was corrected."""
        tz = pytz.timezone(SHOP_TZ)
        today = datetime.now(tz).date()
        start = tz.localize(datetime.combine(today.replace(day=1), time())).astimezone(pytz.utc).replace(tzinfo=None)
        attendances = self.env["hr.attendance"].search([
            ("employee_id", "in", self.employee_ids.ids), ("check_in", ">=", start)])
        attendances.write({"hik_shift_id": False})
        for attendance in attendances:
            attendance.hik_shift_id = attendance.employee_id.hik_shift_id
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"type": "success", "message": _("%s ta davomat qayta hisoblandi.", len(attendances))},
        }


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    hik_shift_id = fields.Many2one(
        "hik.work.shift", string="Ish smenasi", index=True, tracking=True,
        groups="hr.group_hr_user,hr_attendance.group_hr_attendance_officer",
        help="Face ID kirish-chiqishi shu smena vaqtiga solishtiriladi.")


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    hik_shift_id = fields.Many2one("hik.work.shift", string="Smena", index=True)
    hik_planned_start = fields.Datetime(
        string="Reja: kirish", compute="_compute_hik_plan", store=True)
    hik_planned_end = fields.Datetime(
        string="Reja: chiqish", compute="_compute_hik_plan", store=True)
    hik_offday = fields.Boolean(string="Dam olish kuni", compute="_compute_hik_plan", store=True)
    hik_late_min = fields.Integer(
        string="Kechikish (daq)", compute="_compute_hik_plan", store=True, aggregator="sum")
    hik_early_min = fields.Integer(
        string="Erta ketish (daq)", compute="_compute_hik_plan", store=True, aggregator="sum")
    hik_status = fields.Selection([
        ("ok", "O'z vaqtida"), ("late", "Kechikdi"), ("early", "Erta ketdi"),
        ("late_early", "Kechikdi va erta ketdi"), ("offday", "Dam olish kuni"), ("none", "Smenasiz"),
    ], string="Holat", compute="_compute_hik_plan", store=True)

    @api.depends("check_in", "check_out", "hik_shift_id")
    def _compute_hik_plan(self):
        for att in self:
            shift = att.hik_shift_id
            if not shift or not att.check_in:
                att.update({"hik_planned_start": False, "hik_planned_end": False, "hik_offday": False,
                            "hik_late_min": 0, "hik_early_min": 0, "hik_status": "none"})
                continue
            start, end, day = shift.plan_for(att.check_in)
            offday = not shift.is_workday(day.weekday())
            late = early = 0
            if not offday:
                minutes = (att.check_in - start).total_seconds() / 60.0
                late = int(minutes) if minutes > shift.late_tolerance else 0
                if att.check_out:
                    minutes = (end - att.check_out).total_seconds() / 60.0
                    early = int(minutes) if minutes > shift.early_tolerance else 0
            status = ("offday" if offday else "late_early" if late and early
                      else "late" if late else "early" if early else "ok")
            att.update({"hik_planned_start": start, "hik_planned_end": end, "hik_offday": offday,
                        "hik_late_min": late, "hik_early_min": early, "hik_status": status})

    @api.model_create_multi
    def create(self, vals_list):
        # the employee's shift at the moment of entry stays with the record
        Employee = self.env["hr.employee"].sudo()
        for vals in vals_list:
            if not vals.get("hik_shift_id") and vals.get("employee_id"):
                vals["hik_shift_id"] = Employee.browse(vals["employee_id"]).hik_shift_id.id
        return super().create(vals_list)

    def _hik_shift_line(self, kind):
        """«⏰ 1-smena (08:00–17:00) · 12 daq kechikdi» for the bot."""
        self.ensure_one()
        shift = self.hik_shift_id
        if not shift:
            return "⏰ Smena biriktirilmagan"
        head = "⏰ %s (%s)" % (shift.name, shift.time_label)
        if self.hik_offday:
            return head + " · dam olish kuni"
        if kind == "check_in":
            return head + (" · <b>%s daq kechikdi</b>" % self.hik_late_min if self.hik_late_min else " · o'z vaqtida")
        if self.hik_early_min:
            return head + " · <b>%s daq erta ketdi</b>" % self.hik_early_min
        return head + " · o'z vaqtida"


class HikWorkShiftAssign(models.TransientModel):
    _name = "hik.work.shift.assign"
    _description = "Xodimlarni smenaga biriktirish"

    shift_id = fields.Many2one("hik.work.shift", string="Smena", required=True)
    employee_ids = fields.Many2many("hr.employee", string="Xodimlar", required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get("active_model") == "hr.employee" and self.env.context.get("active_ids"):
            res["employee_ids"] = [(6, 0, self.env.context["active_ids"])]
        return res

    def action_assign(self):
        self.ensure_one()
        self.employee_ids.write({"hik_shift_id": self.shift_id.id})
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"type": "success", "next": {"type": "ir.actions.act_window_close"},
                       "message": _("%(n)s ta xodim «%(shift)s»ga biriktirildi.",
                                    n=len(self.employee_ids), shift=self.shift_id.name)},
        }


class HikAttendanceDaily(models.TransientModel):
    _name = "hik.attendance.daily"
    _description = "Kunlik davomat"

    date = fields.Date(string="Sana", required=True,
                       default=lambda self: datetime.now(pytz.timezone(SHOP_TZ)).date())
    shift_id = fields.Many2one("hik.work.shift", string="Smena")
    department_id = fields.Many2one("hr.department", string="Bo'lim")
    line_ids = fields.One2many("hik.attendance.daily.line", "wizard_id")

    def action_show(self):
        self.ensure_one()
        self.line_ids.unlink()
        tz = pytz.timezone(SHOP_TZ)
        day_start = tz.localize(datetime.combine(self.date, time())).astimezone(pytz.utc).replace(tzinfo=None)
        day_end = day_start + timedelta(days=1)
        emp_domain = [("hik_shift_id", "!=", False)]
        if self.shift_id:
            emp_domain.append(("hik_shift_id", "=", self.shift_id.id))
        if self.department_id:
            emp_domain.append(("department_id", "child_of", self.department_id.id))
        employees = self.env["hr.employee"].search(emp_domain)
        attendances = self.env["hr.attendance"].search([
            ("employee_id", "in", employees.ids),
            ("hik_planned_start", ">=", day_start), ("hik_planned_start", "<", day_end),
        ], order="check_in")
        by_employee = {}
        for att in attendances:
            by_employee.setdefault(att.employee_id.id, att)  # the first entry of the day
        lines = []
        for emp in employees:
            att = by_employee.get(emp.id)
            shift = emp.hik_shift_id
            workday = shift.is_workday(self.date.weekday())
            if att:
                status = att.hik_status
            elif workday:
                status = "absent"
            else:
                status = "offday"
            lines.append({
                "wizard_id": self.id, "employee_id": emp.id, "shift_id": shift.id,
                "department_id": emp.department_id.id, "status": status,
                "check_in": att.check_in if att else False, "check_out": att.check_out if att else False,
                "late_min": att.hik_late_min if att else 0, "early_min": att.hik_early_min if att else 0,
                "worked_hours": att.worked_hours if att else 0.0,
            })
        self.env["hik.attendance.daily.line"].create(lines)
        return {
            "type": "ir.actions.act_window",
            "name": _("Kunlik davomat — %s", self.date.strftime("%d.%m.%Y")),
            "res_model": "hik.attendance.daily.line", "view_mode": "list",
            "domain": [("wizard_id", "=", self.id)],
            "context": {"search_default_group_status": 1},
        }


class HikAttendanceDailyLine(models.TransientModel):
    _name = "hik.attendance.daily.line"
    _description = "Kunlik davomat qatori"
    _order = "status_order, shift_id, employee_id"

    wizard_id = fields.Many2one("hik.attendance.daily", ondelete="cascade")
    employee_id = fields.Many2one("hr.employee", string="Xodim")
    shift_id = fields.Many2one("hik.work.shift", string="Smena")
    department_id = fields.Many2one("hr.department", string="Bo'lim")
    status = fields.Selection([
        ("absent", "Kelmadi"), ("late", "Kechikdi"), ("late_early", "Kechikdi va erta ketdi"),
        ("early", "Erta ketdi"), ("ok", "O'z vaqtida"), ("offday", "Dam olish kuni"), ("none", "Smenasiz"),
    ], string="Holat")
    status_order = fields.Integer(compute="_compute_status_order", store=True)
    check_in = fields.Datetime(string="Kirdi")
    check_out = fields.Datetime(string="Chiqdi")
    late_min = fields.Integer(string="Kechikish (daq)", aggregator="sum")
    early_min = fields.Integer(string="Erta ketish (daq)", aggregator="sum")
    worked_hours = fields.Float(string="Ishlagan (soat)", aggregator="sum")

    @api.depends("status")
    def _compute_status_order(self):
        order = {"absent": 0, "late": 1, "late_early": 2, "early": 3, "ok": 4, "offday": 5, "none": 6}
        for line in self:
            line.status_order = order.get(line.status, 9)
