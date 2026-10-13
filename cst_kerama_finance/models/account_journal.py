from odoo import api, models


class AccountJournal(models.Model):
    """A liquidity journal is only as good as its outstanding accounts.

    Left empty — which is how Odoo creates them — a payment produces no
    journal entry at all until a bank statement is reconciled against it.  For
    a bank that is a defensible flow; for a cash drawer it means the money is
    simply missing from the books, and nothing on screen says so.
    """

    _inherit = "account.journal"

    def _cst_outstanding_accounts(self):
        """(inbound, outbound) accounts this journal's payments should use."""
        self.ensure_one()
        if self.type not in ("bank", "cash", "credit"):
            return self.env["account.account"], self.env["account.account"]
        if self.type == "cash":
            # The drawer is the destination, not a waiting room: one step, and
            # Odoo marks the payment paid because the account is `asset_cash`.
            return self.default_account_id, self.default_account_id
        chart = self.env["account.chart.template"].with_context(
            allowed_company_ids=self.company_id.root_id.ids)
        return (
            chart.ref("account_journal_payment_debit_account_id", raise_if_not_found=False)
            or self.env["account.account"],
            chart.ref("account_journal_payment_credit_account_id", raise_if_not_found=False)
            or self.env["account.account"],
        )

    def _cst_fill_outstanding_accounts(self):
        """Fill in what is missing, never overwrite a deliberate choice."""
        for journal in self:
            if journal.type not in ("bank", "cash", "credit"):
                continue
            inbound, outbound = journal._cst_outstanding_accounts()
            for lines, account in (
                (journal.inbound_payment_method_line_ids, inbound),
                (journal.outbound_payment_method_line_ids, outbound),
            ):
                if not account:
                    continue
                blank = lines.filtered(lambda line: not line.payment_account_id)
                if blank:
                    blank.payment_account_id = account

    @api.model_create_multi
    def create(self, vals_list):
        journals = super().create(vals_list)
        journals._cst_fill_outstanding_accounts()
        return journals

    def write(self, vals):
        result = super().write(vals)
        # A journal that only just received its default account, or changed
        # type, needs its payment methods pointed somewhere real.
        if {"type", "default_account_id"} & set(vals):
            self._cst_fill_outstanding_accounts()
        return result
