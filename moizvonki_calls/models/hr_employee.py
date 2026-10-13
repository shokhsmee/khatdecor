from odoo import api, fields, models

class HREmployee(models.Model):
    _inherit = "hr.employee"

    moizvonki_call_count = fields.Integer(
        string="Calls",
        compute="_compute_moizvonki_call_count",
    )

    def _compute_moizvonki_call_count(self):
        Call = self.env["moizvonki.call"].sudo()
        for emp in self:
            email = (emp.work_email or "").strip().lower()
            if not email:
                emp.moizvonki_call_count = 0
                continue
            emp.moizvonki_call_count = Call.search_count([
                ("user_login", "ilike", email),
            ])

    def action_open_moizvonki_calls(self):
        self.ensure_one()
        email = (self.work_email or "").strip().lower()
        action = self.env.ref("moizvonki_calls.action_moizvonki_calls").read()[0]
        action["domain"] = [("user_login", "ilike", email)] if email else [("id", "=", 0)]
        action["context"] = {
            **self.env.context,
            "search_default_group_by_employee_id": 0,
        }
        return action
