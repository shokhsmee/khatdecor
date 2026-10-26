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
    # KPI and brak are salary money: in the payroll currency (so'm)
    currency_id = fields.Many2one(related="company_id.cst_payroll_currency_id")
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
    # computed as superuser: the shift manager reads people as public profiles only
    attendance_employee_ids = fields.Many2many(
        "hr.employee", compute="_compute_attendance", string="Face ID bo'yicha kelganlar", compute_sudo=True)
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
    # payroll is not the production manager's business: counted as superuser,
    # the button itself is for payroll people only
    payroll_line_ids = fields.One2many("cst.payroll.line", compute="_compute_payroll_lines", string="Oylik qatorlari",
                                       compute_sudo=True)
    payroll_line_count = fields.Integer(compute="_compute_payroll_lines", compute_sudo=True)
    worker_ids = fields.One2many("cst.production.shift.worker", "shift_id", string="Xodimlar KPI")
    kpi_cost_ids = fields.Many2many(
        "stock.landed.cost", "cst_shift_kpi_cost_rel", "shift_id", "cost_id", string="KPI tannarx hujjatlari",
        readonly=True, copy=False)
    kpi_capitalized = fields.Monetary(
        string="Tannarxga qo'shilgan KPI", currency_field="currency_id", compute="_compute_kpi_capitalized",
        compute_sudo=True)
    kpi_cost_pending = fields.Boolean(
        string="KPI tannarxga o'tkazilishi kerak", copy=False, index=True,
        help="KPI o'zgardi, lekin hali mahsulot tannarxiga qo'shilmagan (har 10 daqiqada avtomatik o'tadi).")
    kpi_cost_note = fields.Char(string="Tannarx izohi", readonly=True, copy=False)
    can_edit_kpi = fields.Boolean(compute="_compute_can_edit_kpi")
    can_correct = fields.Boolean(compute="_compute_can_edit_kpi")
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

    # people clock in up to an hour or so before their shift (06:52 for 08:00)
    ARRIVAL_GRACE = timedelta(hours=2)

    @api.depends("date_start", "date_end", "department_id", "employee_ids")
    def _compute_attendance(self):
        """Who of this shift's people Face ID saw arrive for it.

        Only the department's staff and the shift's own crew count -- the
        terminal sees the whole factory -- and only a check-in made for this
        shift: from a little before its start up to its end. Someone still
        inside from the previous shift (checked in at 07:00, leaving 19:00)
        is not counted for the 17:00 shift.
        """
        Attendance = self.env["hr.attendance"].sudo()
        for shift in self:
            people = shift.department_id.employee_ids | shift.employee_ids
            if not shift.date_start or not people:
                shift.attendance_employee_ids = False
                continue
            records = Attendance.search([
                ("employee_id", "in", people.ids),
                ("check_in", ">=", shift.date_start - self.ARRIVAL_GRACE),
                ("check_in", "<", shift.date_end),
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

    @api.depends("kpi_cost_ids.state", "kpi_cost_ids.amount_total", "kpi_cost_ids.cst_kpi_pay_amount")
    def _compute_kpi_capitalized(self):
        # in the KPI's own currency: each cost remembers the so'm it carried,
        # a re-conversion of its dollars would leave a few so'm to post forever
        for shift in self:
            shift.kpi_capitalized = sum(
                cost.cst_kpi_pay_amount or cost.amount_total
                for cost in shift.kpi_cost_ids.filtered(lambda c: c.state == "done"))

    @api.depends_context("uid")
    def _compute_can_edit_kpi(self):
        hr = self.env["cst.production.shift.worker"]._can_edit_kpi()
        correct = self.env.user.has_group("cst_kerama_shift.group_doc_correction")
        for shift in self:
            shift.can_edit_kpi = hr
            shift.can_correct = correct

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

    def _cst_moment(self):
        """When the shift's results happened: now, or -- typed after the
        shift is over -- one minute before its end."""
        self.ensure_one()
        now = fields.Datetime.now()
        if self.date_end and now > self.date_end:
            return self.date_end - timedelta(minutes=1)
        return now

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

    def write(self, vals):
        # «Smena ochildi: 8 xodim» must still add up after the crew is edited:
        # every change of an opened shift's crew goes to the chatter
        before = {s.id: s.employee_ids for s in self if s.state != "draft"} if "employee_ids" in vals else {}
        result = super().write(vals)
        for shift in self.filtered(lambda s: s.id in before):
            old, new = before[shift.id], shift.employee_ids
            if old == new:
                continue
            bits = []
            if new - old:
                bits.append(_("qo'shildi: %s", ", ".join((new - old).sudo().mapped("name"))))
            if old - new:
                bits.append(_("chiqarildi: %s", ", ".join((old - new).sudo().mapped("name"))))
            shift.message_post(body=_("Smena xodimlari: %(old)s → %(new)s xodim (%(what)s).",
                                      old=len(old), new=len(new), what="; ".join(bits)))
        return result

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
                # (sudo: the shift manager has no read access to hr.employee)
                shift.sudo().employee_ids = (present & staff) or staff
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
        self._cst_set_workers(shares)
        self.write({
            "state": "closed", "closed_at": fields.Datetime.now(), "closed_by": self.env.user.id,
            "note": note or self.note,
        })
        self._cst_sync_payroll()
        self.invalidate_recordset(["payroll_line_ids", "payroll_line_count"])
        self.message_post(body=_(
            "Smena yopildi. 1-sort %(good)s, 2-sort %(second)s, brak %(scrap)s. KPI fondi %(kpi)s, jarima %(penalty)s.",
            good=self.qty_good, second=self.qty_second, scrap=self.qty_scrap,
            kpi=self.kpi_total, penalty=self.penalty_total))
        if self.kpi_cost_pending:
            # the cost price must never stop a shift from closing: on failure
            # the KPI stays pending, the cron and the button try again
            try:
                with self.env.cr.savepoint():
                    self._cst_post_kpi_cost()
            except Exception as error:  # noqa: BLE001 -- reported on the shift
                self.sudo().write({"kpi_cost_note": str(error)[:250]})
        return True

    # ------------------------------------------------------------------ KPI per worker
    def _cst_set_workers(self, shares):
        """The KPI rows of the closing shift: one per worker of the crew.

        The KPI amount is HR's to enter; a manager closing the shift only
        brings the crew and the brak penalty. Rows HR already filled (a shift
        reopened and closed again) keep their KPI.
        """
        self.ensure_one()
        hr = self.env["cst.production.shift.worker"]._can_edit_kpi()  # the real user, before sudo
        Worker = self.env["cst.production.shift.worker"].sudo()
        existing = {w.employee_id.id: w for w in self.worker_ids.sudo()}
        keep = Worker
        for employee, kpi_amount, penalty_amount in shares:
            values = {"penalty_amount": penalty_amount}
            if hr:
                values["kpi_amount"] = kpi_amount
            worker = existing.get(employee.id)
            if worker:
                worker.with_context(cst_no_sync=True).write(values)
            else:
                values.setdefault("kpi_amount", 0.0)
                worker = Worker.with_context(cst_no_sync=True).create(dict(values, shift_id=self.id, employee_id=employee.id))
            keep |= worker
        (self.worker_ids.sudo() - keep).with_context(cst_no_sync=True).unlink()
        self._cst_workers_changed()

    def _cst_workers_changed(self):
        """Totals follow the rows; the cost waits for the next KPI posting."""
        for shift in self:
            workers = shift.worker_ids.sudo()
            kpi = sum(workers.mapped("kpi_amount"))
            penalty = sum(workers.mapped("penalty_amount"))
            values = {}
            if shift.currency_id.compare_amounts(kpi, shift.kpi_total) != 0:
                values["kpi_total"] = kpi
            if shift.currency_id.compare_amounts(penalty, shift.penalty_total) != 0:
                values["penalty_total"] = penalty
            if shift.currency_id.compare_amounts(kpi, shift.kpi_capitalized) != 0:
                values["kpi_cost_pending"] = True
            if values:
                super(CstProductionShift, shift.sudo()).write(values)

    def _cst_sync_payroll(self):
        """Draft payroll lines of the shift = the KPI rows, always. Run as
        superuser: neither the shift manager nor HR needs payroll rights for it."""
        for shift in self.sudo().filtered(lambda s: s.state == "closed"):
            lines = self.env["cst.payroll.line"].sudo().search([
                ("source_model", "=", shift._name), ("source_id", "=", shift.id), ("state", "!=", "cancel")])
            wanted = [(w.employee_id, w.kpi_amount, w.penalty_amount) for w in shift.worker_ids.sudo()]
            current = sorted((l.employee_id.id, l.component_id.id, round(l.amount, 2)) for l in lines)
            if current == shift._cst_payroll_key(wanted):
                continue
            posted = lines.filtered(lambda l: l.state not in ("draft", "cancel"))
            if posted:
                raise UserError(_(
                    "%(shift)s: oylik qatorlari allaqachon tasdiqlangan (%(n)s ta). KPI yoki jarimani o'zgartirish uchun "
                    "avval oylikda ularni qoralamaga qaytaring.", shift=shift.display_name, n=len(posted)))
            lines.unlink()
            shift._post_payroll(wanted)
            shift.invalidate_recordset(["payroll_line_ids", "payroll_line_count"])

    def _cst_payroll_key(self, shares):
        kpi = self.env.ref("cst_kerama_shift.component_smena_kpi").id
        penalty = self.env.ref("cst_kerama_payroll.component_jarima").id
        key = []
        for employee, kpi_amount, penalty_amount in shares:
            if not self.currency_id.is_zero(kpi_amount):
                key.append((employee.id, kpi, round(abs(kpi_amount), 2)))
            if not self.currency_id.is_zero(penalty_amount):
                key.append((employee.id, penalty, round(abs(penalty_amount), 2)))
        return sorted(key)

    def action_fill_kpi_from_rates(self):
        """HR: put the suggested KPI (rate × 1-sort share) into every row."""
        Worker = self.env["cst.production.shift.worker"]
        if not Worker._can_edit_kpi():
            raise UserError(_("KPI'ni faqat HR kiritadi."))
        for shift in self:
            for worker in shift.worker_ids:
                worker.kpi_amount = worker.kpi_suggested
        return True

    def action_create_workers(self):
        """HR on a shift closed before the KPI rows existed: rows from the crew."""
        for shift in self.filtered(lambda s: s.state == "closed" and not s.worker_ids):
            payroll = shift.payroll_line_ids
            kpi_component = self.env.ref("cst_kerama_shift.component_smena_kpi")
            shares = []
            for employee in shift.employee_ids:
                mine = payroll.filtered(lambda l, e=employee: l.employee_id == e)
                shares.append((employee, sum(mine.filtered(lambda l: l.component_id == kpi_component).mapped("amount")),
                               sum((mine - mine.filtered(lambda l: l.component_id == kpi_component)).mapped("amount"))))
            shift.with_context(cst_keep_kpi=True)._cst_set_workers(shares)
        return True

    # ------------------------------------------------------------------ KPI → cost price
    def action_post_kpi_cost(self):
        self._cst_post_kpi_cost()
        return True

    @api.model
    def _cron_post_kpi_cost(self):
        """KPI typed by HR reaches the product cost within minutes, once a
        shift's rows have stopped changing."""
        quiet = fields.Datetime.subtract(fields.Datetime.now(), minutes=5)
        shifts = self.sudo().search([("kpi_cost_pending", "=", True), ("state", "=", "closed")])
        for shift in shifts:
            if shift.worker_ids and max(shift.worker_ids.mapped("write_date")) > quiet:
                continue
            try:
                with self.env.cr.savepoint():
                    shift._cst_post_kpi_cost()
            except Exception as error:  # one bad shift must not stop the others
                shift.sudo().write({"kpi_cost_note": str(error)[:250]})

    def _cst_kpi_targets(self):
        """(production, share) pairs: the shift's KPI goes to the products it
        made, in proportion to the 1-sort pieces of each line. Corrections
        made later travel with their line (correction orders count too)."""
        self.ensure_one()
        targets = []
        for line in self.line_ids.filtered(lambda l: l.is_final_operation and l.qty_good > 0):
            productions = (line.production_id | line.correction_production_ids).filtered(lambda p: p.state == "done")
            if productions:
                targets.append((productions, line.qty_good))
        return targets

    def _cst_post_kpi_cost(self):
        """Book the not-yet-capitalized KPI (positive or negative) as a landed
        cost on the shift's finished pieces: Dt stock valuation, Kt the salary
        expense the payroll line hits, so the KPI ends up in the cost price."""
        Cost = self.env["stock.landed.cost"].sudo()
        for shift in self.sudo():
            delta = shift.currency_id.round(shift.kpi_total - shift.kpi_capitalized)
            if shift.currency_id.is_zero(delta):
                shift.write({"kpi_cost_pending": False, "kpi_cost_note": False})
                continue
            targets = shift._cst_kpi_targets()
            if not targets:
                shift.write({"kpi_cost_pending": False, "kpi_cost_note": _(
                    "Tannarxga qo'shilmadi: smenada omborga tushgan 1-sort mahsulot yo'q.")})
                continue
            company = shift.company_id
            # the KPI is in so'm, the stock valuation in dollars
            delta_pay = delta
            if shift.currency_id != company.currency_id:
                rate = company._cst_payroll_rate(fields.Date.context_today(shift))
                if not rate or rate <= 0:
                    shift.write({"kpi_cost_note": _("Tannarxga qo'shilmadi: dollar kursi topilmadi.")})
                    continue
                delta = company.currency_id.round(delta_pay / rate)
                if company.currency_id.is_zero(delta):
                    shift.write({"kpi_cost_pending": False, "kpi_cost_note": False})
                    continue
            product = self.env.ref("cst_kerama_shift.product_kpi_cost").with_company(company)
            account = company.cst_salary_expense_cash_account_id or company.cst_salary_expense_account_id
            cost = Cost.with_company(company).create({
                "target_model": "manufacturing",
                "mrp_production_ids": [(6, 0, sum((p for p, _q in targets), self.env["mrp.production"]).ids)],
                "company_id": company.id,
                "date": fields.Date.context_today(shift),
                "description": _("Smena KPI: %s", shift.display_name),
                "cst_kpi_pay_amount": delta_pay,
                "cost_lines": [(0, 0, {
                    "product_id": product.product_variant_id.id if product._name == "product.template" else product.id,
                    "name": _("Smena KPI — %s", shift.display_name),
                    "price_unit": delta, "split_method": "equal",
                    "account_id": account.id if account else False,
                })],
            })
            cost.compute_landed_cost()
            shift._cst_spread_kpi(cost, targets, delta)
            cost.button_validate()
            shift.write({"kpi_cost_ids": [(4, cost.id)], "kpi_cost_pending": False, "kpi_cost_note": False})
            amount = company.currency_id.format(delta)
            if delta_pay != delta:
                amount = f"{shift.currency_id.format(delta_pay)} = {amount}"
            shift.message_post(body=_("KPI tannarxga qo'shildi: %(amount)s (%(doc)s).",
                                      amount=amount, doc=cost.name))

    def _cst_spread_kpi(self, cost, targets, delta):
        """Overwrite Odoo's split: by the line's 1-sort pieces, then within a
        line by finished-move quantity."""
        total = sum(q for _p, q in targets)
        currency = self.company_id.currency_id  # the cost's own currency, not the KPI's
        adjustments = cost.valuation_adjustment_lines
        by_move = {}
        for productions, qty in targets:
            moves = adjustments.filtered(lambda a: a.move_id.production_id in productions)
            moves_qty = sum(moves.mapped("quantity"))
            for adj in moves:
                share = delta * (qty / total) * (adj.quantity / moves_qty if moves_qty else 0.0)
                by_move[adj.id] = by_move.get(adj.id, 0.0) + share
        rows = list(adjustments)
        assigned = 0.0
        for i, adj in enumerate(rows):
            amount = currency.round(by_move.get(adj.id, 0.0))
            if i == len(rows) - 1:
                amount = currency.round(delta - assigned)  # rounding lands on the last row
            adj.additional_landed_cost = amount
            assigned += amount

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
            shift.sudo().employee_ids |= shift.attendance_employee_ids & shift.department_id.employee_ids
        return True
