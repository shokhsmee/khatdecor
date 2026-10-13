import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError

SUPPORTED = (".xlsx", ".xls", ".csv", ".ofx", ".qif", ".camt", ".xml")


class CstBankStatementImportWizard(models.TransientModel):
    """One door to the bank statement importer.

    Odoo's own importer is reached from a journal's dashboard card.  Reached
    any other way — the generic *Import a File* screen, for instance — the
    file is imported as plain journal entries, "Debet" lands on *Journal
    Items / Debit* and every row fails with *The entry is not balanced*.  The
    columns are only offered as Debit / Credit / Cumulative Balance when the
    importer is opened from the journal, so this wizard makes that the easy
    path instead of the hidden one.
    """

    _name = "cst.bank.statement.import.wizard"
    _description = "Bank vipiskasini yuklash"

    journal_id = fields.Many2one(
        "account.journal", string="Jurnal", required=True,
        domain="[('type', 'in', ('bank', 'cash', 'credit')), ('company_id', '=', company_id)]",
        default=lambda self: self._default_journal(),
        help="Виписка кайси кассага ёки банк хисобига тегишли.")
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company)
    file = fields.Binary(string="Fayl", required=True, attachment=False)
    file_name = fields.Char()
    formats = fields.Char(compute="_compute_formats", string="Qo'llab-quvvatlanadi")

    @api.model
    def _default_journal(self):
        return self.env["account.journal"].search([
            ("company_id", "=", self.env.company.id),
            ("type", "=", "bank"),
        ], limit=1)

    def _compute_formats(self):
        supported = ", ".join(
            self.env["account.journal"]._get_bank_statements_available_import_formats())
        for wizard in self:
            wizard.formats = supported

    def action_import(self):
        self.ensure_one()
        if not self.file_name or not self.file_name.lower().endswith(SUPPORTED):
            raise UserError(_(
                "«%(name)s» — бу формат кутилмаган.\n\nЮкланадиган форматлар: %(formats)s",
                name=self.file_name or "?", formats=self.formats))
        if not self.journal_id.default_account_id:
            raise UserError(_(
                "«%s» журналида асосий хисоб курсатилмаган, шунинг учун випискани "
                "юклаб булмайди.", self.journal_id.display_name))

        attachment = self.env["ir.attachment"].create({
            "name": self.file_name,
            "raw": base64.b64decode(self.file),
        })
        # Exactly what the journal's own upload zone calls.
        return self.journal_id.create_document_from_attachment(attachment.ids)
