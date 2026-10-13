import base64
import io
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Whatever the bank calls the columns, these are the three things needed.
HEADERS = {
    "pinfl": ("pinfl", "jshshir", "jshshir (pinfl)", "пинфл", "жшшир", "жшшир (пинфл)",
              "инн физ лица", "shaxsiy raqam", "identifikatsiya raqami"),
    "amount": ("summa", "сумма", "amount", "miqdor", "to'lov", "tolov",
               "сумма перечисления", "перечислено", "сумма к выплате", "karta summa"),
    "name": ("fio", "f.i.o.", "fio (ism)", "ism", "xodim", "ходим", "сотрудник",
             "ф.и.о.", "фио", "name", "ism familiya"),
}


def digits(value):
    return re.sub(r"\D", "", str(value or ""))


class CstPayrollCardImportWizard(models.TransientModel):
    """Load the bank's card-transfer list and turn it into payroll lines.

    Two steps on purpose: money is being written onto people's accounts, so
    the file is parsed and shown first, and nothing is created until someone
    has looked at what matched and what did not.
    """

    _name = "cst.payroll.card.import.wizard"
    _description = "Kartaga o'tkazilgan pullarni yuklash"

    state = fields.Selection(
        [("upload", "Fayl"), ("preview", "Tekshirish")],
        default="upload", required=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    component_id = fields.Many2one(
        "cst.payroll.component", string="Qaysi ustunga", required=True,
        domain="[('kind', '=', 'deduction')]",
        default=lambda self: self.env.ref(
            "cst_kerama_payroll.component_avans_plastik", raise_if_not_found=False),
        help="Картага утказилган пул ходимга берилган пул — ушланмалар "
             "устунига тушади.")
    date = fields.Date(required=True, default=fields.Date.context_today)
    period_id = fields.Many2one(
        "cst.payroll.period", string="Davr",
        domain="[('company_id', '=', company_id), ('state', 'in', ('draft', 'computed'))]")
    file = fields.Binary(string="Excel fayl", attachment=False)
    file_name = fields.Char()

    line_ids = fields.One2many(
        "cst.payroll.card.import.line", "wizard_id", string="Qatorlar")
    matched_count = fields.Integer(compute="_compute_counts")
    unmatched_count = fields.Integer(compute="_compute_counts")
    duplicate_count = fields.Integer(compute="_compute_counts")
    matched_total = fields.Monetary(compute="_compute_counts", currency_field="currency_id")

    @api.depends("line_ids.state", "line_ids.amount")
    def _compute_counts(self):
        for wizard in self:
            lines = wizard.line_ids
            matched = lines.filtered(lambda line: line.state == "matched")
            wizard.matched_count = len(matched)
            wizard.unmatched_count = len(lines) - len(matched)
            wizard.duplicate_count = len(lines.filtered(lambda line: line.is_duplicate))
            wizard.matched_total = sum(matched.mapped("amount"))

    # ------------------------------------------------------------------
    # Reading the file
    # ------------------------------------------------------------------
    def _rows(self):
        """(header index map, data rows) from the uploaded workbook."""
        self.ensure_one()
        import openpyxl

        try:
            book = openpyxl.load_workbook(
                io.BytesIO(base64.b64decode(self.file)), data_only=True, read_only=True)
        except Exception as error:                       # noqa: BLE001
            raise UserError(_(
                "«%(name)s» файлини укиб булмади.  Excel (.xlsx) файл юкланг.\n\n%(error)s",
                name=self.file_name or "?", error=error)) from error

        sheet = book.active
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            raise UserError(_("Файл буш."))

        columns, header_row = {}, None
        for index, row in enumerate(rows[:10]):
            found = {}
            for position, cell in enumerate(row):
                label = str(cell or "").strip().lower()
                for key, aliases in HEADERS.items():
                    if label in aliases and key not in found:
                        found[position] = key
            if "pinfl" in found.values() and "amount" in found.values():
                columns, header_row = found, index
                break
        if header_row is None:
            raise UserError(_(
                "Файлда ЖШШИР ва сумма устунлари топилмади.\n\n"
                "Сарлавха каторида «PINFL» (ёки ЖШШИР) ва «Summa» (ёки Сумма) "
                "деб ёзилган устунлар булиши керак."))
        return columns, rows[header_row + 1:]

    def action_parse(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_("Аввал файлни юкланг."))
        columns, rows = self._rows()

        Employee = self.env["hr.employee"].sudo()
        by_pinfl = {
            employee.cst_pinfl: employee
            for employee in Employee.search([("cst_pinfl", "!=", False)])
        }
        values = []
        for row in rows:
            cells = {key: (row[position] if position < len(row) else None)
                     for position, key in columns.items()}
            pinfl = digits(cells.get("pinfl"))
            raw_amount = cells.get("amount")
            if not pinfl and not raw_amount:
                continue                                   # a blank filler row
            try:
                amount = float(str(raw_amount).replace(" ", "").replace(",", ".") or 0)
            except ValueError:
                amount = 0.0
            employee = by_pinfl.get(pinfl)
            values.append((0, 0, {
                "pinfl": pinfl or False,
                "file_name_text": str(cells.get("name") or "") or False,
                "amount": amount,
                "employee_id": employee.id if employee else False,
                "state": "matched" if (employee and amount) else "unmatched",
                "reason": self._reason(pinfl, amount, employee),
            }))
        if not values:
            raise UserError(_("Файлда бирорта катор топилмади."))
        self.write({"line_ids": [(5, 0, 0)] + values, "state": "preview"})
        self.line_ids._flag_duplicates(self.component_id, self.date)
        return self._reopen()

    def _reason(self, pinfl, amount, employee):
        if not pinfl:
            return _("ЖШШИР ёзилмаган")
        if len(pinfl) != 14:
            return _("ЖШШИР 14 та ракам эмас")
        if not employee:
            return _("Бу ЖШШИР билан ходим топилмади")
        if not amount:
            return _("Сумма нол")
        return False

    def action_back(self):
        self.write({"state": "upload"})
        return self._reopen()

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    # ------------------------------------------------------------------
    def action_confirm(self):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda line: line.state == "matched")
        if not lines:
            raise UserError(_(
                "Бирорта катор ходимга бог'ланмади.  Ходимлар картасида "
                "ЖШШИР тулдирилганини текширинг."))
        if self.period_id and self.period_id.state not in ("draft", "computed"):
            raise UserError(_(
                "«%s» даври тасдикланган — унга янги катор кушиб булмайди.",
                self.period_id.name))

        payroll_lines = self.env["cst.payroll.line"].create([{
            "employee_id": line.employee_id.id,
            "component_id": self.component_id.id,
            "company_id": self.company_id.id,
            "date": self.date,
            "period_id": self.period_id.id or False,
            "amount": line.amount,
            "name": self.component_id.name,
            "note": _("Excel: %s", self.file_name or ""),
            "is_manual": True,
        } for line in lines])

        return {
            "type": "ir.actions.act_window",
            "name": _("Юкланди — %s ta qator", len(payroll_lines)),
            "res_model": "cst.payroll.line",
            "view_mode": "list,form",
            "domain": [("id", "in", payroll_lines.ids)],
        }


class CstPayrollCardImportLine(models.TransientModel):
    _name = "cst.payroll.card.import.line"
    _description = "Kartaga o'tkazma qatori"

    wizard_id = fields.Many2one("cst.payroll.card.import.wizard", required=True,
                                ondelete="cascade")
    company_id = fields.Many2one(related="wizard_id.company_id")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    pinfl = fields.Char(string="JSHSHIR")
    file_name_text = fields.Char(string="Fayldagi ism")
    employee_id = fields.Many2one("hr.employee", string="Xodim")
    amount = fields.Monetary(currency_field="currency_id")
    state = fields.Selection(
        [("matched", "Topildi"), ("unmatched", "Topilmadi")], default="unmatched")
    reason = fields.Char(string="Sabab")
    is_duplicate = fields.Boolean(string="Takror?")

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        # A row fixed by hand becomes importable.
        for line in self:
            if line.employee_id and line.amount:
                line.state = "matched"
                line.reason = False

    def _flag_duplicates(self, component, date):
        """Warn when the same person already has this exact amount that day.

        Importing the same file twice is the easy mistake here, and it is
        invisible afterwards — the second set of lines looks just as real.
        """
        existing = self.env["cst.payroll.line"].search([
            ("component_id", "=", component.id),
            ("date", "=", date),
            ("employee_id", "in", self.employee_id.ids),
        ])
        seen = {(line.employee_id.id, round(line.amount, 2)) for line in existing}
        for line in self:
            if line.employee_id and (line.employee_id.id, round(line.amount, 2)) in seen:
                line.is_duplicate = True
                line.reason = _("Шу кунги айнан шундай катор аллакачон бор")
