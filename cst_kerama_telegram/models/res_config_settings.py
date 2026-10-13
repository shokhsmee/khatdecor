import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError

PARAM_TOKEN = "cst_kerama_telegram.bot_token"
PARAM_SECRET = "cst_kerama_telegram.webhook_secret"


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    cst_telegram_bot_token = fields.Char(
        string="Bot token", config_parameter=PARAM_TOKEN,
        help="@BotFather берган токен.")
    cst_telegram_webhook_url = fields.Char(
        string="Webhook URL", compute="_compute_cst_telegram_webhook_url")
    cst_telegram_status = fields.Char(
        string="Holati", compute="_compute_cst_telegram_status")

    def _webhook_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        return f"{(base or '').rstrip('/')}/telegram/webhook"

    @api.depends_context("uid")
    def _compute_cst_telegram_webhook_url(self):
        for record in self:
            record.cst_telegram_webhook_url = record._webhook_url()

    @api.depends("cst_telegram_bot_token")
    def _compute_cst_telegram_status(self):
        for record in self:
            token = self.env["ir.config_parameter"].sudo().get_param(PARAM_TOKEN)
            if not token:
                record.cst_telegram_status = _("Токен киритилмаган")
                continue
            info = self.env["cst.telegram.api"].sudo().get_webhook_info(raise_on_error=False)
            if info is None:
                record.cst_telegram_status = _("Telegram билан алока йук")
            elif info.get("url"):
                record.cst_telegram_status = _(
                    "Уланган: %(url)s  (кутилаётган: %(pending)s)",
                    url=info["url"], pending=info.get("pending_update_count", 0))
            else:
                record.cst_telegram_status = _("Токен бор, webhook урнатилмаган")

    def action_cst_telegram_set_webhook(self):
        """Point Telegram at this Odoo, with a secret only the two of us know."""
        self.ensure_one()
        params = self.env["ir.config_parameter"].sudo()
        if not params.get_param(PARAM_TOKEN):
            raise UserError(_("Аввал бот токенини киритиб, сакланг."))
        secret = params.get_param(PARAM_SECRET)
        if not secret:
            secret = secrets.token_urlsafe(32)
            params.set_param(PARAM_SECRET, secret)
        url = self._webhook_url()
        if not url.startswith("https://"):
            raise UserError(_(
                "Telegram факат HTTPS манзилга улана олади.  Хозирги манзил: %s", url))
        api = self.env["cst.telegram.api"].sudo()
        me = api.get_me()
        api.set_webhook(url, secret)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("Бот уланди"),
                "message": _("@%(username)s — %(url)s",
                             username=(me or {}).get("username", "?"), url=url),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def action_cst_telegram_delete_webhook(self):
        self.ensure_one()
        self.env["cst.telegram.api"].sudo().delete_webhook()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"type": "warning", "title": _("Бот учирилди"),
                       "message": _("Webhook олиб ташланди."),
                       "next": {"type": "ir.actions.act_window_close"}},
        }
