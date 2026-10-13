import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class CstTelegramController(http.Controller):
    """The one public door.

    Telegram signs every call with the secret handed to setWebhook, so the URL
    being public is not the same as the door being open.  Anything the bot
    cannot make sense of is still answered with 200: Telegram retries whatever
    is not, and a retry storm on one bad message is worse than a lost message.
    """

    @http.route("/telegram/webhook", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    def telegram_webhook(self, **kwargs):
        expected = (request.env["ir.config_parameter"].sudo()
                    .get_param("cst_kerama_telegram.webhook_secret") or "")
        given = request.httprequest.headers.get("X-Telegram-Bot-Api-Secret-Token") or ""
        if not expected or given != expected:
            _logger.warning("Telegram webhook called with a wrong secret from %s",
                            request.httprequest.remote_addr)
            return request.make_response("", status=403)

        try:
            update = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            _logger.warning("Telegram webhook received something that is not JSON")
            return request.make_response("", status=200)

        request.env["cst.telegram.bot"].sudo()._handle_update(update)
        return request.make_response("", status=200)
