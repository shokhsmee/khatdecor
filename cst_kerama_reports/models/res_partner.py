import re

from odoo import _, fields, models
from odoo.fields import Domain

_WORD = re.compile(r"[^\s,;]+")


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _search_display_name(self, operator, value):
        """Word-by-word contact search (05.11, «Поискини тугирлаш»).

        Odoo matches the typed text as one piece: «тож ака мар» never finds
        «Тожиддин ака Маргилон».  Here every word must appear somewhere in
        Odoo's own criteria (name, company name, email, reference, VAT…),
        in any order — the same rule the product search already follows.
        """
        words = _WORD.findall(value) if isinstance(value, str) else []
        if operator not in ("ilike", "like") or len(words) < 2:
            return super()._search_display_name(operator, value)
        parent = super()
        return Domain.AND([Domain(parent._search_display_name(operator, word)) for word in words])

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
