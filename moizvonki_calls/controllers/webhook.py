import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MoizvonkiWebhookController(http.Controller):

    @http.route("/moizvonki/webhook", type="jsonrpc", auth="public", methods=["POST"], csrf=False)
    def moizvonki_webhook(self, **kwargs):
        """
        Expected payload:
        {
          "webhook": {...},
          "event": {...}   (or event list, but docs show event: [данные события])
        }
        """
        payload = request.jsonrequest or {}
        ICP = request.env["ir.config_parameter"].sudo()

        # Optional simple secret check: send ?secret=... in webhook URL
        secret_cfg = (ICP.get_param("moizvonki.webhook_secret") or "").strip()
        secret_qs = (request.httprequest.args.get("secret") or "").strip()
        if secret_cfg and secret_qs != secret_cfg:
            _logger.warning("Moizvonki webhook rejected (bad secret).")
            return {"ok": False}

        webhook_meta = payload.get("webhook") or {}
        event = payload.get("event")

        # In docs, "event": [данные события] -> could be dict or list
        if isinstance(event, list):
            for ev in event:
                request.env["moizvonki.call"].sudo().ingest_webhook(webhook_meta, ev or {})
        elif isinstance(event, dict):
            request.env["moizvonki.call"].sudo().ingest_webhook(webhook_meta, event)
        else:
            _logger.warning("Moizvonki webhook payload missing event: %s", json.dumps(payload))
            return {"ok": False}

        return {"ok": True}
