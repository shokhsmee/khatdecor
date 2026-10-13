from odoo import _, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    def action_cst_akt_sverka(self):
        """Open this counterparty's akt sverka, dates ready to adjust."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Akt sverka: %s", self.display_name),
            "res_model": "cst.partner.statement.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_partner_id": self.commercial_partner_id.id or self.id,
                "default_date_from": fields.Date.start_of(
                    fields.Date.context_today(self), "year"),
                "default_date_to": fields.Date.context_today(self),
            },
        }
