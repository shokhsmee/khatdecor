from odoo import api, fields, models


class MoizvonkiSettings(models.Model):
    _name = "moizvonki.settings"
    _description = "Moizvonki Settings"
    _rec_name = "id"

    # We keep a single record (singleton)
    moizvonki_domain = fields.Char(string="Moizvonki domain (subdomain)")
    moizvonki_user_name = fields.Char(string="Moizvonki user email")
    moizvonki_api_key = fields.Char(string="Moizvonki API key")
    moizvonki_webhook_secret = fields.Char(string="Webhook secret (optional)")

    @api.model
    def get_singleton(self):
        rec = self.search([], limit=1)
        if not rec:
            rec = self.create({})
            rec._load_from_params()
        return rec

    def _load_from_params(self):
        ICP = self.env["ir.config_parameter"].sudo()
        for rec in self:
            rec.moizvonki_domain = ICP.get_param("moizvonki.domain", "")
            rec.moizvonki_user_name = ICP.get_param("moizvonki.user_name", "")
            rec.moizvonki_api_key = ICP.get_param("moizvonki.api_key", "")
            rec.moizvonki_webhook_secret = ICP.get_param("moizvonki.webhook_secret", "")

    def _save_to_params(self):
        ICP = self.env["ir.config_parameter"].sudo()
        for rec in self:
            ICP.set_param("moizvonki.domain", rec.moizvonki_domain or "")
            ICP.set_param("moizvonki.user_name", rec.moizvonki_user_name or "")
            ICP.set_param("moizvonki.api_key", rec.moizvonki_api_key or "")
            ICP.set_param("moizvonki.webhook_secret", rec.moizvonki_webhook_secret or "")

    def write(self, vals):
        res = super().write(vals)
        self._save_to_params()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs._save_to_params()
        return recs
