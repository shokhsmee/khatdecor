from odoo import api, fields, models


class AccountJournal(models.Model):
    _inherit = "account.journal"

    cst_prevent_negative_balance = fields.Boolean(
        string="Prevent Negative Balance",
        compute="_compute_cst_prevent_negative_balance", store=True, readonly=False,
        help="Refuse to post an entry that would take this journal's account "
             "below zero — a cash box cannot pay out money it does not hold. "
             "On by default for cash journals.")

    @api.depends("type")
    def _compute_cst_prevent_negative_balance(self):
        for journal in self:
            journal.cst_prevent_negative_balance = journal.type == "cash"
