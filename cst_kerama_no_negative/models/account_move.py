from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


def bypasses_cash_guard(env):
    """True when the current user (or caller) may take a cash box below zero."""
    return bool(
        env.context.get("cst_allow_negative")
        or env.user.has_group("cst_kerama_no_negative.group_allow_negative_cash")
    )


class AccountMove(models.Model):
    _inherit = "account.move"

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        posted._cst_check_cash_not_negative()
        return posted

    def _cst_check_cash_not_negative(self):
        """Refuse the posting when a guarded cash account ends up below zero.

        Checked after posting so the entry being posted is included; raising
        here rolls the whole posting back.
        """
        if bypasses_cash_guard(self.env):
            return
        watched = self.env["account.journal"].sudo().search([
            ("cst_prevent_negative_balance", "=", True),
        ]).default_account_id
        if not watched:
            return

        pairs = set()
        for move in self:
            for account in move.line_ids.account_id:
                if account in watched:
                    pairs.add((account.id, move.company_id.id))

        Line = self.env["account.move.line"].sudo()
        for account_id, company_id in pairs:
            company = self.env["res.company"].browse(company_id)
            account = self.env["account.account"].browse(account_id)
            groups = Line._read_group(
                [("account_id", "=", account_id),
                 ("company_id", "=", company_id),
                 ("parent_state", "=", "posted")],
                groupby=[], aggregates=["balance:sum"])
            balance = (groups[0][0] if groups else 0.0) or 0.0
            if float_compare(balance, 0.0,
                             precision_rounding=company.currency_id.rounding) < 0:
                raise UserError(_(
                    "The cash box cannot go negative.\n\n"
                    "%(account)s would end at %(balance).2f %(currency)s.\n\n"
                    "Register the incoming cash first, or ask someone with the "
                    "\"Allow Negative Cash\" right to post this.",
                    account=account.display_name,
                    balance=balance,
                    currency=company.currency_id.name))
