import logging
import time
from datetime import datetime

import pytz

from odoo import api, fields, models
from odoo.http import request

_logger = logging.getLogger(__name__)

BUCKET = 300  # seconds: one bucket with any request = 5 active minutes


class CstUserActivity(models.Model):
    """Who worked in the program, on which day, from when to when, and for how
    long (ТЗ hisobot 41).

    Odoo keeps only an hourly device trace per session and vacuums it, so it
    cannot answer «how long did X work on Tuesday». Every request of a logged
    in user marks the five-minute slot it falls in; the first request of a new
    slot adds five minutes to the user's day. An open but idle browser tab
    sends nothing over HTTP (the client polls through the websocket), so it is
    not counted as work.
    """

    _name = "cst.user.activity"
    _description = "Foydalanuvchi faolligi"
    _order = "day desc, user_id"
    _rec_name = "user_id"

    user_id = fields.Many2one("res.users", string="Foydalanuvchi", required=True, index=True, ondelete="cascade")
    day = fields.Date(string="Kun", required=True, index=True)
    first_seen = fields.Datetime(string="Birinchi harakat")
    last_seen = fields.Datetime(string="Oxirgi harakat")
    active_minutes = fields.Integer(string="Faol vaqt (daq.)")
    requests = fields.Integer(string="So'rovlar")
    active_hours = fields.Float(string="Faol vaqt", compute="_compute_hours",
                               help="Kamida bitta amal bo'lgan 5 daqiqalik bo'laklar yig'indisi.")
    span_hours = fields.Float(string="Birinchi → oxirgi", compute="_compute_hours")

    @api.depends("active_minutes", "first_seen", "last_seen")
    def _compute_hours(self):
        for row in self:
            row.active_hours = (row.active_minutes or 0) / 60.0
            span = (row.last_seen - row.first_seen).total_seconds() / 3600.0 if row.first_seen and row.last_seen else 0.0
            row.span_hours = span

    _user_day_uniq = models.Constraint("unique(user_id, day)", "Bir foydalanuvchi uchun kuniga bitta qator.")

    @api.model
    def _cst_touch(self, uid, tz_name):
        """Record a request of ``uid`` now, on its own short transaction."""
        now = int(time.time())
        bucket = now // BUCKET
        session = request.session
        if session.get("_cst_act_bucket") == bucket:
            return
        session["_cst_act_bucket"] = bucket
        tz = pytz.timezone(tz_name or "Asia/Tashkent")
        stamp = datetime.utcfromtimestamp(now)
        day = pytz.utc.localize(stamp).astimezone(tz).date()
        try:
            with self.env.registry.cursor() as cr:
                cr.execute("""
                    INSERT INTO cst_user_activity
                           (user_id, day, first_seen, last_seen, active_minutes, requests,
                            create_uid, write_uid, create_date, write_date)
                    VALUES (%(uid)s, %(day)s, %(now)s, %(now)s, %(minutes)s, 1, 1, 1, %(now)s, %(now)s)
                    ON CONFLICT (user_id, day) DO UPDATE
                       SET last_seen = EXCLUDED.last_seen,
                           active_minutes = cst_user_activity.active_minutes + %(minutes)s,
                           requests = cst_user_activity.requests + 1,
                           write_date = EXCLUDED.write_date
                """, {"uid": uid, "day": day, "now": stamp, "minutes": BUCKET // 60})
        except Exception:  # never let the bookkeeping break the user's request
            _logger.debug("user activity not recorded", exc_info=True)


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _pre_dispatch(cls, rule, args):
        super()._pre_dispatch(rule, args)
        try:
            uid = request.session.uid
            if uid and request.env.registry.get("cst.user.activity") is not None \
                    and not request.httprequest.path.startswith(("/web/assets", "/web/static", "/web/image", "/websocket")):
                request.env["cst.user.activity"].sudo()._cst_touch(uid, request.session.context.get("tz"))
        except Exception:
            _logger.debug("user activity hook failed", exc_info=True)
