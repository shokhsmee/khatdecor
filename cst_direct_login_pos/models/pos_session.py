# -*- coding: utf-8 -*-

from odoo import fields, models
from odoo.http import request


class PosSession(models.Model):
    _inherit = 'pos.session'

    def close_session_from_ui(self, bank_payment_method_diff_pairs=None):
        res = super().close_session_from_ui(bank_payment_method_diff_pairs=bank_payment_method_diff_pairs)
        if self.user_id.allow_direct_login:
            request.session.logout(keep_db=True)
        return res
