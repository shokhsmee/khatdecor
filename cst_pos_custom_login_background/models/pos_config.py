# -*- coding: utf-8 -*-

from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    login_screen_background = fields.Binary("Login Screen Background")


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_login_screen_background = fields.Binary(related='pos_config_id.login_screen_background', readonly=False,
                                                string="Login Screen Background Image")
