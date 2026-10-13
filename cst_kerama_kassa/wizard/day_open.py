from odoo import _, api, fields, models
from odoo.exceptions import UserError


class KassaDayOpen(models.TransientModel):
    """Opening a cash day starts with the day's dollar rate.  The first kassa to
    open enters it; the others are offered that rate and may keep their own."""

    _name = "cst.kassa.day.open"
    _description = "Open Cash Day"

    kassa_id = fields.Many2one("cst.kassa", required=True, readonly=True)
    date = fields.Date(required=True, readonly=True, default=fields.Date.context_today)
    currency_id = fields.Many2one(related="kassa_id.currency_id")
    company_currency_id = fields.Many2one(related="kassa_id.company_id.currency_id")
    rate_required = fields.Boolean(compute="_compute_reference")
    ref_day_id = fields.Many2one("cst.kassa.day", compute="_compute_reference")
    ref_kassa_name = fields.Char(compute="_compute_reference", string="Rate entered in")
    ref_rate = fields.Float(compute="_compute_reference", digits=(16, 2), string="Today's rate")
    rate_mode = fields.Selection(
        [("same", "Use today's rate"), ("other", "Enter another rate for this kassa")],
        string="Rate", default="same")
    usd_rate = fields.Float(string="Dollar rate", digits=(16, 2),
                           help="How many units of this kassa's currency make one dollar today.")

    @api.depends("kassa_id", "date")
    def _compute_reference(self):
        Day = self.env["cst.kassa.day"].sudo()
        for wiz in self:
            wiz.rate_required = wiz.kassa_id.currency_id != wiz.kassa_id.company_id.currency_id
            ref = Day.search([("date", "=", wiz.date), ("usd_rate", ">", 0),
                              ("kassa_id", "!=", wiz.kassa_id.id)], order="write_date desc", limit=1)
            wiz.ref_day_id = ref
            wiz.ref_kassa_name = ref.kassa_id.name or False
            wiz.ref_rate = ref.usd_rate

    @api.model
    def _cst_suggested_rate(self, kassa):
        """Last rate this kassa used, else the last one any kassa used, else the
        company's official rate for the kassa currency."""
        Day = self.env["cst.kassa.day"].sudo()
        last = Day.search([("kassa_id", "=", kassa.id), ("usd_rate", ">", 0)], order="date desc", limit=1) \
            or Day.search([("usd_rate", ">", 0)], order="date desc, id desc", limit=1)
        if last:
            return last.usd_rate
        company = kassa.company_id
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        if kassa.currency_id != company.currency_id:
            return kassa.currency_id._get_conversion_rate(company.currency_id, kassa.currency_id, company,
                                                          fields.Date.context_today(self))
        uzs = self.env.ref("base.UZS", raise_if_not_found=False)
        if usd and uzs:
            return usd._get_conversion_rate(usd, uzs, company, fields.Date.context_today(self))
        return 0.0

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        kassa = self.env["cst.kassa"].browse(res.get("kassa_id") or self.env.context.get("default_kassa_id"))
        if kassa:
            ref = self.env["cst.kassa.day"].sudo().search(
                [("date", "=", fields.Date.context_today(self)), ("usd_rate", ">", 0),
                 ("kassa_id", "!=", kassa.id)], order="write_date desc", limit=1)
            res["usd_rate"] = ref.usd_rate if ref else round(self._cst_suggested_rate(kassa), 2)
            res["rate_mode"] = "same" if ref else "other"
        return res

    @api.onchange("rate_mode")
    def _onchange_rate_mode(self):
        if self.rate_mode == "same" and self.ref_day_id:
            self.usd_rate = self.ref_rate

    def action_open(self):
        self.ensure_one()
        kassa = self.kassa_id
        kassa._cst_check_cashier()
        rate = self.ref_rate if (self.ref_day_id and self.rate_mode == "same") else self.usd_rate
        if self.rate_required and rate <= 0:
            raise UserError(_("Enter today's dollar rate."))
        if rate < 0:
            raise UserError(_("The rate cannot be negative."))
        Day = self.env["cst.kassa.day"]
        if Day.search_count([("kassa_id", "=", kassa.id), ("date", "=", self.date)]):
            raise UserError(_("Today's cash day of %(kassa)s already exists.", kassa=kassa.name))
        if Day.search_count([("kassa_id", "=", kassa.id), ("state", "=", "open")]):
            raise UserError(_("%(kassa)s already has an open day.", kassa=kassa.name))
        day = Day.create({"kassa_id": kassa.id, "date": self.date, "usd_rate": rate})
        return day._cst_form_action()
