from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CstTelegramBroadcast(models.Model):
    """A message the company sends out through the bot."""

    _name = "cst.telegram.broadcast"
    _description = "Telegram Broadcast"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(string="Sarlavha", required=True)
    body = fields.Text(string="Xabar matni", required=True,
                       help="Оддий матн.  <b>калин</b> ва <i>курсив</i> ишлатса булади.")
    audience = fields.Selection(
        [
            ("customer", "Mijozlar"),
            ("vendor", "Yetkazib beruvchilar"),
            ("all", "Hammasi"),
            ("selected", "Tanlanganlar"),
        ],
        default="customer", required=True)
    partner_ids = fields.Many2many("res.partner", string="Kontragentlar")
    state = fields.Selection(
        [("draft", "Qoralama"), ("sent", "Yuborilgan")],
        default="draft", required=True, readonly=True, tracking=True)
    recipient_count = fields.Integer(compute="_compute_recipient_count",
                                     string="Qabul qiluvchilar")
    sent_count = fields.Integer(readonly=True)
    failed_count = fields.Integer(readonly=True)
    sent_date = fields.Datetime(readonly=True)

    @api.depends("audience", "partner_ids")
    def _compute_recipient_count(self):
        for broadcast in self:
            broadcast.recipient_count = len(broadcast._recipients())

    def _recipients(self):
        """Linked chats that should receive this."""
        self.ensure_one()
        chats = self.env["cst.telegram.chat"].sudo().search([
            ("state", "=", "linked"), ("partner_id", "!=", False)])
        if self.audience == "selected":
            wanted = self.partner_ids.ids
            return chats.filtered(lambda c: c.partner_id.id in wanted)
        if self.audience == "all":
            return chats
        return chats.filtered(lambda c: self.audience in c._cst_roles())

    def action_send(self):
        for broadcast in self:
            if broadcast.state == "sent":
                raise UserError(_("«%s» аллакачон юборилган.", broadcast.name))
            chats = broadcast._recipients()
            if not chats:
                raise UserError(_(
                    "Хеч ким топилмади.  Ботда узини танитган контрагентлар "
                    "булиши керак."))
            api = self.env["cst.telegram.api"].sudo()
            sent = failed = 0
            for chat in chats:
                if api.send_message(chat.chat_id, broadcast.body):
                    sent += 1
                else:
                    failed += 1
            broadcast.write({
                "state": "sent",
                "sent_count": sent,
                "failed_count": failed,
                "sent_date": fields.Datetime.now(),
            })
            broadcast.message_post(body=_(
                "Юборилди: %(sent)s та, етиб бормади: %(failed)s та.",
                sent=sent, failed=failed))
        return True

    def action_reset(self):
        self.write({"state": "draft", "sent_count": 0, "failed_count": 0,
                    "sent_date": False})
        return True
