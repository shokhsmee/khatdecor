# -*- coding: utf-8 -*-
"""Tiny wrapper around the Telegram Bot HTTP API.

Used to push attendance notifications from Odoo to subscribed admins. Each
call is one POST — no SDK, no extra dependency beyond `requests`.
"""
import base64
import logging
from io import BytesIO

import requests

_logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org/bot{token}/{method}"


def _call(token, method, *, data=None, files=None, timeout=10):
    if not token:
        raise ValueError("telegram bot token not configured")
    url = API_BASE.format(token=token, method=method)
    try:
        r = requests.post(url, data=data, files=files, timeout=timeout)
    except requests.RequestException as e:
        _logger.warning("Telegram %s failed: %s", method, e)
        return {"ok": False, "error": str(e)}
    try:
        return r.json()
    except ValueError:
        return {"ok": False, "error": f"non-JSON response: {r.text[:200]}"}


def get_me(token):
    return _call(token, "getMe", timeout=5)


def set_webhook(token, url, secret_token=None):
    data = {"url": url}
    if secret_token:
        data["secret_token"] = secret_token
    return _call(token, "setWebhook", data=data, timeout=10)


def delete_webhook(token):
    return _call(token, "deleteWebhook", timeout=5)


def send_message(token, chat_id, text, parse_mode="HTML", disable_preview=True):
    return _call(token, "sendMessage", data={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": "true" if disable_preview else "false",
    })


def send_photo(token, chat_id, image_b64, caption="", parse_mode="HTML"):
    """image_b64 is the base64 string as stored in an Odoo Binary field."""
    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception as e:
        _logger.warning("Telegram: bad image base64: %s", e)
        return send_message(token, chat_id, caption, parse_mode=parse_mode)

    files = {"photo": ("face.jpg", BytesIO(image_bytes), "image/jpeg")}
    data = {"chat_id": chat_id, "caption": caption, "parse_mode": parse_mode}
    return _call(token, "sendPhoto", data=data, files=files, timeout=15)
