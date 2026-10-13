from odoo import models
from odoo.addons.account_bank_statement_import_csv.wizard.account_bank_statement_import_csv import (
    Base_ImportImport as StatementCsvImport,
)


class BaseImportImport(models.TransientModel):
    _inherit = "base_import.import"

    def execute_import(self, fields, columns, options, dryrun=False):
        """Let a bank-statement import be *tested* before it is run.

        The standard flow wraps the imported rows in an account.bank.statement
        straight after importing them.  On a dry run base_import has already
        rolled those rows back by then, so the wrapper's Command.set() points
        at records that no longer exist and the "Test" button dies with
        MissingError.

        Skipping only the wrapper — by calling base_import's own
        implementation rather than the statement-aware one — leaves every row
        validated and reported exactly as before, which is the whole point of
        pressing Test.  The real import is untouched.
        """
        testing_a_statement = dryrun and (
            options.get("bank_stmt_import")
            or self.res_model == "account.bank.statement.line"
        )
        if not testing_a_statement:
            return super().execute_import(fields, columns, options, dryrun=dryrun)

        # `bank_stmt_import` stays in the context so the debit/credit and
        # cumulative-balance columns are still parsed by the standard hook.
        return super(
            StatementCsvImport,
            self.with_context(bank_stmt_import=True, auto_statement_processing=False),
        ).execute_import(fields, columns, options, dryrun=True)
