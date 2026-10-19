from odoo import api, models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    def _visible_menu_ids(self, debug=False):
        """«Ichki o'tkazmalar» as its own menu only for people whose Jo'natish
        is transfers alone; warehouse and gate people keep the Skaner home,
        where transfers are a tile, exactly as before."""
        visible = super()._visible_menu_ids(debug=debug)
        user = self.env.user
        if user.has_group("cst_kerama_dispatch.group_dispatch_warehouse") or \
                user.has_group("cst_kerama_dispatch.group_dispatch_gate"):
            menu = self.env.ref("cst_kerama_dispatch.menu_dispatch_transfers", raise_if_not_found=False)
            if menu and menu.id in visible:
                visible = frozenset(visible) - {menu.id}
        return visible
