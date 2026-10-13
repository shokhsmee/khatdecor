from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CstFuelReportWizard(models.TransientModel):
    """«Yoqilg'i hisoboti» — which fuel, which machines, which period."""

    _name = "cst.fuel.report.wizard"
    _description = "Yoqilg'i hisoboti"

    date_from = fields.Date(
        string="Davr boshi", required=True,
        default=lambda self: fields.Date.start_of(fields.Date.context_today(self), "month"))
    date_to = fields.Date(
        string="Davr oxiri", required=True,
        default=lambda self: fields.Date.context_today(self))
    product_ids = fields.Many2many(
        "product.product", string="Yoqilg'i turi",
        domain="[('cst_is_fuel', '=', True)]",
        help="Bo'sh qoldirilsa, barcha yoqilg'i turlari birga hisoblanadi.")
    machine_ids = fields.Many2many("cst.fuel.machine", string="Mashinalar")
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
        data = self.env["cst.fuel.report"].build(
            self.date_from, self.date_to,
            product_ids=self.product_ids.ids or None,
            machine_ids=self.machine_ids.ids or None,
            company_ids=self.company_ids.ids or None)
        return {
            "wizard": self,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "data": data,
            "title": "Yoqilg'i hisoboti",
        }

    def action_print(self):
        return self.env.ref(
            "cst_kerama_reports.action_report_fuel").report_action(self)

    def action_view(self):
        return self.env.ref(
            "cst_kerama_reports.action_report_fuel_html").report_action(self)
