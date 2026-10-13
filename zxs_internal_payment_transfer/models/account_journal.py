# -*- coding: utf-8 -*-
# Copyright (C) 2026 Zarixsol
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    def create_internal_transfer_payment(self):
        self.ensure_one()
        return self.open_payments_action('transfer', mode='form')
