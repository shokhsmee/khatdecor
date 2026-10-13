# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

BOT_TZ = "Asia/Tashkent"


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    check_in_image = fields.Binary(string="Check-In Photo", attachment=True)
    check_out_image = fields.Binary(string="Check-Out Photo", attachment=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # the terminal's webhook sets hik_notify; with or without a photo
        for rec, vals in zip(records, vals_list):
            if self._hik_should_notify(vals.get("check_in_image")):
                rec._notify_telegram("check_in")
            elif rec._is_manual_change():
                rec._notify_correction("add")
        return records

    def write(self, vals):
        before = {}
        if {"check_in", "check_out", "employee_id"} & set(vals) and self._is_manual_change():
            before = {rec.id: (rec.employee_id, rec.check_in, rec.check_out) for rec in self}
        res = super().write(vals)
        if vals.get("check_out") and self._hik_should_notify(vals.get("check_out_image")):
            for rec in self:
                rec._notify_telegram("check_out")
        for rec in self.filtered(lambda r: r.id in before):
            if before[rec.id] != (rec.employee_id, rec.check_in, rec.check_out):
                rec._notify_correction("edit", before[rec.id])
        return res

    def unlink(self):
        if self._is_manual_change():
            for rec in self:
                rec._notify_correction("delete")
        return super().unlink()

    # ------------------------------------------------------------------
    # Hand corrections reach the same chat as the terminal's events
    # ------------------------------------------------------------------
    def _hik_should_notify(self, image):
        """hik_notify=False is the webhook muting a replayed backlog event."""
        flag = self.env.context.get("hik_notify")
        return bool(flag or (image and flag is not False))

    def _is_manual_change(self):
        """A person editing attendance in Odoo -- not the terminal (hik_notify)
        and not the system (crons and the webhook run as superuser)."""
        ctx = self.env.context
        return "hik_notify" not in ctx and not self.env.su and not ctx.get("install_mode")

    def _uz_time(self, dt):
        return self._format_uz_datetime(dt) if dt else "—"

    def _notify_correction(self, kind, old=None):
        self.ensure_one()
        emp = self.employee_id
        who = self.env.user.name
        if kind == "add":
            body = (f"➕ <b>Davomat qo'lda qo'shildi</b>\n👤 {emp.name}\n"
                    f"🟢 Kirish: {self._uz_time(self.check_in)}\n🔴 Chiqish: {self._uz_time(self.check_out)}")
        elif kind == "delete":
            body = (f"🗑 <b>Davomat o'chirildi</b>\n👤 {emp.name}\n"
                    f"🟢 Kirish: {self._uz_time(self.check_in)}\n🔴 Chiqish: {self._uz_time(self.check_out)}")
        else:
            old_emp, old_in, old_out = old
            lines = [f"✏️ <b>Davomat tuzatildi</b>", f"👤 {emp.name}"]
            if old_emp != emp:
                lines.append(f"👥 Xodim: {old_emp.name} → {emp.name}")
            if old_in != self.check_in:
                lines.append(f"🟢 Kirish: {self._uz_time(old_in)} → <b>{self._uz_time(self.check_in)}</b>")
            if old_out != self.check_out:
                lines.append(f"🔴 Chiqish: {self._uz_time(old_out)} → <b>{self._uz_time(self.check_out)}</b>")
            body = "\n".join(lines)
        body += f"\n✍️ Tuzatdi: {who}"
        try:
            self.env["hikvision.attendance.subscriber"].sudo()._broadcast(body)
        except Exception as e:
            _logger.warning("Hikvision bot: correction notify failed: %s", e)

    _UZ_MONTHS = (
        "yanvar", "fevral", "mart", "aprel", "may", "iyun",
        "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
    )

    def _format_uz_datetime(self, dt):
        if not dt:
            return "?"
        # bot messages go out from the camera's webhook (public user, no tz):
        # the shop is in Tashkent, UTC+5, whoever triggers the message
        local = fields.Datetime.context_timestamp(self.with_context(tz=BOT_TZ), dt)
        return (
            f"{local.day}-{self._UZ_MONTHS[local.month - 1]} "
            f"{local.year}-yil, {local:%H:%M}"
        )

    def _notify_telegram(self, kind):
        """Push a Hikvision-sourced attendance event to subscribed admins."""
        self.ensure_one()
        if kind == "check_in":
            dt = self.check_in
            image = self.check_in_image
            emoji = "🟢"
            label = "Kirish"
        else:
            dt = self.check_out
            image = self.check_out_image
            emoji = "🔴"
            label = "Chiqish"

        emp = self.employee_id
        company_name = (emp.company_id.name
                        or self.company_id.name
                        or self.env.company.name)
        caption = (
            f"{emoji} <b>{label}</b>\n"
            f"👤 {emp.name or '?'}\n"
            f"🆔 {emp.sudo().face_id or emp.barcode or '-'}\n"
            f"🕐 {self._format_uz_datetime(dt)}\n"
            f"{self._hik_shift_line(kind)}"
        )
        if company_name:
            caption += f"\n🏢 {company_name}"

        try:
            self.env["hikvision.attendance.subscriber"].sudo()._broadcast(
                caption, image_b64=image or None,
            )
        except Exception as e:
            _logger.warning("Hikvision bot: dispatch failed: %s", e)
