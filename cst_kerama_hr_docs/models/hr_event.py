"""A personnel movement: the hiring, the transfer, the dismissal.

The HR department's workbook keeps one register row per *event*, not per
person — 473 rows for 300 people — and the row carries everything the
documents of that event need: the order number, the date, the department and
position, and for a transfer the ones the employee moves to.  That is exactly
this model, with the documents of the event hanging off it.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .hr_doc_template import EVENT_KINDS

MONTHS_UZ = [
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr",
]


class CstHrEvent(models.Model):
    _name = "cst.hr.event"
    _description = "Kadr harakati"
    _order = "date desc, id desc"
    _inherit = ["mail.thread"]

    employee_id = fields.Many2one(
        "hr.employee", string="Xodim", required=True, ondelete="cascade",
        index=True, tracking=True)
    kind = fields.Selection(
        EVENT_KINDS, string="Harakat turi", required=True, default="kirish",
        tracking=True)
    date = fields.Date(
        string="Sana", required=True, default=fields.Date.context_today, tracking=True)
    date_text = fields.Char(
        string="Sana (so'z bilan)", compute="_compute_date_text",
        help="Hujjatlarda «03 avgust 2026 yil» ko'rinishida chiqadi.")

    order_no = fields.Char(string="Buyruq №", copy=False, tracking=True)
    contract_no = fields.Char(
        string="Shartnoma №", copy=False, tracking=True,
        help="Ishga qabulda — mehnat shartnomasi raqami, o'tkazishda — "
             "qo'shimcha kelishuv raqami.")

    department_id = fields.Many2one("hr.department", string="Bo'lim", tracking=True)
    job_title = fields.Char(string="Lavozim", tracking=True)
    new_department_id = fields.Many2one(
        "hr.department", string="Yangi bo'lim", tracking=True)
    new_job_title = fields.Char(string="Yangi lavozim", tracking=True)

    base_contract_date = fields.Date(
        string="Mehnat shartnomasi sanasi",
        help="Qo'shimcha kelishuv qaysi mehnat shartnomasiga tuzilayotgani.")
    base_contract_no = fields.Char(string="Mehnat shartnomasi raqami")
    compensation_days = fields.Integer(
        string="Foydalanilmagan ta'til kuni",
        help="Bo'shash buyrug'ida kompensatsiya bandini chiqaradi.  0 bo'lsa "
             "band umuman yozilmaydi.")

    document_ids = fields.One2many(
        "cst.hr.document", "event_id", string="Hujjatlar", copy=False)
    document_count = fields.Integer(compute="_compute_document_count")
    ready_count = fields.Integer(compute="_compute_document_count")

    company_id = fields.Many2one(
        "res.company", string="Kompaniya", required=True,
        default=lambda self: self.env.company)
    state = fields.Selection(
        [("draft", "Qoralama"), ("done", "Tasdiqlangan")],
        string="Holati", default="draft", required=True, readonly=True, tracking=True)
    note = fields.Text(string="Izoh")

    # ------------------------------------------------------------------
    @api.depends("date")
    def _compute_date_text(self):
        for event in self:
            date = event.date
            event.date_text = (
                f"{date.day:02d} {MONTHS_UZ[date.month - 1]} {date.year} yil"
                if date else "")

    @api.depends("document_ids.file")
    def _compute_document_count(self):
        for event in self:
            event.document_count = len(event.document_ids)
            event.ready_count = len(event.document_ids.filtered("file"))

    @api.onchange("employee_id", "kind")
    def _onchange_employee_id(self):
        """Fill in where the employee stands today — the documents start there."""
        for event in self:
            employee = event.employee_id
            if not employee:
                continue
            if not event.department_id:
                event.department_id = employee.department_id
            if not event.job_title:
                event.job_title = employee.job_title
            if event.kind == "otkazish" and not event.base_contract_no:
                hire = self.search([
                    ("employee_id", "=", employee._origin.id or employee.id),
                    ("kind", "=", "kirish"),
                ], order="date desc", limit=1)
                event.base_contract_no = hire.contract_no
                event.base_contract_date = hire.date

    # ------------------------------------------------------------------
    def _next_order_no(self):
        """«196-10/k» — the department's own shape: number, month, /k."""
        self.ensure_one()
        number = self.env["ir.sequence"].next_by_code("cst.hr.event.order") or "1"
        return f"{number}-{self.date.month:02d}/k"

    def _next_contract_no(self):
        self.ensure_one()
        if self.kind == "otkazish":
            base = self.order_no or self._next_order_no()
            return base[:-2] + "/qk" if base.endswith("/k") else base + "/qk"
        return self.env["ir.sequence"].next_by_code("cst.hr.event.contract") or ""

    @api.model_create_multi
    def create(self, vals_list):
        events = super().create(vals_list)
        # Loading the department's historical register must not burn through
        # this year's numbering: the rows carry the numbers they were given.
        numbering = not self.env.context.get("cst_skip_autonumber")
        for event in events:
            if numbering and not event.order_no:
                event.order_no = event._next_order_no()
            if numbering and not event.contract_no and event.kind != "boshash":
                event.contract_no = event._next_contract_no()
            event._sync_documents()
        return events

    def write(self, vals):
        result = super().write(vals)
        if "kind" in vals:
            self._sync_documents()
        return result

    def _sync_documents(self):
        """Give the event exactly the documents its kind calls for."""
        Template = self.env["cst.hr.doc.template"]
        Document = self.env["cst.hr.document"]
        for event in self:
            templates = Template.search([("kind", "=", event.kind)])
            present = event.document_ids.template_id
            for template in templates - present:
                Document.create({"event_id": event.id, "template_id": template.id})
            stale = event.document_ids.filtered(
                lambda d: d.template_id not in templates and not d.file)
            stale.unlink()

    # ------------------------------------------------------------------
    def action_generate_all(self):
        for event in self:
            event.document_ids.action_generate()
        return True

    def action_confirm(self):
        """Confirming is what moves the employee — the paper follows the fact."""
        for event in self.filtered(lambda e: e.state == "draft"):
            employee = event.employee_id
            if event.kind == "otkazish":
                if not (event.new_department_id or event.new_job_title):
                    # The historical register has transfer rows whose target was
                    # never written down.  Refusing them outright would leave the
                    # imported history in a draft state nobody can clear, so the
                    # load says so explicitly and the event confirms without
                    # moving anyone.
                    if not self.env.context.get("cst_allow_incomplete"):
                        raise UserError(_(
                            "«%s»: o'tkazish uchun yangi bo'lim yoki yangi lavozim "
                            "ko'rsatilishi kerak.", employee.display_name))
                    event.state = "done"
                    continue
                employee.write({
                    "department_id": (event.new_department_id
                                      or employee.department_id).id,
                    "job_title": event.new_job_title or employee.job_title,
                })
            elif event.kind == "kirish":
                employee.write({
                    "department_id": (event.department_id
                                      or employee.department_id).id,
                    "job_title": event.job_title or employee.job_title,
                    "active": True,
                })
            else:
                employee.action_archive()
            event.state = "done"
        return True

    def action_reset(self):
        self.filtered(lambda e: e.state == "done").write({"state": "draft"})
        return True

    def unlink(self):
        if any(event.state == "done" for event in self):
            raise UserError(_(
                "Tasdiqlangan kadr harakatini o'chirib bo'lmaydi — avval "
                "qoralamaga qaytaring."))
        return super().unlink()
