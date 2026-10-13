from odoo import models

MONEY_TYPES = ("bank", "cash", "credit")


class AccountJournal(models.Model):
    _inherit = "account.journal"

    # ------------------------------------------------------------------
    # What is in the journal
    # ------------------------------------------------------------------
    def _cst_liquidity_accounts(self):
        """The accounts this journal's money can be sitting in."""
        self.ensure_one()
        return (
            self.default_account_id
            | self.inbound_payment_method_line_ids.payment_account_id
            | self.outbound_payment_method_line_ids.payment_account_id
        )

    def _cst_money_balances(self):
        """{journal id: balance} for bank, cash and credit journals.

        Counted as everything this journal posted to its own account and to its
        outstanding accounts, plus whatever other journals posted to its own
        account (a misc entry correcting the bank, say).

        The outstanding accounts cannot simply be summed: Odoo hands the same
        Outstanding Receipts and Outstanding Payments accounts to every bank
        journal of the company, so summing them per journal would show each
        journal the whole company's money.  Hence the split by journal.
        """
        AccountMoveLine = self.env["account.move.line"]
        balances = {}
        for journal in self:
            accounts = journal._cst_liquidity_accounts()
            if not accounts:
                balances[journal.id] = 0.0
                continue
            # A journal held in a FOREIGN currency keeps its real amount in
            # amount_currency.  When the journal currency is the company's own,
            # amount_currency is not reliably filled - balance is the figure.
            foreign = (
                journal.currency_id
                and journal.currency_id != journal.company_id.currency_id
            )
            field = "amount_currency" if foreign else "balance"
            base = [
                ("parent_state", "=", "posted"),
                ("company_id", "=", journal.company_id.id),
            ]
            own = AccountMoveLine._read_group(
                domain=base + [
                    ("account_id", "in", accounts.ids),
                    ("journal_id", "=", journal.id),
                ],
                aggregates=[f"{field}:sum"],
            )
            total = own[0][0] or 0.0
            if journal.default_account_id:
                elsewhere = AccountMoveLine._read_group(
                    domain=base + [
                        ("account_id", "=", journal.default_account_id.id),
                        ("journal_id", "!=", journal.id),
                    ],
                    aggregates=[f"{field}:sum"],
                )
                total += elsewhere[0][0] or 0.0
            balances[journal.id] = total
        return balances

    def _cst_open_balances(self):
        """{journal id: still owed} for sale and purchase journals."""
        AccountMove = self.env["account.move"]
        balances = {}
        for journal in self:
            groups = AccountMove._read_group(
                domain=[
                    ("journal_id", "=", journal.id),
                    ("state", "=", "posted"),
                    ("payment_state", "not in", ("paid", "reversed", "invoicing_legacy")),
                ],
                aggregates=["amount_residual_signed:sum"],
            )
            balances[journal.id] = groups[0][0] or 0.0
        return balances

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    def _get_journal_dashboard_data_batched(self):
        dashboard_data = super()._get_journal_dashboard_data_batched()

        money = self.filtered(lambda journal: journal.type in MONEY_TYPES)
        for journal_id, amount in money._cst_money_balances().items():
            journal = self.browse(journal_id)
            currency = journal.currency_id or journal.company_id.sudo().currency_id
            dashboard_data[journal_id].update({
                "cst_balance": currency.format(amount),
                "cst_balance_label": self.env._("Balance"),
                "cst_balance_visible": True,
            })

        open_items = self.filtered(lambda journal: journal.type in ("sale", "purchase"))
        for journal_id, amount in open_items._cst_open_balances().items():
            journal = self.browse(journal_id)
            currency = journal.currency_id or journal.company_id.sudo().currency_id
            dashboard_data[journal_id].update({
                "cst_balance": currency.format(amount),
                "cst_balance_label": self.env._("Still Owed"),
                "cst_balance_visible": True,
            })

        return dashboard_data

    def action_cst_open_journal_items(self):
        """The journal items behind the balance on the card."""
        self.ensure_one()
        if self.type in MONEY_TYPES:
            domain = [
                ("account_id", "in", self._cst_liquidity_accounts().ids),
                ("parent_state", "=", "posted"),
            ]
            name = self.env._("Balance of %s", self.display_name)
        else:
            domain = [("journal_id", "=", self.id), ("parent_state", "=", "posted")]
            name = self.env._("Journal Items of %s", self.display_name)
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": "account.move.line",
            "view_mode": "list,form",
            "domain": domain,
            "context": {"search_default_group_by_account": 1},
        }
