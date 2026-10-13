{
    "name": "Khatdecor Telegram Bot",
    "summary": "Customers and suppliers read their own balance and reconciliation "
               "statement in Telegram; the company can message them back.",
    "description": """
Khatdecor Telegram Bot
======================

A Telegram bot that lives inside Odoo — a webhook route, not a second service
to deploy and keep alive.  The data it answers with is the ledger itself, so
there is nothing to synchronise.

**Who is on the other end.**  A conversation starts by asking Telegram for the
person's own phone number (the contact button, so the number is verified by
Telegram rather than typed).  The number is matched on its last nine digits,
because the same partner is stored as ``907570432`` in one record and
``+998907570432`` in another.  When the number matches exactly one partner the
person is asked to confirm the name; when it matches several — one phone number
really is shared by two partners here — the name they type decides.  When it
matches nothing, the chat is parked as a **request** for a manager to link by
hand, which is also how the partner file slowly acquires the phone numbers it
is missing.

**What they can ask for.**  The current balance, the reconciliation statement
(акт сверка) for a period as a chat summary and as the standard Partner Ledger
PDF, and the list of what is still unpaid.  A partner who both buys and sells
can switch sides; a partner who only buys is never shown the supplier side at
all.

**What the company can send.**  A broadcast to customers, to suppliers, or to a
chosen few, from Odoo, with a delivery count.
    """,
    "author": "Khatdecor",
    "category": "Accounting/Accounting",
    "version": "19.0.1.1.0",
    "depends": ["base", "contacts", "account", "account_reports", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "views/telegram_chat_views.xml",
        "views/telegram_broadcast_views.xml",
        "views/res_config_settings_views.xml",
        "views/telegram_menus.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
