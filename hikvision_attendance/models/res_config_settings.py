# -*- coding: utf-8 -*-
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import telegram_api


PARAM_TOKEN = "hikvision_attendance.bot_token"
PARAM_USERNAME = "hikvision_attendance.bot_username"
PARAM_INVITE = "hikvision_attendance.bot_invite_token"
PARAM_WEBHOOK_SECRET = "hikvision_attendance.webhook_secret"
PARAM_BASE_URL = "hikvision_attendance.odoo_base_url"


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    hik_bot_token = fields.Char(
        string="Telegram Bot Token",
        config_parameter=PARAM_TOKEN,
        help="BotFather dan olingan token (masalan, 123456:AAH...).",
    )
    hik_bot_username = fields.Char(
        string="Bot Username",
        config_parameter=PARAM_USERNAME,
        help="Botning @username (without @). Auto-filled by 'Sync Bot Info'.",
    )
    hik_bot_invite_token = fields.Char(
        string="Admin Invite Token",
        config_parameter=PARAM_INVITE,
        help="Admins must enter the bot via /start <token>. Regenerate to revoke access.",
    )
    hik_bot_odoo_base_url = fields.Char(
        string="Odoo Public Base URL",
        config_parameter=PARAM_BASE_URL,
        help="Public URL of this Odoo (e.g. https://weteachprof.shokhsmee.uz). "
             "Used to register Telegram webhook.",
    )
    hik_bot_webhook_secret = fields.Char(
        string="Webhook Secret",
        config_parameter=PARAM_WEBHOOK_SECRET,
        readonly=True,
    )
    hik_bot_invite_link = fields.Char(
        string="Admin Invite Link",
        compute="_compute_invite_link",
        help="Share this link with admins. They tap it → Telegram opens → bot adds them.",
    )

    @api.depends("hik_bot_username", "hik_bot_invite_token")
    def _compute_invite_link(self):
        for rec in self:
            if rec.hik_bot_username and rec.hik_bot_invite_token:
                rec.hik_bot_invite_link = (
                    f"https://t.me/{rec.hik_bot_username}?start={rec.hik_bot_invite_token}"
                )
            else:
                rec.hik_bot_invite_link = ""

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_hik_bot_sync_info(self):
        """Call getMe to fetch the bot's @username and verify the token."""
        self.ensure_one()
        token = self.hik_bot_token or self.env["ir.config_parameter"].sudo().get_param(PARAM_TOKEN)
        if not token:
            raise UserError(_("Set the bot token first."))

        result = telegram_api.get_me(token)
        if not result.get("ok"):
            raise UserError(_("getMe failed: %s") % result.get("description") or result.get("error"))

        bot = result.get("result", {})
        username = bot.get("username") or ""
        self.env["ir.config_parameter"].sudo().set_param(PARAM_USERNAME, username)

        # Ensure invite token + webhook secret exist
        ICP = self.env["ir.config_parameter"].sudo()
        if not ICP.get_param(PARAM_INVITE):
            ICP.set_param(PARAM_INVITE, secrets.token_urlsafe(16))
        if not ICP.get_param(PARAM_WEBHOOK_SECRET):
            ICP.set_param(PARAM_WEBHOOK_SECRET, secrets.token_urlsafe(24))

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Bot connected"),
                "message": _("@%s (%s)") % (username, bot.get("first_name", "?")),
                "type": "success",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def action_hik_bot_set_webhook(self):
        self.ensure_one()
        ICP = self.env["ir.config_parameter"].sudo()
        token = ICP.get_param(PARAM_TOKEN)
        base_url = (self.hik_bot_odoo_base_url
                    or ICP.get_param(PARAM_BASE_URL)
                    or ICP.get_param("web.base.url"))
        if not (token and base_url):
            raise UserError(_("Bot token and Odoo base URL are both required."))

        # Ensure secret exists
        secret = ICP.get_param(PARAM_WEBHOOK_SECRET)
        if not secret:
            secret = secrets.token_urlsafe(24)
            ICP.set_param(PARAM_WEBHOOK_SECRET, secret)

        webhook_url = base_url.rstrip("/") + "/hikvision_attendance/telegram/webhook"
        result = telegram_api.set_webhook(token, webhook_url, secret_token=secret)
        if not result.get("ok"):
            raise UserError(_("setWebhook failed: %s") % (result.get("description") or result.get("error")))

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Webhook set"),
                "message": webhook_url,
                "type": "success",
            },
        }

    def action_hik_bot_regenerate_invite(self):
        self.ensure_one()
        new = secrets.token_urlsafe(16)
        self.env["ir.config_parameter"].sudo().set_param(PARAM_INVITE, new)
        self.hik_bot_invite_token = new
        return True
