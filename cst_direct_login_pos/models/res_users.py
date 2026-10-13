# -*- coding: utf-8 -*-

from odoo import api, fields, models


class SblResUsers(models.Model):
    _inherit = 'res.users'

    allow_direct_login = fields.Boolean('Allow Direct Login')
    pos_config_id = fields.Many2one('pos.config', string='PoS Configuration')

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields = super()._load_pos_data_fields(config_id)
        fields += ['pos_config_id']
        return fields
