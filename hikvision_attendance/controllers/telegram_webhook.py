# -*- coding: utf-8 -*-
"""Telegram webhook endpoint.

Telegram POSTs every update here. We only handle `/start [token]` for admin
registration; everything else gets a polite reply.
"""
import json
import logging

from odoo import http
from odoo.http import request

from ..models import telegram_api

_logger = logging.getLogger(__name__)


def _icp(key, default=""):
    return request.env["ir.config_parameter"].sudo().get_param(key, default)


class HikvisionAttendanceBotWebhook(http.Controller):

    @http.route(
        "/hikvision_attendance/telegram/webhook",
        type="http", auth="public", methods=["POST"], csrf=False,
    )
    def webhook(self, **kwargs):
        # Verify Telegram's secret header (rejects bogus callers)
        stored_secret = _icp("hikvision_attendance.webhook_secret")
        sent_secret = request.httprequest.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if stored_secret and stored_secret != sent_secret:
            _logger.warning("Hikvision bot: webhook secret mismatch")
            return request.make_response("forbidden", status=403)

        try:
            update = json.loads(request.httprequest.data or b"{}")
        except ValueError:
            return request.make_response("bad json", status=400)

        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = (message.get("text") or "").strip()
        from_user = message.get("from") or {}

        if not chat_id:
            return request.make_response("OK", status=200)

        token = _icp("hikvision_attendance.bot_token")

        if text.startswith("/start"):
            self._handle_start(token, chat, from_user, text)
        elif text == "/stop":
            self._handle_stop(token, chat_id)
        elif text == "/whoami":
            self._handle_whoami(token, chat_id)
        else:
            telegram_api.send_message(
                token, chat_id,
                "Use this link from your admin to register:\n"
                "ask the school director for the invite link.",
            )

        return request.make_response("OK", status=200)

    # ------------------------------------------------------------------
    def _handle_start(self, token, chat, from_user, text):
        chat_id = chat.get("id")
        parts = text.split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        expected = _icp("hikvision_attendance.bot_invite_token")
        if not expected or arg != expected:
            telegram_api.send_message(
                token, chat_id,
                "❌ Noto'g'ri yoki yo'q kirish kodi.\n"
                "Iltimos, admindan to'g'ri taklif havolasini so'rang.",
            )
            return

        Sub = request.env["hikvision.attendance.subscriber"].sudo()
        sub = Sub.search([("chat_id", "=", str(chat_id))], limit=1)
        vals = {
            "chat_id": str(chat_id),
            "telegram_username": from_user.get("username") or "",
            "first_name": from_user.get("first_name") or "",
            "last_name": from_user.get("last_name") or "",
            "active": True,
        }
        if sub:
            sub.write(vals)
        else:
            Sub.create(vals)

        telegram_api.send_message(
            token, chat_id,
            "✅ Siz davomat botiga admin sifatida ulandingiz.\n"
            "Hodimlar Kirish/Chiqish qilganda, siz bu yerga bildirishnoma olasiz.\n\n"
            "To'xtatish uchun: /stop",
        )

    def _handle_stop(self, token, chat_id):
        Sub = request.env["hikvision.attendance.subscriber"].sudo()
        sub = Sub.search([("chat_id", "=", str(chat_id))], limit=1)
        if sub:
            sub.active = False
            telegram_api.send_message(token, chat_id,
                                      "🔕 Bildirishnomalar to'xtatildi.")
        else:
            telegram_api.send_message(token, chat_id,
                                      "Siz ro'yxatda emassiz.")

    def _handle_whoami(self, token, chat_id):
        Sub = request.env["hikvision.attendance.subscriber"].sudo()
        sub = Sub.search([("chat_id", "=", str(chat_id))], limit=1)
        if sub and sub.active:
            telegram_api.send_message(
                token, chat_id,
                f"✅ Faol admin: {sub.display_name}\n"
                f"Ro'yxatdan o'tgan: {sub.registered_at}",
            )
        else:
            telegram_api.send_message(token, chat_id, "❌ Ro'yxatda emassiz.")
