from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    cst_kassa_allow_reopen = fields.Boolean(
        related="company_id.cst_kassa_allow_reopen", readonly=False)
    cst_kassa_client_tag_ids = fields.Many2many(
        related="company_id.cst_kassa_client_tag_ids", readonly=False)
    cst_kassa_supplier_tag_ids = fields.Many2many(
        related="company_id.cst_kassa_supplier_tag_ids", readonly=False)
    cst_kassa_employee_tag_ids = fields.Many2many(
        related="company_id.cst_kassa_employee_tag_ids", readonly=False)
