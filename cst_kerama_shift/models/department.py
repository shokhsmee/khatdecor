import json
from datetime import datetime

import pytz

from odoo import _, api, fields, models
from odoo.addons.base.models.res_partner import _tz_get
from odoo.exceptions import ValidationError


class CstProductionDepartment(models.Model):
    """A section of the shop: its lines, its manager, its people.

    The chain is Bosma -> Kesish -> Preslash. A department owns the work
    centers of its lines, and work is pulled into a shift by department: the
    work orders of the department's lines are its queue.
    """

    _name = "cst.production.department"
    _description = "Ishlab chiqarish bo'limi"
    _order = "sequence, id"

    name = fields.Char(string="Bo'lim", required=True)
    code = fields.Char(string="Kod", required=True, help="Qisqa kod: BOSMA, KESISH, PRESLASH.")
    sequence = fields.Integer(string="Zanjirdagi o'rni", default=10)
    color = fields.Integer(string="Rang")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", string="Kompaniya", required=True, default=lambda self: self.env.company)
    workcenter_ids = fields.One2many(
        "mrp.workcenter", "cst_department_id", string="Stanoklar (liniyalar)")
    workcenter_count = fields.Integer(compute="_compute_counts")
    manager_user_ids = fields.Many2many(
        "res.users", "cst_department_manager_rel", "department_id", "user_id",
        string="Menejerlar", domain=[("share", "=", False)],
        help="Shu bo'limda smena ochib-yopa oladigan foydalanuvchilar.")
    employee_ids = fields.Many2many(
        "hr.employee", "cst_department_employee_rel", "department_id", "employee_id",
        string="Doimiy xodimlar",
        help="Smena ochilganda ro'yxatda chiqadigan xodimlar; kelganlari Face ID bo'yicha belgilanadi.")
    output_kind = fields.Selection([
        ("semi", "Yarim tayyor mahsulot"),
        ("finished", "Tayyor mahsulot"),
    ], string="Chiqaradigan mahsulot", default="semi", required=True)
    tz = fields.Selection(_tz_get, string="Vaqt mintaqasi", default="Asia/Tashkent", required=True,
                          help="Smena soatlari shu mintaqa bo'yicha o'qiladi.")
    shift_template_ids = fields.Many2many(
        "cst.production.shift.template", "cst_department_shift_template_rel",
        "department_id", "template_id", string="Smena vaqtlari",
        default=lambda self: self.env["cst.production.shift.template"].search([]),
        help="Bo'limda ishlatiladigan smenalar. Bo'sh qolsa hammasi.")
    scrap_reason_tag_id = fields.Many2one(
        "stock.scrap.reason.tag", string="Brak sababi",
        help="Shu bo'limdan chiqqan brak scrap'ga shu sabab bilan yoziladi.")
    shift_ids = fields.One2many("cst.production.shift", "department_id", string="Smenalar")
    open_shift_id = fields.Many2one(
        "cst.production.shift", string="Ochiq smena", compute="_compute_open_shift")
    shift_count = fields.Integer(compute="_compute_counts")
    note = fields.Text(string="Izoh")
    # the dashboard card: what waits, what runs, what came out today
    queue_count = fields.Integer(string="Navbatda", compute="_compute_dashboard")
    running_count = fields.Integer(string="Liniyada", compute="_compute_dashboard")
    today_good = fields.Float(string="Bugun 1-sort", compute="_compute_dashboard", digits="Product Unit of Measure")
    today_scrap = fields.Float(string="Bugun brak", compute="_compute_dashboard", digits="Product Unit of Measure")
    today_planned = fields.Float(string="Bugun reja", compute="_compute_dashboard", digits="Product Unit of Measure")
    employee_count = fields.Integer(compute="_compute_dashboard")
    open_shift_label = fields.Char(compute="_compute_dashboard")
    late_count = fields.Integer(string="Kech", compute="_compute_dashboard")
    today_count = fields.Integer(string="Bugun", compute="_compute_dashboard")
    tomorrow_count = fields.Integer(string="Ertaga", compute="_compute_dashboard")
    # the same JSON Inventory feeds its per-day bar graph with, so its widget draws ours
    kanban_dashboard_graph = fields.Text(compute="_compute_dashboard")

    _GRAPH_BUCKETS = (
        ("before", "Kech", "past"), ("yesterday", "Kecha", "past"), ("today", "Bugun", "present"),
        ("day_1", "Ertaga", "future"), ("day_2", "Indinga", "future"), ("after", "Keyin", "future"))

    def _date_bucket(self, value):
        """before / yesterday / today / day_1 / day_2 / after, in the department's own time zone."""
        self.ensure_one()
        if not value:
            return "after"
        tz = pytz.timezone(self.tz or "Asia/Tashkent")
        local = pytz.utc.localize(value).astimezone(tz).date()
        delta = (local - datetime.now(tz).date()).days
        if delta < -1:
            return "before"
        return {-1: "yesterday", 0: "today", 1: "day_1", 2: "day_2"}.get(delta, "after")

    def _compute_dashboard(self):
        Floor = self.env["cst.production.floor"]
        for department in self:
            shift = department.open_shift_id
            today = Floor._today(department)
            lines_today = department.shift_ids.filtered(
                lambda s: s.date == today and s.state != "cancel").line_ids
            taken = shift.line_ids.filtered(lambda l: l.state in ("todo", "progress", "paused")).workorder_id \
                if shift else self.env["mrp.workorder"]
            department.queue_count = len(department._pending_workorders() - taken)
            department.running_count = len(shift.line_ids.filtered(lambda l: l.state in ("progress", "paused"))) if shift else 0
            department.today_good = sum(lines_today.mapped("qty_good"))
            department.today_scrap = sum(lines_today.mapped("qty_scrap"))
            department.today_planned = sum(lines_today.mapped("planned_qty"))
            department.employee_count = len(shift.employee_ids) if shift else len(department.employee_ids)
            department.open_shift_label = (
                "%s · %s–%s" % (shift.template_id.name, Floor._local(department, shift.date_start),
                                Floor._local(department, shift.date_end)) if shift else "")
            # every order still waiting for this department, by the day it is planned
            totals = {key: 0 for key, _l, _t in self._GRAPH_BUCKETS}
            for wo in department._pending_workorders():
                totals[department._date_bucket(wo.date_start or wo.production_id.date_start)] += 1
            department.late_count = totals["before"] + totals["yesterday"]
            department.today_count = totals["today"]
            department.tomorrow_count = totals["day_1"]
            empty = not any(totals.values())
            department.kanban_dashboard_graph = json.dumps([{
                "key": "Ma'lumot yo'q" if empty else "Buyurtmalar",
                "picking_type_id": None,
                "values": [{"label": label, "value": totals[key], "type": "sample" if empty else kind}
                           for key, label, kind in self._GRAPH_BUCKETS],
            }])

    @api.constrains("code", "company_id", "active")
    def _check_code_unique(self):
        for department in self.filtered("active"):
            twin = self.search_count([
                ("id", "!=", department.id), ("code", "=ilike", department.code),
                ("company_id", "=", department.company_id.id), ("active", "=", True)])
            if twin:
                raise ValidationError(_("«%s» kodli bo'lim allaqachon bor.", department.code))

    @api.depends("workcenter_ids", "shift_ids")
    def _compute_counts(self):
        for department in self:
            department.workcenter_count = len(department.workcenter_ids)
            department.shift_count = len(department.shift_ids)

    @api.depends("shift_ids.state")
    def _compute_open_shift(self):
        for department in self:
            department.open_shift_id = department.shift_ids.filtered(
                lambda s: s.state == "open").sorted("id")[-1:]

    # ------------------------------------------------------------------
    def _templates(self):
        self.ensure_one()
        return self.shift_template_ids or self.env["cst.production.shift.template"].search([])

    def _pending_workorders(self):
        """The department's queue: work orders on its lines that are not done."""
        self.ensure_one()
        return self.env["mrp.workorder"].search([
            ("workcenter_id", "in", self.workcenter_ids.ids),
            ("state", "not in", ("done", "cancel")),
            ("production_id.state", "in", ("confirmed", "progress", "to_close")),
        ], order="production_id, sequence, id")

    def action_view_shifts(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("%s — smenalar", self.name),
            "res_model": "cst.production.shift", "view_mode": "list,form",
            "domain": [("department_id", "=", self.id)],
            "context": {"default_department_id": self.id, "search_default_department_id": self.id},
        }

    def action_view_queue(self):
        """The orders waiting for this department, as a work-order list."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("%s — navbat", self.name),
            "res_model": "mrp.workorder", "view_mode": "list,form",
            "domain": [("id", "in", self._pending_workorders().ids)],
            "context": {"search_default_groupby_production": 0},
        }

    def action_view_today_entries(self):
        self.ensure_one()
        today = self.env["cst.production.floor"]._today(self)
        return {
            "type": "ir.actions.act_window", "name": _("%s — bugungi natijalar", self.name),
            "res_model": "cst.production.shift.entry", "view_mode": "list,pivot",
            "domain": [("department_id", "=", self.id), ("shift_id.date", "=", today)],
        }

    def action_open_floor(self):
        """The department's floor screen (OWL client action)."""
        self.ensure_one()
        return {
            "type": "ir.actions.client", "tag": "cst_shift_floor", "name": self.name,
            "params": {"department_id": self.id},
            "context": {"active_id": self.id, "active_model": self._name},
        }
