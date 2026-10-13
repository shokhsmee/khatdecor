from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CstPartnerStatementWizard(models.TransientModel):
    """«Akt sverka» — one counterparty's card over a period."""

    _name = "cst.partner.statement.wizard"
    _description = "Akt sverka"

    partner_id = fields.Many2one("res.partner", string="Kontragent", required=True)
    date_from = fields.Date(
        string="Davr boshi", required=True,
        default=lambda self: fields.Date.start_of(fields.Date.context_today(self), "year"))
    date_to = fields.Date(
        string="Davr oxiri", required=True,
        default=lambda self: fields.Date.context_today(self))
    company_ids = fields.Many2many(
        "res.company", string="Kompaniyalar",
        default=lambda self: self.env.companies)

    @api.constrains("date_from", "date_to")
    def _check_period(self):
        for wizard in self:
            if wizard.date_to < wizard.date_from:
                raise UserError(_("Davr oxiri boshidan oldin bo'lishi mumkin emas."))

    def _report_values(self):
        self.ensure_one()
        engine = self.env["cst.partner.statement"]
        return {
            "wizard": self,
            "partner": self.partner_id,
            "title": "Akt sverka: %s" % self.partner_id.display_name,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "companies": engine.statement_rows(
                self.partner_id, self.date_from, self.date_to,
                company_ids=self.company_ids.ids or None),
        }

    def action_print(self):
        return self.env.ref(
            "cst_kerama_reports.action_report_partner_statement").report_action(self)

    def action_view(self):
        return self.env.ref(
            "cst_kerama_reports.action_report_partner_statement_html").report_action(self)
