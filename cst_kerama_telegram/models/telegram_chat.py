from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .res_partner import phone_key


class CstTelegramChat(models.Model):
    """One Telegram conversation, and everything known about who is in it.

    Also the manager's inbox: a chat whose phone number matched nothing sits
    here in `pending` until someone links it to a partner, which is the only
    moment a human is needed.
    """

    _name = "cst.telegram.chat"
    _description = "Telegram Chat"
    _inherit = ["mail.thread"]
    _order = "write_date desc"
    _rec_name = "display_name"

    chat_id = fields.Char(required=True, index=True, copy=False, readonly=True)
    tg_username = fields.Char(string="Telegram username", readonly=True)
    tg_name = fields.Char(string="Telegram name", readonly=True)
    phone = fields.Char(readonly=True, tracking=True)
    phone_key = fields.Char(compute="_compute_phone_key", store=True, index="btree_not_null")
    claimed_name = fields.Char(
        string="Aytgan ismi", readonly=True, tracking=True,
        help="Фойдаланувчи узи ёзган исм-фамилия.")
    partner_id = fields.Many2one(
        "res.partner", string="Kontragent", tracking=True, ondelete="set null",
        help="Шу чат кайси контрагентга тегишли.")
    state = fields.Selection(
        [
            ("new", "Yangi"),
            ("awaiting_phone", "Raqam kutilmoqda"),
            ("awaiting_name", "Ism kutilmoqda"),
            ("pending", "Menejer bog'lashi kerak"),
            ("linked", "Bog'langan"),
            ("blocked", "Bloklangan"),
        ],
        default="new", required=True, index=True, tracking=True)
    role_mode = fields.Selection(
        [("customer", "Mijoz"), ("vendor", "Yetkazib beruvchi")],
        string="Qaysi sifatida", default="customer")
    available_roles = fields.Char(compute="_compute_available_roles")
    last_seen = fields.Datetime(readonly=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True)

    _chat_uniq = models.Constraint("unique(chat_id)", "That Telegram chat is already known.")

    @api.depends("phone")
    def _compute_phone_key(self):
        for chat in self:
            chat.phone_key = phone_key(chat.phone)

    @api.depends("partner_id")
    def _compute_available_roles(self):
        for chat in self:
            chat.available_roles = ",".join(
                chat.partner_id._cst_roles()) if chat.partner_id else ""

    @api.depends("partner_id", "tg_name", "chat_id")
    def _compute_display_name(self):
        for chat in self:
            who = chat.partner_id.display_name or chat.claimed_name or chat.tg_name
            chat.display_name = f"{who or 'Telegram'} ({chat.chat_id})"

    # ------------------------------------------------------------------
    @api.model
    def _cst_get_or_create(self, chat_id, sender):
        chat = self.sudo().search([("chat_id", "=", str(chat_id))], limit=1)
        name = " ".join(filter(None, (sender.get("first_name"), sender.get("last_name"))))
        values = {
            "tg_username": sender.get("username"),
            "tg_name": name or False,
            "last_seen": fields.Datetime.now(),
        }
        if chat:
            chat.write(values)
            return chat
        return self.sudo().create({"chat_id": str(chat_id), **values})

    def _cst_roles(self):
        self.ensure_one()
        return self.partner_id._cst_roles() if self.partner_id else []

    def _cst_active_role(self):
        """The side of the ledger this chat is currently looking at.

        A partner who only buys never sees the supplier side — not as an empty
        report, not as a disabled button.
        """
        self.ensure_one()
        roles = self._cst_roles()
        if not roles:
            return None
        if self.role_mode in roles:
            return self.role_mode
        return roles[0]

    # ------------------------------------------------------------------
    # Manager actions
    # ------------------------------------------------------------------
    def action_link(self):
        """Confirm the link a manager made, and tell the person."""
        for chat in self:
            if not chat.partner_id:
                raise UserError(_("Аввал контрагентни танланг."))
            chat.state = "linked"
            if not chat.role_mode or chat.role_mode not in chat._cst_roles():
                roles = chat._cst_roles()
                chat.role_mode = roles[0] if roles else "customer"
            # The partner file is usually missing exactly this.
            if chat.phone and not chat.partner_id.phone:
                chat.partner_id.phone = chat.phone
            chat.message_post(body=_("Контрагентга бог'ланди: %s", chat.partner_id.display_name))
            self.env["cst.telegram.bot"]._send_linked_greeting(chat)
        return True

    def action_block(self):
        self.write({"state": "blocked"})
        return True

    def action_reset(self):
        self.write({"state": "awaiting_phone", "partner_id": False,
                    "phone": False, "claimed_name": False})
        return True

    def action_open_partner(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "res_id": self.partner_id.id,
            "view_mode": "form",
        }
