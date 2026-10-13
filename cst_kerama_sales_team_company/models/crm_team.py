from odoo import api, fields, models
from odoo.tools import SQL


class CrmTeam(models.Model):
    _inherit = "crm.team"

    @api.depends_context("allowed_company_ids")
    def _compute_invoiced(self):
        """Same as the native sale computation, but scoped to the companies
        currently selected in the company switcher so that each filial only
        sees its own invoiced amount (native SQL filters by team_id only)."""
        company_ids = self.env.companies.ids
        if self.ids and company_ids:
            today = fields.Date.today()
            data_map = dict(self.env.execute_query(SQL(
                ''' SELECT
                        move.team_id AS team_id,
                        SUM(move.amount_untaxed_signed) AS amount_untaxed_signed
                    FROM account_move move
                    WHERE move.move_type IN ('out_invoice', 'out_refund', 'out_receipt')
                    AND move.payment_state IN ('in_payment', 'paid', 'reversed')
                    AND move.state = 'posted'
                    AND move.team_id IN %s
                    AND move.company_id IN %s
                    AND move.date BETWEEN %s AND %s
                    GROUP BY move.team_id
                ''',
                tuple(self.ids),
                tuple(company_ids),
                fields.Date.to_string(today.replace(day=1)),
                fields.Date.to_string(today),
            )))
        else:
            data_map = {}

        for team in self:
            team.invoiced = data_map.get(team._origin.id, 0.0)
