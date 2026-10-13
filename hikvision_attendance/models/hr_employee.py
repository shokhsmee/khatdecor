from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    face_id = fields.Char(
        string="Face ID", index=True, copy=False, groups="hr.group_hr_user",
        help="Hikvision Face ID terminalidagi xodimning Employee ID raqami. Kamera "
             "voqeasi shu raqam bo'yicha xodimga bog'lanadi.")

    @api.constrains("face_id")
    def _check_face_id_unique(self):
        for employee in self.filtered("face_id"):
            twin = self.with_context(active_test=False).sudo().search(
                [("face_id", "=", employee.face_id), ("id", "!=", employee.id)], limit=1)
            if twin:
                raise ValidationError(_("Face ID «%(code)s» allaqachon %(name)s xodimiga berilgan.",
                                        code=employee.face_id, name=twin.name))

    def write(self, vals):
        if vals.get("face_id"):
            vals["face_id"] = vals["face_id"].strip()
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("face_id"):
                vals["face_id"] = vals["face_id"].strip()
        return super().create(vals_list)
