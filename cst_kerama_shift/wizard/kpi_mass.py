from collections import defaultdict

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

MODES = [
    ("suggested", "Reja bo'yicha (KPI narxi × bajarilish foizi)"),
    ("per_piece", "1 dona 1-sort uchun summa × xodim ulushi"),
    ("per_hour", "1 soat ish uchun summa × ishlagan soati"),
    ("fixed", "Har xodimga bir xil summa"),
    ("add", "Joriy summaga qo'shish / ayirish (±)"),
    ("percent", "Joriy summani foizga o'zgartirish (± %)"),
    ("clear", "Nolga tushirish"),
]


class CstShiftKpiMassWizard(models.TransientModel):
    """«KPI ommaviy kiritish» — HR fills or changes the KPI (or the penalty) of
    many shift workers at once instead of row by row.

    Pick the rows (period, departments, shift times, people — or the rows
    ticked in «Smena KPI»), pick how the amount is found, press «Hisoblash»:
    every row shows its current and its new amount and can still be edited by
    hand. «Qo'llash» writes them, then each touched shift rewrites its draft
    payroll lines and queues the KPI for the cost price — once per shift."""

    _name = "cst.shift.kpi.mass.wizard"
    _description = "KPI ommaviy kiritish"

    date_from = fields.Date(string="Davr boshi", default=lambda self: fields.Date.start_of(
        fields.Date.context_today(self), "month"))
    date_to = fields.Date(string="Davr oxiri", default=fields.Date.context_today)
    department_ids = fields.Many2many("cst.production.department", string="Bo'limlar",
                                      help="Bo'sh = hamma bo'limlar.")
    template_ids = fields.Many2many("cst.production.shift.template", string="Smena vaqtlari",
                                    help="Bo'sh = hamma smenalar.")
    employee_ids = fields.Many2many("hr.employee", string="Xodimlar", help="Bo'sh = hamma xodimlar.")
    worker_ids = fields.Many2many("cst.production.shift.worker", string="Tanlangan qatorlar",
                                  help="«Smena KPI» ro'yxatida belgilangan qatorlar; bo'lsa — faqat shular.")
    only_empty = fields.Boolean(string="Faqat hali kiritilmaganlar", default=True,
                                help="Summasi 0 bo'lgan qatorlar (KPI yoki jarima — tanlanganiga qarab). "
                                     "O'chirilsa, kiritilganlari ham qayta yoziladi.")
    target = fields.Selection([("kpi", "KPI"), ("penalty", "Jarima")], string="Nima o'zgaradi",
                              default="kpi", required=True)
    mode = fields.Selection(MODES, string="Qanday hisoblanadi", default="suggested", required=True)
    value = fields.Float(string="Qiymat", digits=(16, 2),
                         help="Summa, stavka yoki foiz — tanlangan usulga qarab.")
    note = fields.Char(string="Izoh", help="Bo'sh bo'lmasa, har qatorning izohiga yoziladi.")
    line_ids = fields.One2many("cst.shift.kpi.mass.line", "wizard_id", string="Qatorlar")
    line_count = fields.Integer(compute="_compute_totals")
    total_current = fields.Float(string="Hozir jami", compute="_compute_totals")
    total_new = fields.Float(string="Yangi jami", compute="_compute_totals")
    skipped_note = fields.Char(readonly=True)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        ctx = self.env.context
        if ctx.get("active_model") == "cst.production.shift.worker" and ctx.get("active_ids"):
            values["worker_ids"] = [(6, 0, ctx["active_ids"])]
            values["date_from"] = False
            values["date_to"] = False
            values["only_empty"] = False  # the ticked rows are the choice
        return values

    @api.depends("line_ids.current", "line_ids.new_amount")
    def _compute_totals(self):
        for wizard in self:
            wizard.line_count = len(wizard.line_ids)
            wizard.total_current = sum(wizard.line_ids.mapped("current"))
            wizard.total_new = sum(wizard.line_ids.mapped("new_amount"))

    def _check_rights(self):
        if not self.env["cst.production.shift.worker"]._can_edit_kpi():
            raise UserError(_("Xodimlar KPI va jarimasini faqat HR o'zgartiradi."))

    def _workers(self):
        self.ensure_one()
        domain = [("shift_state", "=", "closed")]
        if self.worker_ids:
            domain.append(("id", "in", self.worker_ids.ids))
        if self.date_from:
            domain.append(("shift_date", ">=", self.date_from))
        if self.date_to:
            domain.append(("shift_date", "<=", self.date_to))
        if self.department_ids:
            domain.append(("department_id", "in", self.department_ids.ids))
        if self.template_ids:
            domain.append(("template_id", "in", self.template_ids.ids))
        if self.employee_ids:
            domain.append(("employee_id", "in", self.employee_ids.ids))
        if self.only_empty:
            domain.append(("kpi_amount" if self.target == "kpi" else "penalty_amount", "=", 0))
        return self.env["cst.production.shift.worker"].search(domain)

    def _new_amount(self, worker, current):
        value = self.value or 0.0
        if self.mode == "suggested":
            # no rate for this work: keep what HR wrote rather than wipe it
            return worker.kpi_suggested if worker.kpi_suggested else current
        if self.mode == "per_piece":
            return worker.qty_good * value
        if self.mode == "per_hour":
            return worker.minutes / 60.0 * value
        if self.mode == "fixed":
            return value
        if self.mode == "add":
            return current + value
        if self.mode == "percent":
            return current * (1 + value / 100.0)
        return 0.0

    def action_compute(self):
        self.ensure_one()
        self._check_rights()
        workers = self._workers()
        if not workers:
            raise UserError(_("Tanlangan shartlarga mos yopilgan smena qatori topilmadi."))
        field = "kpi_amount" if self.target == "kpi" else "penalty_amount"
        lines = [(5, 0, 0)]
        for worker in workers:
            current = worker[field]
            new = self._new_amount(worker, current)
            if worker.currency_id:
                new = worker.currency_id.round(new)
            lines.append((0, 0, {"worker_id": worker.id, "current": current, "new_amount": max(new, 0.0)}))
        self.line_ids = lines
        return self._reopen()

    def action_apply(self):
        self.ensure_one()
        self._check_rights()
        if not self.line_ids:
            self.action_compute()
        field = "kpi_amount" if self.target == "kpi" else "penalty_amount"
        changed = defaultdict(list)
        for line in self.line_ids:
            worker = line.worker_id
            if not worker.exists() or worker.shift_id.state != "closed":
                continue
            values = {}
            if worker.currency_id.compare_amounts(line.new_amount, worker[field]) != 0:
                values[field] = line.new_amount
                if field == "kpi_amount":
                    # an amount typed here is a hand correction: the plan recount keeps it
                    values["kpi_manual"] = self.mode != "suggested"
            if self.note:
                values["note"] = self.note
            if values:
                old = worker[field]
                worker.with_context(cst_no_sync=True).write(values)
                changed[worker.shift_id].append((worker.employee_name, old, line.new_amount))
        what = _("KPI") if self.target == "kpi" else _("Jarima")
        for shift, rows in changed.items():
            shift._cst_workers_changed()
            shift._cst_sync_payroll()
            items = Markup("").join(Markup("<li>%s: %s → %s</li>") % row for row in rows)
            shift.sudo().message_post(body=Markup("%s %s (%s):<ul>%s</ul>") % (
                _("Ommaviy o'zgartirildi:"), what, self.env.user.name, items))
        count = sum(len(rows) for rows in changed.values())
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {
                "title": _("KPI ommaviy kiritish"),
                "message": _("%(count)s ta qator o'zgardi, %(shifts)s ta smena oyligi yangilandi.",
                             count=count, shifts=len(changed)),
                "type": "success", "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _reopen(self):
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new", "name": _("KPI ommaviy kiritish")}


class CstShiftKpiMassLine(models.TransientModel):
    _name = "cst.shift.kpi.mass.line"
    _description = "KPI ommaviy kiritish qatori"
    _order = "shift_date desc, department_id, employee_name"

    wizard_id = fields.Many2one("cst.shift.kpi.mass.wizard", required=True, ondelete="cascade")
    worker_id = fields.Many2one("cst.production.shift.worker", required=True, ondelete="cascade")
    shift_date = fields.Date(related="worker_id.shift_date")
    department_id = fields.Many2one(related="worker_id.department_id")
    template_id = fields.Many2one(related="worker_id.template_id")
    employee_name = fields.Char(related="worker_id.employee_name")
    qty_good = fields.Float(related="worker_id.qty_good")
    minutes = fields.Float(related="worker_id.minutes")
    kpi_suggested = fields.Monetary(related="worker_id.kpi_suggested")
    currency_id = fields.Many2one(related="worker_id.currency_id")
    current = fields.Float(string="Hozir", digits=(16, 2))
    new_amount = fields.Float(string="Yangi", digits=(16, 2))


class CstKpiRateMassWizard(models.TransientModel):
    """«KPI stavkalarini ommaviy o'rnatish» — one rate for many rows at once,
    in any of the three rate tables the company uses:

    * **smena** (cst.shift.kpi.rate) — per department / line, for a category or
      each chosen product; dated, so a change is a new row from that day;
    * **sotuv** — product.template.cst_kpi_rate (sales manager, per unit sold);
    * **ishbay** — mrp.routing.workcenter.cst_kpi_rate (per BoM operation).

    The value can replace the rate, be added (±) or change it by a percentage."""

    _name = "cst.kpi.rate.mass.wizard"
    _description = "KPI stavkalarini ommaviy o'rnatish"

    kind = fields.Selection([
        ("shift", "Smena KPI stavkasi (1 dona 1-sort uchun)"),
        ("sale", "Sotuv KPI stavkasi (1 dona sotilgan mahsulot uchun)"),
        ("operation", "Ishbay stavkasi (texkarta operatsiyasi bo'yicha)"),
    ], string="Qaysi stavka", default="shift", required=True)
    department_ids = fields.Many2many("cst.production.department", string="Bo'limlar")
    workcenter_ids = fields.Many2many("mrp.workcenter", string="Liniyalar",
                                      help="Smena: bo'sh = bo'limning hamma liniyalari uchun bitta stavka. "
                                           "Ishbay: bo'sh = hamma liniyalar.")
    categ_ids = fields.Many2many("product.category", string="Kategoriyalar",
                                 help="Ichki kategoriyalar ham kiradi.")
    product_tmpl_ids = fields.Many2many("product.template", string="Mahsulotlar")
    per_product = fields.Boolean(
        string="Har mahsulotga alohida qator",
        help="Smena stavkasi: belgilansa kategoriyadagi har mahsulotga alohida stavka qatori yoziladi; "
             "aks holda kategoriyaning o'ziga bitta qator.")
    operation = fields.Selection(selection="_operation_names", string="Operatsiya",
                                 help="Ishbay: bo'sh = hamma operatsiyalar.")
    mode = fields.Selection([("set", "Shu qiymatga o'rnatish"), ("add", "Joriy stavkaga qo'shish (±)"),
                             ("percent", "Foizga o'zgartirish (± %)")],
                            string="Usul", default="set", required=True)
    value = fields.Float(string="Qiymat", digits=(16, 2), required=True)
    date_from = fields.Date(string="Amal qiladi (dan)", default=fields.Date.context_today,
                            help="Smena stavkasi: shu sanadan yangi qator; eski smenalar eski stavkada qoladi.")
    preview = fields.Text(string="Natija", readonly=True)

    @api.model
    def _operation_names(self):
        self.env.cr.execute("SELECT DISTINCT name FROM mrp_routing_workcenter WHERE active ORDER BY name")
        return [(name, name) for (name,) in self.env.cr.fetchall() if name]

    def _check_rights(self):
        user = self.env.user
        if not (self.env.su or user.has_group("hr.group_hr_user") or user.has_group("base.group_system")
                or user.has_group("cst_kerama_shift.group_shift_admin")):
            raise UserError(_("KPI stavkalarini faqat HR yoki administrator o'zgartiradi."))

    def _new(self, current):
        if self.mode == "add":
            return max(current + self.value, 0.0)
        if self.mode == "percent":
            return max(current * (1 + self.value / 100.0), 0.0)
        return self.value

    def _templates(self):
        Template = self.env["product.template"]
        templates = self.product_tmpl_ids
        if self.categ_ids:
            templates |= Template.search([("categ_id", "child_of", self.categ_ids.ids)])
        return templates

    def action_apply(self):
        self.ensure_one()
        self._check_rights()
        count = getattr(self, "_apply_%s" % self.kind)()
        self.preview = _("%s ta stavka yozildi.", count)
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": _("KPI stavkalari"), "message": self.preview, "type": "success",
                       "next": {"type": "ir.actions.act_window_close"}},
        }

    def _apply_sale(self):
        templates = self._templates()
        if not templates:
            raise UserError(_("Kategoriya yoki mahsulot tanlang."))
        for template in templates.sudo():  # rights checked above; HR has no product rights
            template.cst_kpi_rate = self._new(template.cst_kpi_rate)
        return len(templates)

    def _apply_operation(self):
        domain = []
        templates = self._templates()
        if templates:
            domain.append(("bom_id.product_tmpl_id", "in", templates.ids))
        if self.workcenter_ids:
            domain.append(("workcenter_id", "in", self.workcenter_ids.ids))
        if self.department_ids:
            domain.append(("workcenter_id.cst_department_id", "in", self.department_ids.ids))
        if self.operation:
            domain.append(("name", "=", self.operation))
        if not domain:
            raise UserError(_("Hamma texkartalarga birdan yozilmaydi: bo'lim, liniya, kategoriya, mahsulot "
                              "yoki operatsiyadan kamida bittasini tanlang."))
        operations = self.env["mrp.routing.workcenter"].sudo().search(domain)
        for operation in operations:
            operation.cst_kpi_rate = self._new(operation.cst_kpi_rate)
        return len(operations)

    def _apply_shift(self):
        if not self.department_ids:
            raise UserError(_("Smena stavkasi uchun bo'limni tanlang."))
        if not self.date_from:
            raise UserError(_("Stavka qaysi sanadan amal qilishini kiriting."))
        Rate = self.env["cst.shift.kpi.rate"]
        if self.per_product:
            targets = [(t, False) for t in self._templates()]
            if not targets:
                raise UserError(_("Kategoriya yoki mahsulot tanlang."))
        else:
            targets = [(t, False) for t in self.product_tmpl_ids] + [(False, c) for c in self.categ_ids]
            targets = targets or [(False, False)]
        count = 0
        for department in self.department_ids:
            lines = self.workcenter_ids.filtered(lambda w: w.cst_department_id == department) or [False]
            for workcenter in lines:
                for template, categ in targets:
                    key = [("department_id", "=", department.id),
                           ("workcenter_id", "=", workcenter.id if workcenter else False),
                           ("product_tmpl_id", "=", template.id if template else False),
                           ("categ_id", "=", categ.id if categ else False)]
                    current = Rate.search(key + [("date_from", "<=", self.date_from)],
                                          order="date_from desc, id desc", limit=1)
                    new = self._new(current.rate if current else 0.0)
                    same_day = Rate.search(key + [("date_from", "=", self.date_from)], limit=1)
                    if same_day:
                        same_day.rate = new
                    else:
                        Rate.create({
                            "department_id": department.id,
                            "workcenter_id": workcenter.id if workcenter else False,
                            "product_tmpl_id": template.id if template else False,
                            "categ_id": categ.id if categ else False,
                            "rate": new, "date_from": self.date_from,
                            "note": _("Ommaviy o'rnatildi"),
                        })
                    count += 1
        return count
