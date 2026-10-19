from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResCompany(models.Model):
    _inherit = "res.company"

    @api.model
    def _cst_default_payroll_currency(self):
        uzs = self.env.ref("base.UZS", raise_if_not_found=False)
        return uzs if uzs and uzs.active else self.env.company.currency_id

    # Salaries are agreed and paid in so'm while the books are kept in dollars
    # since the 20.09 switch: every payroll amount (wage, KPI, advances, the
    # report) lives in this currency; only the journal entry converts.
    cst_payroll_currency_id = fields.Many2one(
        "res.currency", string="Oylik valyutasi",
        default=lambda self: self._cst_default_payroll_currency(),
        help="Oklad, KPI, avans, jarima va oylik hisoboti shu valyutada yuritiladi. "
             "Buxgalteriya provodkasi kompaniya valyutasiga davrdagi kurs bo'yicha o'tkaziladi.")

    cst_payroll_journal_id = fields.Many2one(
        "account.journal", string="Salary Journal",
        domain="[('type', '=', 'general'), ('company_id', '=', id)]",
        check_company=True,
        help="Journal that carries the payroll entries.")
    cst_salary_payable_account_id = fields.Many2one(
        "account.account", string="Salary Payable Account", check_company=True,
        help="What the company owes its employees.  Must be a payable-type "
             "account, otherwise Odoo will not keep a per-employee balance.")
    cst_salary_expense_account_id = fields.Many2one(
        "account.account", string="Salary Expense (Official)", check_company=True)
    cst_salary_expense_cash_account_id = fields.Many2one(
        "account.account", string="Salary Expense (Cash)", check_company=True,
        help="Expense account for the undeclared part, kept apart so the "
             "official profit and loss can be read on its own.")
    cst_employee_tax_account_id = fields.Many2one(
        "account.account", string="Employee Tax Payable", check_company=True,
        help="Income tax and pension withheld from employees, owed to the state.")
    cst_employer_tax_account_id = fields.Many2one(
        "account.account", string="Employer Tax Payable", check_company=True)

    # Rates are configuration, never constants: they change from year to year
    # and a wrong value silently corrupts every report built on them.
    cst_income_tax_rate = fields.Float(
        string="Income Tax (%)", digits=(5, 3),
        help="Даромад солиғи (ЖШДС) withheld from the employee.")
    cst_pension_rate = fields.Float(
        string="Pension / INPS (%)", digits=(5, 3),
        help="Withheld from the employee.")
    cst_unload_rate_default = fields.Monetary(
        string="Default Unloading Payment", currency_field="cst_payroll_currency_id",
        help="Юк туширган хар бир ходим учун таклиф килинадиган сумма.  "
             "Хужжатда узгартириш мумкин — бу факат бошлангич киймат.")

    cst_social_tax_rate = fields.Float(
        string="Social Tax (%)", digits=(5, 3),
        help="Ижтимоий солиқ, borne by the employer.  An expense, not a "
             "deduction — it never touches the employee's balance.")

    def _cst_payroll_currency(self):
        self.ensure_one()
        return self.cst_payroll_currency_id or self.currency_id

    def _cst_payroll_rate(self, date):
        """Units of the payroll currency per one unit of the company currency
        (so'm per dollar) on ``date``.  Odoo's own rates here; the kassa
        module answers with the rate the cashier opened the day with."""
        self.ensure_one()
        pay = self._cst_payroll_currency()
        if pay == self.currency_id:
            return 1.0
        return self.currency_id._get_conversion_rate(self.currency_id, pay, self, date)

    def write(self, vals):
        if vals.get("cst_payroll_currency_id") and "cst.payroll.line" in self.env:
            for company in self:
                if company.cst_payroll_currency_id.id == vals["cst_payroll_currency_id"]:
                    continue
                if self.env["cst.payroll.line"].sudo().search_count([
                        ("company_id", "=", company.id), ("state", "!=", "cancel")], limit=1):
                    raise UserError(_(
                        "%s: oylik qatorlari allaqachon bor — oylik valyutasini endi o'zgartirib bo'lmaydi "
                        "(eski summalar boshqa valyutada qolib ketadi).", company.name))
        return super().write(vals)
