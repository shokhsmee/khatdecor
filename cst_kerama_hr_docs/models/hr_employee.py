"""The personal data the hiring documents ask for, and the Hujjatlar tab."""
from odoo import _, api, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    cst_passport_issuer = fields.Char(
        string="Pasport kim tomonidan berilgan", groups="hr.group_hr_user",
        tracking=True,
        help="Buyruq va arizada shu matn chop etiladi, masalan «Bag'dod tumani IIB».")
    cst_region = fields.Char(string="Viloyat", groups="hr.group_hr_user")
    cst_district = fields.Char(string="Tuman", groups="hr.group_hr_user")
    cst_mfy = fields.Char(string="MFY", groups="hr.group_hr_user")
    cst_street_name = fields.Char(string="Ko'cha", groups="hr.group_hr_user")
    cst_full_address = fields.Char(
        string="To'liq manzil", compute="_compute_cst_full_address", store=True,
        readonly=False, groups="hr.group_hr_user",
        help="Hujjatlarga tushadigan manzil.  Bo'laklardan o'zi yig'iladi, "
             "lekin qo'lda ham yozish mumkin.")

    cst_event_ids = fields.One2many(
        "cst.hr.event", "employee_id", string="Kadr harakatlari",
        groups="hr.group_hr_user")
    # The Hujjatlar tab keeps the three kinds apart the way the paper file
    # does — a hiring folder, a transfer folder, a dismissal folder — so one
    # o2m per kind rather than one list the user has to group by hand.
    cst_event_hire_ids = fields.One2many(
        "cst.hr.event", "employee_id", string="Ishga qabul",
        domain=[("kind", "=", "kirish")], context={"default_kind": "kirish"},
        groups="hr.group_hr_user")
    cst_event_transfer_ids = fields.One2many(
        "cst.hr.event", "employee_id", string="O'tkazish",
        domain=[("kind", "=", "otkazish")], context={"default_kind": "otkazish"},
        groups="hr.group_hr_user")
    cst_event_leave_ids = fields.One2many(
        "cst.hr.event", "employee_id", string="Bo'shatish",
        domain=[("kind", "=", "boshash")], context={"default_kind": "boshash"},
        groups="hr.group_hr_user")
    cst_event_count = fields.Integer(
        compute="_compute_cst_event_count", groups="hr.group_hr_user")
    cst_document_count = fields.Integer(
        compute="_compute_cst_event_count", groups="hr.group_hr_user")

    @api.depends("cst_region", "cst_district", "cst_mfy", "cst_street_name")
    def _compute_cst_full_address(self):
        for employee in self:
            parts = [
                (employee.cst_region, "viloyati"),
                (employee.cst_district, "tumani"),
                (employee.cst_mfy, "MFY"),
                (employee.cst_street_name, "ko'chasi"),
            ]
            employee.cst_full_address = " ".join(
                f"{value.strip()} {word}" for value, word in parts if value and value.strip())

    @api.depends("cst_event_ids", "cst_event_ids.document_ids.file")
    def _compute_cst_event_count(self):
        for employee in self:
            documents = employee.cst_event_ids.document_ids
            employee.cst_event_count = len(employee.cst_event_ids)
            employee.cst_document_count = len(documents.filtered("file"))

    def action_open_hr_events(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Kadr harakatlari — %s", self.display_name),
            "res_model": "cst.hr.event",
            "view_mode": "list,form",
            "domain": [("employee_id", "=", self.id)],
            "context": {"default_employee_id": self.id},
        }
