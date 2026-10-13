from odoo import api, fields, models
from odoo.fields import Command


class AccessRole(models.Model):
    """Fixes on top of the Access Roles app that the Khatdecor roles rely on."""

    _inherit = "access.role"

    def _update_users_groups(self):
        """Push the role's groups onto its users.

        Two things are fixed here. The app writes ``groups_ids``, a field Odoo
        19 renamed to ``group_ids`` on ``res.users``, so the original raised a
        ValueError as soon as a role that already had users got its group list
        edited. And it looked only at ``user_ids``, a list the app fills from
        the Users form's onchange alone — a role assigned by import, by script
        or from the role's own form left that list empty and the new groups
        never reached anybody. The users pointing at the role are the truth.
        """
        Users = self.env["res.users"]
        for role in self:
            users = role.user_ids | Users.sudo().search([("access_role_id", "=", role.id)])
            if users:
                users.browse(users.ids).write({
                    "group_ids": [Command.set(role.groups_ids.ids)]
                })

    @api.model_create_multi
    def create(self, vals_list):
        roles = super().create(vals_list)
        self.env.registry.clear_cache()
        return roles

    def write(self, values):
        result = super().write(values)
        # a role that moves to another Role Management record changes which
        # menus its users may see
        self.env.registry.clear_cache()
        return result

    def unlink(self):
        result = super().unlink()
        self.env.registry.clear_cache()
        return result


class RoleManagement(models.Model):
    """Make a change to the hidden-menu list visible without a restart."""

    _inherit = "role.management"

    cst_shown_menu_ids = fields.Many2many(
        "ir.ui.menu", "cst_role_management_shown_menu_rel", "role_management_id", "menu_id",
        string="Faqat shu menyular ko'rinsin",
        help="Bo'sh bo'lsa — hech narsa o'zgarmaydi. To'ldirilsa, rol egasi faqat shu menyularni, "
             "ularning ichidagilarni va ularga olib boradigan yuqori menyularni ko'radi; qolgan "
             "ilovalar yashiriladi. Huquqlar (guruhlar) tegilmaydi.")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        result = super().write(vals)
        self.env.registry.clear_cache()
        return result

    def unlink(self):
        result = super().unlink()
        self.env.registry.clear_cache()
        return result


class ResUsers(models.Model):
    """Keep the role's user list in step with the users' own role field."""

    _inherit = "res.users"

    def write(self, vals):
        result = super().write(vals)
        if "access_role_id" in vals:
            Role = self.env["access.role"].sudo()
            new_role = Role.browse(vals["access_role_id"]) if vals["access_role_id"] else Role
            for role in Role.search([("user_ids", "in", self.ids)]) - new_role:
                role.write({"user_ids": [Command.unlink(uid) for uid in self.ids]})
            if new_role:
                new_role.write({"user_ids": [Command.link(uid) for uid in self.ids]})
        return result
