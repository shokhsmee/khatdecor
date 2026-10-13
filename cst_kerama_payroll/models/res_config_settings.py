from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    cst_payroll_journal_id = fields.Many2one(
        related="company_id.cst_payroll_journal_id", readonly=False)
    cst_salary_payable_account_id = fields.Many2one(
        related="company_id.cst_salary_payable_account_id", readonly=False)
    cst_salary_expense_account_id = fields.Many2one(
        related="company_id.cst_salary_expense_account_id", readonly=False)
    cst_salary_expense_cash_account_id = fields.Many2one(
        related="company_id.cst_salary_expense_cash_account_id", readonly=False)
    cst_employee_tax_account_id = fields.Many2one(
        related="company_id.cst_employee_tax_account_id", readonly=False)
    cst_employer_tax_account_id = fields.Many2one(
        related="company_id.cst_employer_tax_account_id", readonly=False)
    cst_income_tax_rate = fields.Float(
        related="company_id.cst_income_tax_rate", readonly=False)
    cst_pension_rate = fields.Float(
        related="company_id.cst_pension_rate", readonly=False)
    cst_social_tax_rate = fields.Float(
        related="company_id.cst_social_tax_rate", readonly=False)
    cst_unload_rate_default = fields.Monetary(
        related="company_id.cst_unload_rate_default", readonly=False)
