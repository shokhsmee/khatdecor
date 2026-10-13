from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

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
        string="Default Unloading Payment", currency_field="currency_id",
        help="Юк туширган хар бир ходим учун таклиф килинадиган сумма.  "
             "Хужжатда узгартириш мумкин — бу факат бошлангич киймат.")

    cst_social_tax_rate = fields.Float(
        string="Social Tax (%)", digits=(5, 3),
        help="Ижтимоий солиқ, borne by the employer.  An expense, not a "
             "deduction — it never touches the employee's balance.")
