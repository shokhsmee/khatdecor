# -*- coding: utf-8 -*-
import base64
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from odoo import http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 60
OPEN_SHIFT_HOURS = 16
# events older than this are a backlog the terminal is replaying: record them
# but keep the Telegram chat quiet
STALE_MINUTES = 10
EXIT_DEVICE_WORDS = ("chiqish", "chikish", "чиқиш", "чикиш", "exit")
ENTRY_DEVICE_WORDS = ("kirish", "кириш", "entry", "enter")


class HikvisionAttendanceController(http.Controller):

    @http.route(
        "/hikvision/attendance",
        type="http",
        auth="public",
        methods=["POST", "GET", "OPTIONS"],
        csrf=False,
    )
    def hikvision_attendance(self, **kwargs):
        method = request.httprequest.method

        if method in ("GET", "OPTIONS"):
            return request.make_response("OK", status=200, headers=[("Content-Type", "text/plain")])

        # 1) multipart form fields
        form_data = {}
        try:
            form_data = request.httprequest.form.to_dict()
        except Exception:
            pass

        # 2) multipart file parts — keep raw bytes for JPEG, also extract text
        files_text = ""
        image_b64 = None
        try:
            for key, f in request.httprequest.files.items():
                raw = f.read()
                # detect JPEG by magic bytes
                if raw[:2] == b"\xff\xd8":
                    image_b64 = base64.b64encode(raw).decode("ascii")
                else:
                    files_text += raw.decode("utf-8", errors="ignore")
        except Exception:
            pass

        _logger.warning(
            "Hikvision HIT: raw= form=%s files_preview=%s",
            str(form_data)[:2500],
            files_text[:200],
        )

        # --- extract person_code and event time ---
        person_code = None
        event_dt = datetime.now(timezone.utc)
        attendance_status = None
        device_id = ""

        # Primary: parse JSON from AccessControllerEvent form field
        ace_raw = form_data.get("AccessControllerEvent", "")
        if ace_raw:
            try:
                ace = json.loads(ace_raw)
                inner = ace.get("AccessControllerEvent", {})

                # employee identifier
                for key in ("employeeNoString", "employeeNo", "cardNo", "personId", "userID"):
                    val = inner.get(key) or ace.get(key)
                    if val and str(val).strip():
                        person_code = str(val).strip()
                        break

                # attendance status hint from device
                attendance_status = inner.get("attendanceStatus")
                device_id = str(ace.get("deviceID") or "")

                # use device timestamp if available
                raw_dt = ace.get("dateTime")
                if raw_dt:
                    try:
                        event_dt = datetime.fromisoformat(raw_dt).astimezone(timezone.utc).replace(tzinfo=None)
                    except Exception:
                        event_dt = datetime.utcnow()
                else:
                    event_dt = datetime.utcnow()
            except Exception as e:
                _logger.warning("Hikvision: JSON parse error: %s", e)

        # Fallback: regex on files_text (XML or raw body)
        if not person_code and files_text:
            patterns = [
                r"<employeeNoString>(.*?)</employeeNoString>",
                r"<employeeNo>(.*?)</employeeNo>",
                r"\"employeeNoString\"\s*:\s*\"([^\"]+)\"",
                r"\"employeeNo\"\s*:\s*\"([^\"]+)\"",
                r"<cardNo>(.*?)</cardNo>",
                r"<personId>(.*?)</personId>",
            ]
            for pat in patterns:
                m = re.search(pat, files_text, flags=re.IGNORECASE | re.DOTALL)
                if m and m.group(1).strip():
                    person_code = m.group(1).strip()
                    break

        if not person_code:
            _logger.warning("Hikvision: No person_code found. form=%s", str(form_data)[:500])
            return request.make_response("OK", status=200, headers=[("Content-Type", "text/plain")])

        # the dedicated Face ID field first; Badge ID stays as a fallback for
        # employees set up before the field existed
        Employee = request.env["hr.employee"].sudo()
        employee = Employee.search([("face_id", "=", person_code)], limit=1) \
            or Employee.search([("barcode", "=", person_code)], limit=1)
        if not employee:
            # the codes were typed from screenshots: capital I and small l (and 1)
            # are easily mixed up, so compare them as one letter
            def fold(code):
                return (code or "").replace("I", "l").replace("1", "l")
            wanted = fold(person_code)
            employee = Employee.search([("face_id", "!=", False)]).filtered(
                lambda e: fold(e.face_id) == wanted)[:1]
            if employee:
                _logger.warning("Hikvision: face_id %s matched %s by I/l folding (stored %s)",
                                person_code, employee.name, employee.face_id)

        if not employee:
            _logger.warning(
                "Hikvision: No employee with face_id/barcode=%s (attendanceStatus=%s)",
                person_code, attendance_status,
            )
            return request.make_response("OK", status=200, headers=[("Content-Type", "text/plain")])

        Attendance = request.env["hr.attendance"].sudo()
        now = datetime.utcnow()
        # a terminal whose clock runs ahead would stamp the future
        if event_dt > now + timedelta(minutes=2):
            _logger.warning("Hikvision: device clock ahead (%s > %s), using server time", event_dt, now)
            event_dt = now

        open_att = Attendance.search(
            [("employee_id", "=", employee.id), ("check_out", "=", False)],
            limit=1, order="check_in desc")
        # an entry left open longer than a shift is a forgotten exit: close it
        # at zero length so it adds no invented hours, and treat as outside
        if open_att and open_att.check_in < event_dt - timedelta(hours=OPEN_SHIFT_HOURS):
            open_att.with_context(hik_notify=False).write({"check_out": open_att.check_in})
            _logger.warning("Hikvision: forgotten exit closed at zero length for employee=%s (%s)",
                            employee.name, open_att.check_in)
            open_att = Attendance.browse()

        notify = event_dt >= now - timedelta(minutes=STALE_MINUTES)
        Attendance = Attendance.with_context(hik_notify=notify)
        # which way: the terminal's name decides (Kirish / Chiqish), then the
        # device's own status, then whether the person is inside
        device = device_id.lower()
        if any(word in device for word in EXIT_DEVICE_WORDS):
            direction = "checkOut"
        elif any(word in device for word in ENTRY_DEVICE_WORDS):
            direction = "checkIn"
        elif attendance_status in ("checkIn", "checkOut"):
            direction = attendance_status
        else:
            # a terminal with no Kirish/Chiqish role toggles, so a face pass
            # that arrives as two events seconds apart would enter and leave:
            # ignore a repeat within the minute. Kirish/Chiqish terminals need
            # no such filter -- a second entry or exit is refused below, and a
            # quick Kirish→Chiqish must count.
            recent = Attendance.search_count([
                ("employee_id", "=", employee.id), "|",
                ("check_in", ">=", event_dt - timedelta(seconds=DEBOUNCE_SECONDS)),
                ("check_out", ">=", event_dt - timedelta(seconds=DEBOUNCE_SECONDS)),
            ])
            if recent:
                _logger.warning("Hikvision: repeat scan ignored for employee=%s", employee.name)
                return request.make_response("OK", status=200, headers=[("Content-Type", "text/plain")])
            direction = "checkOut" if open_att else "checkIn"

        # the terminal resends an event until it gets a 2xx and holds every
        # later one behind it, so an event Odoo refuses (e.g. an entry that
        # overlaps an existing record) must still be answered OK
        try:
            with request.env.cr.savepoint():
                if direction == "checkIn":
                    if open_att:
                        # already inside: a second entry needs an exit first
                        _logger.warning("Hikvision: entry refused, employee=%s already in since %s (device %s)",
                                        employee.name, open_att.check_in, device_id)
                    else:
                        vals = {"employee_id": employee.id, "check_in": event_dt}
                        if image_b64:
                            vals["check_in_image"] = image_b64
                        Attendance.create(vals)
                        _logger.warning("Hikvision: check_in employee=%s at %s (device %s)", employee.name, event_dt, device_id)
                else:
                    if open_att:
                        vals = {"check_out": event_dt}
                        if image_b64:
                            vals["check_out_image"] = image_b64
                        open_att.with_context(hik_notify=notify).write(vals)
                        _logger.warning("Hikvision: check_out employee=%s at %s (device %s)", employee.name, event_dt, device_id)
                    else:
                        _logger.warning("Hikvision: exit refused, employee=%s has no open entry (device %s)",
                                        employee.name, device_id)
        except (ValidationError, UserError) as e:
            _logger.warning("Hikvision: event refused by Odoo for employee=%s at %s (device %s): %s",
                            employee.name, event_dt, device_id, e)

        return request.make_response("OK", status=200, headers=[("Content-Type", "text/plain")])