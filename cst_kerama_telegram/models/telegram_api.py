import logging

import requests

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TIMEOUT = 20
BASE = "https://api.telegram.org"


class CstTelegramApi(models.AbstractModel):
    """The Bot API, kept to the four calls this module actually makes.

    Nothing here raises at the caller by default: a bot that cannot reach
    Telegram must not be able to roll back an invoice or a broadcast.  Callers
    that genuinely need to know — setting the webhook from Settings — ask for
    it with ``raise_on_error``.
    """

    _name = "cst.telegram.api"
    _description = "Telegram Bot API"

    def _token(self):
        return (self.env["ir.config_parameter"].sudo()
                .get_param("cst_kerama_telegram.bot_token") or "").strip()

    def _secret(self):
        return (self.env["ir.config_parameter"].sudo()
                .get_param("cst_kerama_telegram.webhook_secret") or "").strip()

    def _call(self, method, payload=None, files=None, raise_on_error=False):
        token = self._token()
        if not token:
            if raise_on_error:
                raise UserError(_(
                    "Telegram бот токени киритилмаган.\n\n"
                    "Созламалар ▸ Бухгалтерия ▸ Telegram бот булимига @BotFather "
                    "берган токенни ёзинг."))
            _logger.info("Telegram call %s skipped: no bot token configured", method)
            return None

        url = f"{BASE}/bot{token}/{method}"
        try:
            if files:
                response = requests.post(url, data=payload or {}, files=files, timeout=TIMEOUT)
            else:
                response = requests.post(url, json=payload or {}, timeout=TIMEOUT)
            result = response.json()
        except Exception as error:            # noqa: BLE001 - network, json, anything
            _logger.warning("Telegram %s failed: %s", method, error)
            if raise_on_error:
                raise UserError(_("Telegram билан алока йук: %s", error)) from error
            return None

        if not result.get("ok"):
            _logger.warning("Telegram %s refused: %s", method, result.get("description"))
            if raise_on_error:
                raise UserError(_("Telegram рад этди: %s", result.get("description")))
            return None
        return result.get("result")

    # ------------------------------------------------------------------
    # The calls
    # ------------------------------------------------------------------
    def send_message(self, chat_id, text, keyboard=None, remove_keyboard=False):
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if keyboard is not None:
            payload["reply_markup"] = keyboard
        elif remove_keyboard:
            payload["reply_markup"] = {"remove_keyboard": True}
        return self._call("sendMessage", payload)

    def answer_callback(self, callback_id, text=None):
        payload = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text
        return self._call("answerCallbackQuery", payload)

    def send_document(self, chat_id, filename, content, caption=None):
        payload = {"chat_id": chat_id}
        if caption:
            payload["caption"] = caption
            payload["parse_mode"] = "HTML"
        return self._call(
            "sendDocument", payload,
            files={"document": (filename, content, "application/pdf")})

    def get_me(self, raise_on_error=True):
        return self._call("getMe", raise_on_error=raise_on_error)

    def set_webhook(self, url, secret):
        return self._call("setWebhook", {
            "url": url,
            "secret_token": secret,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": True,
        }, raise_on_error=True)

    def delete_webhook(self):
        return self._call("deleteWebhook", {"drop_pending_updates": True},
                          raise_on_error=True)

    def get_webhook_info(self, raise_on_error=True):
        return self._call("getWebhookInfo", raise_on_error=raise_on_error)
