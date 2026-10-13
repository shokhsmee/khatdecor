from odoo import api, fields, models


class KassaDayClose(models.TransientModel):
    _name = "cst.kassa.day.close"
    _description = "Close Cash Day"

    day_id = fields.Many2one("cst.kassa.day", required=True, readonly=True)
    currency_id = fields.Many2one(related="day_id.currency_id")
    opening_balance = fields.Monetary(related="day_id.opening_balance")
    total_in = fields.Monetary(related="day_id.total_in")
    total_out = fields.Monetary(related="day_id.total_out")
    expected_balance = fields.Monetary(related="day_id.expected_balance")
    counted_balance = fields.Monetary(string="Counted cash", required=True,
                                      help="Count the money in the till and enter the total.")
    difference = fields.Monetary(compute="_compute_difference")
    note = fields.Text(string="Note")

    @api.depends("counted_balance", "expected_balance")
    def _compute_difference(self):
        for wiz in self:
            wiz.difference = wiz.counted_balance - wiz.expected_balance

    def action_close(self):
        self.ensure_one()
        self.day_id._cst_do_close(self.counted_balance, self.note)
        return {"type": "ir.actions.act_window_close"}
