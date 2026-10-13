# -*- coding: utf-8 -*-
import logging
import requests

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

CHUNK = 1024 * 64  # 64KB


class MoizvonkiAudioController(http.Controller):

    @http.route('/moizvonki/stream/<int:call_id>', type='http', auth='user', methods=['GET', 'HEAD'])
    def stream(self, call_id, **kw):
        """Proxy Moizvonki recording with HTTP Range support (seek/play)."""
        call = request.env['moizvonki.call'].sudo().browse(call_id)
        if not call.exists():
            return request.not_found()

        src_url = (call.recording_url or '').strip()
        if not src_url:
            return request.make_response(
                b"No recording URL.",
                [('Content-Type', 'text/plain; charset=utf-8')]
            )

        headers_in = {
            "Range": request.httprequest.headers.get("Range"),
            "If-Range": request.httprequest.headers.get("If-Range"),
            "Accept": "*/*",
            "User-Agent": "Odoo-Moizvonki-Proxy",
        }

        try:
            upstream = requests.get(
                src_url,
                headers={k: v for k, v in headers_in.items() if v},
                stream=True,
                timeout=120,
                allow_redirects=True,
            )
        except Exception as e:
            _logger.exception("Moizvonki stream failed: %s", e)
            return request.make_response(
                b"Failed to fetch audio.",
                [('Content-Type', 'text/plain; charset=utf-8')]
            )

        status = upstream.status_code
        ctype = upstream.headers.get("Content-Type", "audio/mpeg")
        clen = upstream.headers.get("Content-Length")
        crange = upstream.headers.get("Content-Range")

        response_headers = [
            ('Content-Type', ctype),
            ('Accept-Ranges', 'bytes'),
            ('Cache-Control', 'no-cache'),
        ]
        if crange:
            response_headers.append(('Content-Range', crange))
        if clen:
            response_headers.append(('Content-Length', clen))

        if request.httprequest.method == "HEAD":
            return request.make_response(b"", headers=response_headers, status=status)

        def _gen():
            for chunk in upstream.iter_content(CHUNK):
                if chunk:
                    yield chunk

        return request.make_response(_gen(), headers=response_headers, status=status)

    @http.route('/moizvonki/player/<int:call_id>', type='http', auth='user')
    def player(self, call_id, **kw):
        """Optional: small page with audio player (useful for debugging)."""
        call = request.env['moizvonki.call'].sudo().browse(call_id)
        if not call.exists():
            return request.not_found()

        stream_url = f"/moizvonki/stream/{call_id}"
        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<title>Call {call.db_call_id or call.id}</title>
<style>
  html,body {{ margin:0; padding:16px; font:14px system-ui, -apple-system, Segoe UI, Roboto, Arial; }}
  audio {{ width:100%; }}
</style>
</head>
<body>
  <h3>Call {call.db_call_id or call.id}</h3>
  <audio controls preload="metadata">
    <source src="{stream_url}">
    Your browser does not support the audio element.
  </audio>
</body>
</html>"""
        return request.make_response(html, [('Content-Type', 'text/html; charset=utf-8')])
