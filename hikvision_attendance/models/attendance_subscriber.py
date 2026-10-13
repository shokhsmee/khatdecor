# -*- coding: utf-8 -*-
import logging
import threading

from odoo import fields, models

from . import telegram_api
from .res_config_settings import PARAM_TOKEN

_logger = logging.getLogger(__name__)


class HikvisionAttendanceSubscriber(models.Model):
    _name = "hikvision.attendance.subscriber"
    _description = "Hikvision Attendance Telegram Subscriber"
    _order = "create_date desc"
    _rec_name = "display_name"

    chat_id = fields.Char(required=True, index=True)
    telegram_username = fields.Char()
    first_name = fields.Char()
    last_name = fields.Char()
    active = fields.Boolean(default=True)
    registered_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    last_notified = fields.Datetime(readonly=True)
    display_name = fields.Char(compute="_compute_display_name", store=True)

    _sql_constraints = [
        ("unique_chat", "unique(chat_id)",
         "This Telegram chat is already subscribed."),
    ]

    def _compute_display_name(self):
        for rec in self:
            parts = [p for p in (rec.first_name, rec.last_name) if p]
            who = " ".join(parts) or (f"@{rec.telegram_username}" if rec.telegram_username else rec.chat_id)
            rec.display_name = who

    # ------------------------------------------------------------------
    # Notification dispatch (called from hr.attendance hooks)
    # ------------------------------------------------------------------
    def _broadcast(self, caption, image_b64=None):
        """Send a message (or photo+caption) to every active subscriber.

        Runs the actual HTTP calls in a daemon thread so the camera's
        webhook handler returns 200 OK immediately. We snapshot the data
        we need before the thread starts because Odoo's env/cursor are
        not safe to use from another thread.
        """
        token = self.env["ir.config_parameter"].sudo().get_param(PARAM_TOKEN)
        if not token:
            return
        subscribers = self.sudo().search([("active", "=", True)])
        if not subscribers:
            return

        chat_ids = subscribers.mapped("chat_id")

        def _worker():
            for cid in chat_ids:
                try:
                    if image_b64:
                        telegram_api.send_photo(token, cid, image_b64, caption=caption)
                    else:
                        telegram_api.send_message(token, cid, caption)
                except Exception as e:
                    _logger.warning("Hikvision bot: notify %s failed: %s", cid, e)

        # Stamp last_notified before launching (synchronous, single cursor)
        subscribers.write({"last_notified": fields.Datetime.now()})
        threading.Thread(target=_worker, daemon=True, name="hik-attn-tg").start()
