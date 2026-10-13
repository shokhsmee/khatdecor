from odoo import api, models
from odoo.tools import format_amount


class SaleOrder(models.Model):
    _inherit = "sale.order"

    @api.model
    def get_dashboard_values(self):
        """Re-scope the mini-dashboard money totals to the active company.

        The base sale_mini_dashboard module sums amount_total with raw SQL and
        no company filter, so every filial shows the all-company total. The
        record counts already respect the company rules; only the two amount
        figures leak, so we recompute just those, filtered by the companies
        currently selected in the switcher (self.env.companies)."""
        result = super().get_dashboard_values()
        company_ids = tuple(self.env.companies.ids) or (0,)

        self.env.cr.execute(
            "SELECT COALESCE(SUM(amount_total), 0) FROM sale_order "
            "WHERE state IN ('sale', 'done') AND company_id IN %s",
            (company_ids,))
        sale_amount = self.env.cr.fetchone()[0]

        self.env.cr.execute(
            "SELECT COALESCE(SUM(amount_total), 0) FROM sale_order "
            "WHERE state IN ('draft', 'sent') AND company_id IN %s",
            (company_ids,))
        draft_amount = self.env.cr.fetchone()[0]

        currency = self.env.company.currency_id
        result['total_sale_amount'] = format_amount(self.env, sale_amount, currency)
        result['total_draft_amount'] = format_amount(self.env, draft_amount, currency)
        return result
