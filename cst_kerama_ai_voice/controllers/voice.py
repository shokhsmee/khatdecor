import io
import json
import logging

import requests

from odoo import _, http
from odoo.http import request

_logger = logging.getLogger(__name__)

ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"
TIMEOUT = 120
MAX_BYTES = 20 * 1024 * 1024        # OpenAI's own limit is 25 MB
ALLOWED = ("audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav",
           "audio/x-m4a", "audio/mp3", "video/webm")


class CstAiVoiceController(http.Controller):
    """Turn a recording from the AI composer into text.

    The transcription runs server-side so the OpenAI key never leaves Odoo —
    the browser only ever sends the audio to its own server.
    """

    @http.route("/cst_ai_voice/transcribe", type="http", auth="user",
                methods=["POST"], csrf=True)
    def transcribe(self, **kwargs):
        upload = request.httprequest.files.get("audio")
        if not upload:
            return self._json({"error": _("Овоз файли юборилмади.")}, 400)

        raw = upload.read()
        if not raw:
            return self._json({"error": _("Ёзув буш чикди.")}, 400)
        if len(raw) > MAX_BYTES:
            return self._json({"error": _(
                "Ёзув жуда узун (%s MB).  Кискарок гапиринг.",
                round(len(raw) / 1024 / 1024, 1))}, 400)
        mimetype = (upload.mimetype or "").split(";")[0]
        if mimetype and mimetype not in ALLOWED:
            return self._json({"error": _("Кутилмаган формат: %s", mimetype)}, 400)

        provider = request.env["muk_ai.provider"].sudo().search(
            [("name", "=", "openai")], limit=1)
        api_key = provider.api_key if provider else None
        if not api_key:
            return self._json({"error": _(
                "OpenAI калити топилмади.  AI созламаларида уни киритинг.")}, 400)

        params = request.env["ir.config_parameter"].sudo()
        model = params.get_param("cst_kerama_ai_voice.model") or "gpt-4o-transcribe"
        prompt = params.get_param("cst_kerama_ai_voice.prompt") or ""

        # No `language`: OpenAI rejects 'uz' outright, and automatic detection
        # transcribed Uzbek correctly in testing.  The language is hinted in
        # the prompt instead, which is what the API's own error suggests.
        data = {"model": model, "response_format": "json"}
        if prompt:
            data["prompt"] = prompt

        try:
            response = requests.post(
                ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (upload.filename or "voice.webm",
                                io.BytesIO(raw),
                                mimetype or "audio/webm")},
                data=data, timeout=TIMEOUT)
        except Exception as error:                       # noqa: BLE001
            _logger.warning("Voice transcription failed: %s", error)
            return self._json({"error": _("Хизмат билан алока йук.")}, 502)

        if not response.ok:
            _logger.warning("Voice transcription refused: %s %s",
                            response.status_code, response.text[:300])
            return self._json({"error": _(
                "Матнга угариб булмади (%s).", response.status_code)}, 502)

        text = (response.json() or {}).get("text", "").strip()
        if not text:
            return self._json({"error": _("Хеч нарса эшитилмади.")}, 200)
        return self._json({"text": text})

    def _json(self, payload, status=200):
        return request.make_response(
            json.dumps(payload),
            headers=[("Content-Type", "application/json")],
            status=status)
