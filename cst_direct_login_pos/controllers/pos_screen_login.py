from odoo import http
from odoo.http import request
import werkzeug
from odoo.addons.web.controllers import home


class PoSScreen(home.Home):

    @http.route('/web/login', type='http', auth="public", website=True, sitemap=False)
    def web_login(self, redirect=None, **kw):
        res = super().web_login(redirect=redirect, **kw)
        pos_config = request.env.user.pos_config_id
        if request.env.user.allow_direct_login and pos_config:
            if not pos_config.current_session_id:
                request.env['pos.session'].sudo().create({
                    'user_id': request.env.uid,
                    'config_id': pos_config.id
                })
            return werkzeug.utils.redirect('/pos/ui?config_id=%s' % pos_config.id)
        return res


