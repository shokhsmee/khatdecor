from odoo import api, models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    def _visible_menu_ids(self, debug=False):
        """A role with a «shown menus» list sees only those menus, what lies
        under them and the parents leading to them -- every other app is
        hidden, while the role's groups stay as they are."""
        visible = super()._visible_menu_ids(debug=debug)
        shown = self.env.user.access_role_id.role_management_id.cst_shown_menu_ids
        if not shown:
            return visible
        keep = set()
        for menu in shown.sudo():
            keep.update(int(i) for i in menu.parent_path.strip("/").split("/"))
        roots = shown.ids
        for menu in self.sudo().browse(visible):
            path = [int(i) for i in menu.parent_path.strip("/").split("/")]
            if any(root in path for root in roots):
                keep.add(menu.id)
        return frozenset(visible) & keep

    @api.model
    def load_menus(self, debug):
        """Cache the menu tree per user again.

        Odoo caches ``load_menus`` on ``(uid, debug, lang)``. The Access Roles
        app re-declares it with a key of ``(group set, debug)``, so two users
        who hold the same groups but different roles share one menu tree: the
        first one to warm the cache decides which menus the other sees, and a
        menu hidden for one role shows up for the other. Skipping that layer
        puts the per-user key back; the role-aware filtering itself lives in
        ``_visible_menu_ids`` and still runs.
        """
        parent = super().load_menus
        uncached = getattr(parent.__func__, "__wrapped__", None)
        if uncached is None:
            # the app dropped its cache — nothing left to work around
            return parent(debug)
        return uncached(self, debug)
