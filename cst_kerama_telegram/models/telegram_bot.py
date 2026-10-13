import base64
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, fields, models

_logger = logging.getLogger(__name__)

PERIODS = {
    "m": ("Bu oy", lambda today: (fields.Date.start_of(today, "month"), today)),
    "q": ("3 oy", lambda today: (today - relativedelta(months=3), today)),
    "y": ("Bu yil", lambda today: (fields.Date.start_of(today, "year"), today)),
    "a": ("Hammasi", lambda today: (None, today)),
}

ROLE_LABEL = {"customer": "Mijoz", "vendor": "Yetkazib beruvchi"}


def money(amount):
    """1234567.0 -> '1 234 567' — the way the figure is read here."""
    return f"{amount:,.0f}".replace(",", " ")


def day(value):
    return value.strftime("%d.%m.%Y") if value else ""


class CstTelegramBot(models.AbstractModel):
    """The conversation itself.

    Every reply is built from the ledger at the moment it is asked for; the
    bot keeps no copy of anything except who the person is.
    """

    _name = "cst.telegram.bot"
    _description = "Telegram Bot"

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def _handle_update(self, update):
        try:
            if update.get("message"):
                self._handle_message(update["message"])
            elif update.get("callback_query"):
                self._handle_callback(update["callback_query"])
        except Exception:                                  # noqa: BLE001
            # Telegram retries anything that is not answered with 200, and a
            # retry storm on a broken message helps nobody.
            _logger.exception("Telegram update failed: %s", update)

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------
    def _handle_message(self, message):
        sender = message.get("from") or {}
        chat_id = (message.get("chat") or {}).get("id")
        if not chat_id or sender.get("is_bot"):
            return
        chat = self.env["cst.telegram.chat"]._cst_get_or_create(chat_id, sender)
        if chat.state == "blocked":
            return

        text = (message.get("text") or "").strip()
        contact = message.get("contact")

        if text.startswith("/start"):
            return self._ask_phone(chat)
        if contact:
            return self._on_contact(chat, contact, sender)
        if chat.state == "awaiting_name":
            return self._on_name(chat, text)
        if chat.state == "linked":
            if text in ("/menu", "/help"):
                return self._send_menu(chat)
            return self._send_menu(chat, prefix=_("Керакли булимни танланг:"))
        return self._ask_phone(chat)

    def _ask_phone(self, chat):
        chat.sudo().write({"state": "awaiting_phone"})
        self._api().send_message(
            chat.chat_id,
            _("Ассалому алайкум!\n\n"
              "Мен <b>Khatdecor</b> ботиман.  Сизга баланс, акт сверка ва "
              "тулланмаган хисоб-фактураларни курсатаман.\n\n"
              "Аввал узингизни танитинг — пастдаги тугма орқали "
              "<b>телефон рақамингизни</b> юборинг."),
            keyboard={
                "keyboard": [[{"text": "📱 Raqamni yuborish", "request_contact": True}]],
                "resize_keyboard": True,
                "one_time_keyboard": True,
            })

    def _on_contact(self, chat, contact, sender):
        # Telegram lets a person forward somebody else's contact card; only a
        # number the sender owns proves anything.
        if contact.get("user_id") and str(contact["user_id"]) != str(sender.get("id")):
            return self._api().send_message(
                chat.chat_id,
                _("Бу бошка одамнинг раками.  Илтимос, <b>уз ракамингизни</b> "
                  "тугма орқали юборинг."))
        phone = contact.get("phone_number")
        chat.sudo().write({"phone": phone})

        partners = self.env["res.partner"].sudo()._cst_search_by_phone(phone)
        partners = partners.filtered(lambda p: p._cst_roles())
        if len(partners) == 1:
            chat.sudo().write({"partner_id": partners.id, "state": "awaiting_name"})
            return self._api().send_message(
                chat.chat_id,
                _("Рақам топилди.  Тасдиқлаш учун <b>исм-фамилиянгизни</b> ёзинг."),
                remove_keyboard=True)
        if len(partners) > 1:
            # One phone number really does belong to two partners here.
            chat.sudo().write({"state": "awaiting_name"})
            return self._api().send_message(
                chat.chat_id,
                _("Бу рақам бир нечта контрагентга ёзилган.  "
                  "<b>Исм-фамилиянгизни</b> ёзинг — кайси бири эканини аниклайман."),
                remove_keyboard=True)
        chat.sudo().write({"state": "awaiting_name"})
        return self._api().send_message(
            chat.chat_id,
            _("Рақамингиз базада топилмади.  <b>Исм-фамилиянгизни</b> ёзинг — "
              "менежерга суров юбораман."),
            remove_keyboard=True)

    def _on_name(self, chat, text):
        if len(text) < 3:
            return self._api().send_message(
                chat.chat_id, _("Илтимос, тулик исм-фамилиянгизни ёзинг."))
        chat.sudo().write({"claimed_name": text})

        candidates = self.env["res.partner"].sudo()._cst_search_by_phone(chat.phone)
        candidates = candidates.filtered(lambda p: p._cst_roles())
        # One partner was already picked by the phone number; otherwise the
        # name has to choose between the several that share it.
        partner = chat.partner_id or self._pick_by_name(candidates, text)
        if partner:
            chat.sudo().write({"partner_id": partner.id})
            return self._confirm_partner(chat, claimed=text)

        chat.sudo().write({"state": "pending"})
        chat.sudo().message_post(body=_(
            "Янги суров: %(name)s, %(phone)s — контрагент топилмади.",
            name=text, phone=chat.phone or "—"))
        return self._api().send_message(
            chat.chat_id,
            _("Рахмат!  Маълумотларингиз менежерга юборилди.\n\n"
              "Тасдикланганидан сунг сизга хабар бераман."))

    def _pick_by_name(self, partners, text):
        """The name the person typed, against the names on the candidates."""
        wanted = set(part for part in text.lower().split() if len(part) > 2)
        best, best_score = None, 0
        for partner in partners:
            words = set(part for part in (partner.name or "").lower().split() if len(part) > 2)
            score = len(wanted & words)
            if score > best_score:
                best, best_score = partner, score
        return best

    def _confirm_partner(self, chat, claimed=None):
        chat.sudo().write({"state": "linked"})
        roles = chat._cst_roles()
        chat.sudo().write({"role_mode": roles[0] if roles else "customer"})
        if chat.phone and not chat.partner_id.phone:
            chat.partner_id.sudo().phone = chat.phone
        note = _("Телеграм оркали узини танитди: %s", chat.partner_id.display_name)
        # The phone is proof, the name is only a second opinion — so a name
        # that does not look like the partner's is flagged rather than
        # refused.  Locking a real customer out over a spelling is worse than
        # a manager glancing at a note.
        if claimed and not self._pick_by_name(chat.partner_id, claimed):
            note += _("\n⚠️ Ёзган исми контрагент номига ухшамайди: «%s»", claimed)
        chat.sudo().message_post(body=note)
        return self._send_linked_greeting(chat)

    def _send_linked_greeting(self, chat):
        roles = chat._cst_roles()
        as_what = " / ".join(ROLE_LABEL[role] for role in roles) or "—"
        self._api().send_message(
            chat.chat_id,
            _("Хуш келибсиз, <b>%(name)s</b>!\n"
              "Сиз <b>%(roles)s</b> сифатида руйхатдансиз.",
              name=chat.partner_id.display_name, roles=as_what),
            remove_keyboard=True)
        return self._send_menu(chat)

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------
    def _menu_keyboard(self, chat):
        roles = chat._cst_roles()
        rows = [
            [{"text": "💰 Balans", "callback_data": "bal"},
             {"text": "📄 Akt sverka", "callback_data": "st"}],
            [{"text": "🧾 To'lanmagan hujjatlar", "callback_data": "open"}],
        ]
        # Only a partner who really is on both sides is offered the switch.
        if len(roles) > 1:
            other = "vendor" if chat._cst_active_role() == "customer" else "customer"
            rows.append([{
                "text": _("🔄 %s sifatida ko'rish", ROLE_LABEL[other]),
                "callback_data": f"role:{other}",
            }])
        return {"inline_keyboard": rows}

    def _send_menu(self, chat, prefix=None):
        role = chat._cst_active_role()
        header = prefix or _("Керакли булимни танланг:")
        if len(chat._cst_roles()) > 1:
            header = _("%(header)s\n\nХозир: <b>%(role)s</b> сифатида",
                       header=header, role=ROLE_LABEL[role])
        return self._api().send_message(
            chat.chat_id, header, keyboard=self._menu_keyboard(chat))

    def _handle_callback(self, callback):
        sender = callback.get("from") or {}
        chat_id = ((callback.get("message") or {}).get("chat") or {}).get("id")
        data = callback.get("data") or ""
        if not chat_id:
            return
        chat = self.env["cst.telegram.chat"]._cst_get_or_create(chat_id, sender)
        self._api().answer_callback(callback.get("id"))
        if chat.state != "linked":
            return self._ask_phone(chat)

        if data == "bal":
            return self._send_balance(chat)
        if data == "st":
            return self._ask_period(chat)
        if data.startswith("st:"):
            return self._send_statement(chat, data[3:])
        if data.startswith("pdf:"):
            return self._send_statement_pdf(chat, data[4:])
        if data == "open":
            return self._send_open_documents(chat)
        if data.startswith("role:"):
            wanted = data[5:]
            if wanted in chat._cst_roles():
                chat.sudo().role_mode = wanted
            return self._send_menu(chat)
        if data == "menu":
            return self._send_menu(chat)

    # ------------------------------------------------------------------
    # Answers
    # ------------------------------------------------------------------
    def _send_balance(self, chat):
        role = chat._cst_active_role()
        data = chat.partner_id._cst_statement(role)
        owed = data["closing"]
        if role == "customer":
            verdict = _("Сизнинг қарзингиз: <b>%s so'm</b>", money(owed)) if owed > 0 \
                else _("Қарзингиз йўқ.  Олдиндан тўлов: <b>%s so'm</b>", money(-owed)) \
                if owed < 0 else _("Қарздорлик йўқ. ✅")
        else:
            verdict = _("Компания сизга қарздор: <b>%s so'm</b>", money(owed)) if owed > 0 \
                else _("Қарздорлик йўқ. ✅") if owed == 0 \
                else _("Сиз компанияга қарздорсиз: <b>%s so'm</b>", money(-owed))
        # amounts are in company currency (USD since 20.09), not always so'm
        ccy = data["currency"]
        verdict = verdict.replace("so'm", ccy.currency_unit_label or ccy.name)
        return self._api().send_message(
            chat.chat_id,
            _("<b>%(partner)s</b>\n%(role)s сифатида\n\n%(verdict)s",
              partner=chat.partner_id.display_name,
              role=ROLE_LABEL[role], verdict=verdict),
            keyboard=self._menu_keyboard(chat))

    def _ask_period(self, chat):
        rows = [
            [{"text": PERIODS["m"][0], "callback_data": "st:m"},
             {"text": PERIODS["q"][0], "callback_data": "st:q"}],
            [{"text": PERIODS["y"][0], "callback_data": "st:y"},
             {"text": PERIODS["a"][0], "callback_data": "st:a"}],
            [{"text": "⬅️ Orqaga", "callback_data": "menu"}],
        ]
        return self._api().send_message(
            chat.chat_id, _("Акт сверка кайси давр учун?"),
            keyboard={"inline_keyboard": rows})

    def _period(self, key):
        label, bounds = PERIODS.get(key, PERIODS["m"])
        date_from, date_to = bounds(fields.Date.context_today(self))
        return label, date_from, date_to

    def _send_statement(self, chat, key):
        role = chat._cst_active_role()
        label, date_from, date_to = self._period(key)
        data = chat.partner_id._cst_statement(role, date_from, date_to)

        header = _(
            "<b>АКТ СВЕРКА</b>\n%(partner)s\n%(role)s сифатида\n%(period)s\n",
            partner=chat.partner_id.display_name, role=ROLE_LABEL[role],
            period=f"{day(date_from) or '...'} — {day(date_to)}")
        body = [header]
        if data["truncated"]:
            body.append(_("(охирги %(shown)s та ёзув курсатилди, жами %(total)s та)",
                          shown=len(data["movements"]),
                          total=len(data["movements"]) + data["truncated"]))
        body.append("")
        body.append(_("Бошлангич колдик: <b>%s</b>", money(data["opening"])))
        for line in data["movements"]:
            sign = "+" if line["amount"] >= 0 else "−"
            body.append(f"{day(line['date'])}  {line['name'] or line['label'][:40]}  {sign}{money(abs(line['amount']))}")
        body.append("")
        body.append(_("Хисобланди: <b>%s</b>", money(data["charged"])))
        body.append(_("Туланди: <b>%s</b>", money(data["paid"])))
        body.append(_("Охирги колдик: <b>%s so'm</b>", money(data["closing"])).replace(
            "so'm", data["currency"].currency_unit_label or data["currency"].name))

        return self._api().send_message(
            chat.chat_id, "\n".join(body),
            keyboard={"inline_keyboard": [
                [{"text": "📎 PDF yuklash", "callback_data": f"pdf:{key}"}],
                [{"text": "⬅️ Menyu", "callback_data": "menu"}],
            ]})

    def _send_statement_pdf(self, chat, key):
        label, date_from, date_to = self._period(key)
        content = self._partner_ledger_pdf(chat.partner_id, date_from, date_to)
        if not content:
            return self._api().send_message(
                chat.chat_id, _("PDF тайёрлашда хатолик булди.  Кейинрок уриниб куринг."))
        filename = "akt_sverka_%s_%s.pdf" % (
            (chat.partner_id.ref or chat.partner_id.id), day(date_to).replace(".", ""))
        return self._api().send_document(
            chat.chat_id, filename, content,
            caption=_("Акт сверка — %s", chat.partner_id.display_name))

    def _partner_ledger_pdf(self, partner, date_from, date_to):
        """The standard Partner Ledger, for this partner only."""
        report = self.env.ref("account_reports.partner_ledger_report",
                              raise_if_not_found=False)
        if not report:
            return None
        report = report.sudo().with_company(self.env.company)
        options = report.get_options({
            "date": {
                "mode": "range",
                "filter": "custom",
                "date_from": fields.Date.to_string(
                    date_from or fields.Date.to_date("2000-01-01")),
                "date_to": fields.Date.to_string(date_to),
            },
            "partner_ids": [partner.commercial_partner_id.id],
            "unfold_all": True,
            "export_mode": "print",
        })
        result = report.export_to_pdf(options)
        content = result.get("file_content") if isinstance(result, dict) else result
        if isinstance(content, str):
            content = base64.b64decode(content)
        return content

    def _send_open_documents(self, chat):
        role = chat._cst_active_role()
        moves = chat.partner_id._cst_open_documents(role)
        if not moves:
            return self._api().send_message(
                chat.chat_id, _("Туланмаган хужжат йук. ✅"),
                keyboard=self._menu_keyboard(chat))
        body = [_("<b>Туланмаган хужжатлар</b>\n")]
        totals = {}
        for doc in moves[:30]:
            ccy = doc["currency"]
            label = ccy.currency_unit_label or ccy.name
            totals[label] = totals.get(label, 0.0) + doc["residual"]
            body.append("%s  %s  <b>%s %s</b>" % (
                doc["name"], day(doc["due"]) if doc["due"] else "", money(doc["residual"]), label))
        body.append("")
        body.append(_("Жами: <b>%s</b>", ", ".join("%s %s" % (money(v), k) for k, v in totals.items())))
        if len(moves) > 30:
            body.append(_("(биринчи 30 таси курсатилди)"))
        return self._api().send_message(
            chat.chat_id, "\n".join(body), keyboard=self._menu_keyboard(chat))

    def _api(self):
        return self.env["cst.telegram.api"].sudo()
