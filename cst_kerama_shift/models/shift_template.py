from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CstProductionShiftTemplate(models.Model):
    """Configurable shift slots: 1-smena 06-14, 2-smena 14-22, 3-smena 22-06."""

    _name = "cst.production.shift.template"
    _description = "Smena vaqti"
    _order = "sequence, id"

    name = fields.Char(string="Smena", required=True)
    sequence = fields.Integer(string="Raqami", default=1, required=True,
                              help="1, 2, 3 — oylik hisobotidagi «Smena» ustuniga shu raqam ketadi.")
    hour_from = fields.Float(string="Boshlanishi", required=True, default=6.0, help="Soat, masalan 6.0 = 06:00, 14.5 = 14:30.")
    hour_to = fields.Float(string="Tugashi", required=True, default=14.0)
    crosses_midnight = fields.Boolean(compute="_compute_crosses_midnight", string="Tun o'rtasidan o'tadi")
    color = fields.Integer(string="Rang")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", string="Kompaniya", default=lambda self: self.env.company)

    @api.depends("hour_from", "hour_to")
    def _compute_crosses_midnight(self):
        for template in self:
            template.crosses_midnight = template.hour_to <= template.hour_from

    @api.constrains("hour_from", "hour_to")
    def _check_hours(self):
        for template in self:
            if not (0 <= template.hour_from < 24 and 0 <= template.hour_to < 24):
                raise ValidationError(_("Smena soatlari 0 dan 24 gacha bo'lishi kerak."))

    @staticmethod
    def _hm(value):
        hours = int(value)
        minutes = int(round((value - hours) * 60))
        return hours, minutes

    def _window(self, date, tz_name):
        """(start, end) of this shift on ``date`` as naive UTC datetimes."""
        self.ensure_one()
        tz = pytz.timezone(tz_name or "Asia/Tashkent")
        h1, m1 = self._hm(self.hour_from)
        h2, m2 = self._hm(self.hour_to)
        start = tz.localize(datetime.combine(date, time(h1, m1)))
        end_date = date + timedelta(days=1) if self.crosses_midnight else date
        end = tz.localize(datetime.combine(end_date, time(h2, m2)))
        return (start.astimezone(pytz.utc).replace(tzinfo=None),
                end.astimezone(pytz.utc).replace(tzinfo=None))

    def _payroll_code(self):
        """The value the payroll «Smena» selection understands."""
        self.ensure_one()
        return str(self.sequence) if self.sequence in (1, 2, 3) else False

    def _label_hours(self):
        self.ensure_one()
        return "%02d:%02d–%02d:%02d" % (*self._hm(self.hour_from), *self._hm(self.hour_to))
