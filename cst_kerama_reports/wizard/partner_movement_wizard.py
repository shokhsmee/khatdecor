from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CstPartnerMovementWizard(models.TransientModel):
    """«Ta'minotchilar / 3-shaxslar harakati» — pick the period, get the sheet.

    The same wizard serves both reports: the counterparty kind arrives in the
    context from the menu, so the two menus produce two reports with two
    titles out of one screen and one engine.
    """

    _name = "cst.partner.movement.wizard"
    _description = "Kontragentlar harakati hisoboti"

    kind = fields.Selection(
        [("supplier", "Ta'minotchilar"), ("third_party", "3-shaxslar"),
         ("customer", "Mijozlar")],
        string="Kimlar bo'yicha", required=True, default="supplier")
    date_from = fields.Date(
        string="Davr boshi", required=True,
        default=lambda self: fields.Date.start_of(fields.Date.context_today(self), "month"))
    date_to = fields.Date(
        string="Davr oxiri", required=True,
        default=lambda self: fields.Date.context_today(self))
    partner_ids = fields.Many2many(
        "res.partner", string="Kontragentlar",
        help="Bo'sh qoldirilsa, tanlangan turdagi barcha kontragentlar chiqadi.")
    company_ids = fields.Many2many(
        "res.company", string="Kompaniyalar",
        default=lambda self: self.env.companies)
    hide_empty = fields.Boolean(
        string="Bo'sh qatorlarni yashirish", default=True,
        help="Davr boshida ham, oxirida ham qoldig'i bo'lmagan va davr ichida "
             "harakat qilmagan kontragentlar chiqmaydi.")

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
            "kind_label": engine.kind_label(self.kind),
            "title": "%s harakati" % engine.kind_label(self.kind),
            "date_from": self.date_from,
            "date_to": self.date_to,
            "companies": engine.movement_rows(
                self.kind, self.date_from, self.date_to,
                partner_ids=self.partner_ids.ids or None,
                company_ids=self.company_ids.ids or None,
                hide_empty=self.hide_empty,
            ),
        }

    def action_print(self):
        return self.env.ref(
            "cst_kerama_reports.action_report_partner_movement").report_action(self)

    def action_view(self):
        return self.env.ref(
            "cst_kerama_reports.action_report_partner_movement_html").report_action(self)
