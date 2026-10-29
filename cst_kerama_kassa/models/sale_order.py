from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # contacts carrying the company's employee tag (Kassa settings) are not offered as customers
    partner_id = fields.Many2one(domain="[('category_id', 'not in', cst_employee_tag_ids)]")
    cst_employee_tag_ids = fields.Many2many(
        "res.partner.category", compute="_compute_cst_employee_tag_ids", string="Employee tags")

    @api.depends("company_id")
    def _compute_cst_employee_tag_ids(self):
        for order in self:
            company = (order.company_id or self.env.company).sudo()
            order.cst_employee_tag_ids = company.cst_kassa_employee_tag_ids

    def _cst_kassa_invoice(self):
        """The invoice a payment settles when the order has none yet: the whole
        order, posted. (cst_kerama_auto_invoice narrows it to what has left
        the warehouse.)"""
        new = self._create_invoices()
        new.action_post()
        return new
