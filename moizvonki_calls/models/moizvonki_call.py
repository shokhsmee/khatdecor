import json
import logging
import urllib.request
import urllib.error
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json
import urllib.request
import urllib.error
import urllib.parse
from odoo import _
from odoo.exceptions import UserError

from datetime import datetime, timezone

_logger = logging.getLogger(__name__)


class MoizvonkiCall(models.Model):
    _name = "moizvonki.call"
    _description = "Moizvonki Call"
    _order = "start_datetime desc, id desc"

    # Identifiers
    db_call_id = fields.Char(index=True)
    event_pbx_call_id = fields.Char(index=True)

    # Core
    start_datetime = fields.Datetime(index=True)
    answer_datetime = fields.Datetime()
    end_datetime = fields.Datetime()

    direction = fields.Selection(
        [("in", "Kirish"), ("out", "Chiqish")],
        required=True,
        default="in",
        index=True,
    )

    status = fields.Selection(
        [("answered", "Javob berilgan"), ("missed", "Javob berilmagan"), ("unknown", "Noma'lum")],
        default="unknown",
        index=True,
    )

    duration_sec = fields.Integer(string="Gaplashish vaqti (sek)")
    duration_display = fields.Char(string="Gaplashish vaqti", compute="_compute_duration_display", store=True)

    # Numbers (match your UI columns)
    from_number = fields.Char(string="Kimdan", index=True)
    to_number = fields.Char(string="Kimga", index=True)
    external_number = fields.Char(string="Tashqi raqam", index=True)

    # Employee/operator
    user_id_moizvonki = fields.Char(string="Moizvonki User ID")
    user_login = fields.Char(string="User Login (email)")
    employee_name = fields.Char(string="Xodim")

    # Recording
    recording_url = fields.Char(string="Yozuv")
    has_recording = fields.Boolean(string="Yozuv mavjud", compute="_compute_has_recording", store=True)

    # Raw payload
    raw_json = fields.Text(string="Raw JSON")
    
    player_url = fields.Char(string="Play URL", compute="_compute_player_url", store=False)

    audio_embed = fields.Html(
        string="Player",
        compute="_compute_audio_embed",
        sanitize=False,
        readonly=True,
    )
    
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        index=True,
        compute="_compute_employee_id",
        store=True,
    )

    @api.depends("user_login")
    def _compute_employee_id(self):
        Employee = self.env["hr.employee"].sudo()
        for rec in self:
            email = (rec.user_login or "").strip().lower()
            if not email:
                rec.employee_id = False
                continue
            rec.employee_id = Employee.search(
                [("work_email", "ilike", email)],
                limit=1
            ).id
    
    @api.depends('duration_sec')
    def _compute_duration_display(self):
        for rec in self:
            seconds = max(int(rec.duration_sec or 0), 0)
            hours, rest = divmod(seconds, 3600)
            minutes, secs = divmod(rest, 60)
            rec.duration_display = (
                "%d:%02d:%02d" % (hours, minutes, secs) if hours
                else "%d:%02d" % (minutes, secs)
            )

    @api.depends('recording_url')
    def _compute_has_recording(self):
        for rec in self:
            rec.has_recording = bool((rec.recording_url or '').strip())

    @api.depends('recording_url')
    def _compute_player_url(self):
        for rec in self:
            rec.player_url = f"/moizvonki/stream/{rec.id}" if rec.recording_url else False

    @api.depends('player_url', 'has_recording')
    def _compute_audio_embed(self):
        for rec in self:
            if rec.player_url:
                rec.audio_embed = f"""
                    <audio controls preload="metadata" style="width:100%; max-width:420px; height:35px;">
                        <source src="{rec.player_url}" type="audio/mpeg"/>
                        Your browser does not support the audio element.
                    </audio>
                """
            else:
                rec.audio_embed = ""
    # -------------------------
    # Moizvonki REST client
    # -------------------------
    def _moizvonki_cfg(self):
        ICP = self.env["ir.config_parameter"].sudo()
        domain = ICP.get_param("moizvonki.domain", "")
        user_name = ICP.get_param("moizvonki.user_name", "")
        api_key = ICP.get_param("moizvonki.api_key", "")
        if not (domain and user_name and api_key):
            raise UserError(_("Configure Moizvonki credentials in Settings first."))
        return domain.strip(), user_name.strip(), api_key.strip()



    def _moizvonki_post(self, payload: dict) -> dict:
        domain, user_name, api_key = self._moizvonki_cfg()
        url = f"https://{domain}.moizvonki.ru/api/v1"

        request_data = dict(payload)
        request_data.update({"user_name": user_name, "api_key": api_key})

        # IMPORTANT: send as form-urlencoded request_data=<json-string>
        form = urllib.parse.urlencode({
            "request_data": json.dumps(request_data, ensure_ascii=False)
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise UserError(_("Moizvonki HTTP error %s: %s") % (e.code, e.read().decode("utf-8", "ignore")))
        except Exception as e:
            raise UserError(_("Moizvonki request failed: %s") % str(e))

    # -------------------------
    # Import from calls.list
    # -------------------------
    @api.model
    def cron_sync_calls(self):
        """Periodic backfill (safe)."""
        ICP = self.env["ir.config_parameter"].sudo()
        last_from_id = int(ICP.get_param("moizvonki.last_from_id", "1") or "1")

        # Pull in small batches
        max_results = 100
        payload = {
            "action": "calls.list",
            "from_id": last_from_id,
            "max_results": max_results,
            "supervised": 1,
        }
        data = self._moizvonki_post(payload)

        results = data.get("results") or []
        if not results:
            return

        # Sort by db_call_id
        results_sorted = sorted(results, key=lambda r: int(r.get("db_call_id") or 0))
        for r in results_sorted:
            self._upsert_from_calls_list_item(r)

        # Move cursor forward
        max_db_call_id = max(int(r.get("db_call_id") or 0) for r in results_sorted)
        ICP.set_param("moizvonki.last_from_id", str(max_db_call_id + 1))

    @api.model
    def _upsert_from_calls_list_item(self, r: dict):
        db_call_id = str(r.get("db_call_id") or "")
        if not db_call_id:
            return

        direction = "out" if int(r.get("direction") or 0) == 1 else "in"
        answered = int(r.get("answered") or 0)
        duration = int(r.get("duration") or 0)

        status = "answered" if answered == 1 else "missed"

        # timestamps are UTC epoch seconds
        def dt(ts):
            ts = int(ts or 0)
            if not ts:
                return False
            # Moizvonki timestamps are UTC seconds
            return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)

        vals = {
            "db_call_id": db_call_id,
            "event_pbx_call_id": r.get("event_pbx_call_id"),
            "direction": direction,
            "status": status,
            "duration_sec": duration,
            "start_datetime": dt(r.get("start_time")),
            "answer_datetime": dt(r.get("answer_time")),
            "end_datetime": dt(r.get("end_time")),
            "from_number": r.get("client_number") if direction == "in" else (r.get("user_id") or ""),
            "to_number": r.get("client_number") if direction == "out" else (r.get("user_id") or ""),
            "external_number": r.get("src_number"),
            "user_id_moizvonki": str(r.get("user_id") or ""),
            "user_login": r.get("user_account"),
            "employee_name": r.get("user_account") or "",
            "recording_url": r.get("recording") or "",
            "raw_json": json.dumps(r, ensure_ascii=False),
        }

        existing = self.search([("db_call_id", "=", db_call_id)], limit=1)
        if existing:
            existing.write(vals)
        else:
            self.create(vals)

    # -------------------------
    # Webhook ingestion
    # -------------------------
    @api.model
    def ingest_webhook(self, webhook_meta: dict, event: dict):
        """
        webhook_meta contains account/user info, event contains call event data.
        We only need call.finish for full info, but we accept any.
        """
        event_type = int(event.get("event_type") or 0)  # 1 start, 2 answer, 4 finish
        direction = "out" if int(event.get("direction") or 0) == 1 else "in"
        pbx_id = event.get("event_pbx_call_id")

        # Convert timestamps
        def dt(ts):
            ts = int(ts or 0)
            return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None) if ts else False


        # Determine status
        answered = int(event.get("answered") or 0) if event_type == 4 else None
        duration = int(event.get("duration") or 0) if event_type == 4 else 0

        status = "unknown"
        if answered is not None:
            status = "answered" if answered == 1 else "missed"

        vals = {
            "event_pbx_call_id": pbx_id,
            "direction": direction,
            "status": status,
            "duration_sec": duration,
            "start_datetime": dt(event.get("start_time")) or False,
            "answer_datetime": dt(event.get("answer_time")) or False,
            "end_datetime": dt(event.get("end_time")) or False,
            "from_number": event.get("client_number") if direction == "in" else (webhook_meta.get("user_id") or ""),
            "to_number": event.get("client_number") if direction == "out" else (webhook_meta.get("user_id") or ""),
            "external_number": event.get("src_number") or "",
            "user_id_moizvonki": str(webhook_meta.get("user_id") or ""),
            "user_login": webhook_meta.get("user_login") or "",
            "employee_name": webhook_meta.get("user_login") or "",
            "recording_url": event.get("recording") or "",
            "db_call_id": str(event.get("db_call_id") or ""),
            "raw_json": json.dumps({"webhook": webhook_meta, "event": event}, ensure_ascii=False),
        }

        # Upsert logic: prefer db_call_id, else pbx id
        rec = False
        if vals.get("db_call_id"):
            rec = self.search([("db_call_id", "=", vals["db_call_id"])], limit=1)
        if not rec and pbx_id:
            rec = self.search([("event_pbx_call_id", "=", pbx_id)], limit=1)

        if rec:
            # do not overwrite good timestamps with empty ones
            clean = {k: v for k, v in vals.items() if v not in (False, "", None) or k in ("status", "duration_sec")}
            rec.write(clean)
        else:
            self.create(vals)

        return True
