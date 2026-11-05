import base64
import io
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Whatever the bank calls the columns: a header *containing* one of these
# words (after dropping spaces and punctuation) is that column.
HEADERS = {
    "pinfl": ("pinfl", "пинфл", "jshshir", "жшшир", "жшшр", "инфизлица", "shaxsiyraqam",
              "identifikatsiyaraqam", "персональныйидентификац"),
    "amount": ("summa", "сумма", "amount", "miqdor", "tolov", "тўлов", "толов", "перечислен",
               "квыплате", "зачислен"),
    "name": ("fio", "фио", "фиш", "fish", "familiya", "фамилия", "xodim", "ходим", "сотрудник",
             "работник", "ism", "name", "получател", "oluvchi"),
}

# Uzbek Cyrillic -> one Latin skeleton, so «SAMINJONOV ALISHER» from the bank
# finds «Саминжонов Алишер» in Odoo (and «Abdullayev» finds «Абдуллаев»)
CYR = dict(zip("абвгдезийклмнопрстуфхцчшъыьэюяўқғҳё",
               ["a", "b", "v", "g", "d", "e", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                "u", "f", "x", "s", "ch", "sh", "", "i", "", "e", "yu", "ya", "o", "q", "g", "h", "yo"]))
CYR["ж"] = "j"


def name_key(value):
    text = "".join(CYR.get(ch, ch) for ch in str(value or "").lower())
    text = re.sub(r"[ʻʼ'`’‘]", "", text)
    for old, new in (("ye", "e"), ("yo", "o"), ("ya", "a"), ("yu", "u"), ("x", "h"), ("q", "k"),
                     ("w", "v"), ("ts", "s"), ("dj", "j"), ("iy", "i"), ("y", "i")):
        text = text.replace(old, new)
    text = re.sub(r"(.)\1+", r"\1", text)          # «Абдуллаев» = «Abdulayev»
    words = re.findall(r"[a-z]+", text)
    # surname + first name; the patronymic and «ugli/qizi» vary between files
    return " ".join(sorted(words[:2])) if len(words) >= 2 else ""


def header_key(cell):
    return re.sub(r"[\W_]+", "", str(cell or "").lower())


def digits(value):
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"\D", "", str(value or ""))


def parse_amount(value):
    """A bank amount as a number: «1 500 000», «1\u00a0500\u00a0000», «1,500,000»,
    «1.500.000,50», «1500000.5».  Unreadable -> 0 (the row shows as unmatched)."""
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[\s\u00a0\u202f']", "", str(value or ""))
    if not text:
        return 0.0
    if "," in text and "." in text:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        text = text.replace("." if decimal == "," else ",", "").replace(",", ".")
    elif "," in text:
        # «1,500,000» groups thousands; «1500,5» is a decimal comma
        text = text.replace(",", "") if re.fullmatch(r"-?\d{1,3}(,\d{3})+", text) else text.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3}){2,}", text):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return 0.0


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
    currency_id = fields.Many2one(related="company_id.cst_payroll_currency_id")
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
        for index, row in enumerate(rows[:15]):
            found = {}
            for position, cell in enumerate(row):
                label = header_key(cell)
                if not label or len(label) > 60:
                    continue
                for key, aliases in HEADERS.items():
                    if key not in found.values() and any(alias in label for alias in aliases):
                        found[position] = key
                        break
            keys = set(found.values())
            if "amount" in keys and keys & {"pinfl", "name"}:
                columns, header_row = found, index
                break
        if header_row is None:
            raise UserError(_(
                "Файлда сумма ва ЖШШИР (ёки Ф.И.О.) устунлари топилмади.\n\n"
                "Сарлавха каторида «Сумма» ва «ПИНФЛ» ёки «ФИО» сузлари булган "
                "устунлар булиши керак.  Намуна: «Shablon» тугмаси."))
        return columns, rows[header_row + 1:]

    def action_parse(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_("Аввал файлни юкланг."))
        columns, rows = self._rows()

        Employee = self.env["hr.employee"].sudo()
        employees = Employee.search([("company_id", "=", self.company_id.id)])
        by_pinfl = {employee.cst_pinfl: employee for employee in employees if employee.cst_pinfl}
        by_name = {}
        for employee in employees:
            by_name.setdefault(name_key(employee.name), Employee)
            by_name[name_key(employee.name)] |= employee
        by_name.pop("", None)
        values = []
        for row in rows:
            cells = {key: (row[position] if position < len(row) else None)
                     for position, key in columns.items()}
            pinfl = digits(cells.get("pinfl"))
            raw_amount = cells.get("amount")
            if not pinfl and not raw_amount:
                continue                                   # a blank filler row
            amount = parse_amount(raw_amount)
            file_name = str(cells.get("name") or "").strip()
            if not amount and not file_name and not pinfl:
                continue
            if not pinfl and re.match(r"(итого|всего|jami|жами|total)\b", file_name.lower()):
                continue                                   # the bank's total row
            employee = by_pinfl.get(pinfl)
            by_name_match = False
            if not employee and file_name:
                found = by_name.get(name_key(file_name), Employee)
                if len(found) == 1 and not (pinfl and found.cst_pinfl and found.cst_pinfl != pinfl):
                    employee, by_name_match = found, True
            values.append((0, 0, {
                "pinfl": pinfl or False,
                "file_name_text": file_name or False,
                "amount": amount,
                "employee_id": employee.id if employee else False,
                "by_name": by_name_match,
                "reason": _("Ism bo'yicha topildi — tekshiring") if by_name_match
                else self._reason(pinfl, amount, employee),
            }))
        if not values:
            raise UserError(_("Файлда бирорта катор топилмади."))
        self.write({"line_ids": [(5, 0, 0)] + values, "state": "preview"})
        self.line_ids._flag_duplicates(self.component_id, self.date)
        return self._reopen()

    def _reason(self, pinfl, amount, employee):
        if not amount:
            return _("Сумма нол")
        if employee:
            return False
        if not pinfl:
            return _("ЖШШИР ёзилмаган, исм буйича хам топилмади — ходимни танланг")
        if len(pinfl) != 14:
            return _("ЖШШИР 14 та ракам эмас — ходимни танланг")
        return _("Бу ЖШШИР ва исм билан ходим топилмади — ходимни танланг")

    def action_download_template(self):
        """A ready file in the shape the import reads."""
        import openpyxl
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.title = "Kartaga"
        sheet.append(["ПИНФЛ", "ФИО", "Сумма"])
        for employee in self.env["hr.employee"].sudo().search(
                [("company_id", "=", self.company_id.id)], order="name"):
            sheet.append([employee.cst_pinfl or "", employee.name, None])
        sheet.column_dimensions["A"].width = 18
        sheet.column_dimensions["B"].width = 40
        sheet.column_dimensions["C"].width = 16
        stream = io.BytesIO()
        book.save(stream)
        attachment = self.env["ir.attachment"].create({
            "name": "kartaga_otkazma_shablon.xlsx",
            "datas": base64.b64encode(stream.getvalue()),
            "res_model": self._name, "res_id": self.id,
        })
        return {"type": "ir.actions.act_url", "url": "/web/content/%s?download=true" % attachment.id,
                "target": "self"}

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
        lines = self.line_ids.filtered(lambda line: line.state == "matched" and not line.is_duplicate)
        if not lines:
            raise UserError(_(
                "Бирорта катор ходимга бог'ланмади.  Ходимлар картасида "
                "ЖШШИР тулдирилганини текширинг."))
        if self.period_id and self.period_id.state not in ("draft", "computed"):
            raise UserError(_(
                "«%s» даври тасдикланган — унга янги катор кушиб булмайди.",
                self.period_id.name))

        # a PINFL learnt from the file: next month the row matches by itself
        taken = set(self.env["hr.employee"].sudo().search([("cst_pinfl", "in", lines.mapped("pinfl"))]).mapped("cst_pinfl"))
        for line in lines:
            if line.pinfl and len(line.pinfl) == 14 and not line.employee_id.sudo().cst_pinfl \
                    and line.pinfl not in taken:
                line.employee_id.sudo().cst_pinfl = line.pinfl
                taken.add(line.pinfl)
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
    # follows the row: an employee picked by hand makes it importable
    state = fields.Selection(
        [("matched", "Topildi"), ("unmatched", "Topilmadi")],
        compute="_compute_state", store=True)
    reason = fields.Char(string="Sabab")
    by_name = fields.Boolean(string="Ism bo'yicha", readonly=True)
    is_duplicate = fields.Boolean(
        string="Takror?", help="Takror qatorlar yuklanmaydi. Ataylab bo'lsa — belgini olib tashlang.")

    @api.depends("employee_id", "amount")
    def _compute_state(self):
        for line in self:
            line.state = "matched" if (line.employee_id and line.amount) else "unmatched"

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        for line in self:
            if line.employee_id and line.amount and not line.is_duplicate:
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
        in_file = set()
        for line in self:
            key = (line.employee_id.id, round(line.amount, 2))
            if line.employee_id and key in seen:
                line.is_duplicate = True
                line.reason = _("Шу кунги айнан шундай катор аллакачон бор")
            elif line.employee_id and key in in_file:
                line.is_duplicate = True
                line.reason = _("Файлда шу катор икки марта")
            in_file.add(key)
