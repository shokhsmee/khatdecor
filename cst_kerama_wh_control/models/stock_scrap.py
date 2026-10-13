from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .stock_picking import is_wh_supervisor


class StockScrap(models.Model):
    _inherit = "stock.scrap"

    cst_photo_ids = fields.Many2many(
        "ir.attachment", "cst_scrap_photo_rel", "scrap_id", "attachment_id",
        string="Photos", copy=False,
        help="Photographic proof of the scrapped goods. Required to validate.")
    cst_photo_count = fields.Integer(compute="_compute_cst_photo_count")

    @api.depends("cst_photo_ids")
    def _compute_cst_photo_count(self):
        for scrap in self:
            scrap.cst_photo_count = len(scrap.cst_photo_ids)

    def _cst_check_photo(self):
        if is_wh_supervisor(self.env):
            return
        for scrap in self:
            if not scrap.cst_photo_ids:
                raise UserError(_(
                    "Attach a photo of the goods before closing scrap %s.\n\n"
                    "Use the Photos field on the scrap order.",
                    scrap.name or ""))

    def action_validate(self):
        # checked here so the user is told before any wizard opens
        self._cst_check_photo()
        return super().action_validate()

    def do_scrap(self):
        # and again here, because this is what actually performs the scrap:
        # the insufficient-quantity wizard calls it without going through
        # action_validate.
        self._cst_check_photo()
        return super().do_scrap()
