from odoo import _, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    def _cst_check_kassa_day_lock(self):
        """No money movement may be added to / removed from a confirmed cash day."""
        if self.env.context.get("cst_kassa_skip_guard"):
            return
        kassas = self.env["cst.kassa"].sudo().search([])
        if not kassas:
            return
        Day = self.env["cst.kassa.day"].sudo()
        for move in self:
            for kassa in kassas:
                if kassa.company_id != move.company_id:
                    continue
                if not any(kassa._cst_is_money_line(line) for line in move.line_ids):
                    continue
                if Day.search_count([("kassa_id", "=", kassa.id), ("date", "=", move.date),
                                     ("state", "=", "confirmed")]):
                    raise UserError(_(
                        "The cash day of %(kassa)s for %(date)s is confirmed and locked. "
                        "Use another date.", kassa=kassa.name, date=move.date))

    def _post(self, soft=True):
        self._cst_check_kassa_day_lock()
        return super()._post(soft=soft)

    def button_draft(self):
        self._cst_check_kassa_day_lock()
        return super().button_draft()
