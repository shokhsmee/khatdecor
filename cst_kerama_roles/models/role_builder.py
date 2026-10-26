from collections import defaultdict

from odoo import api, models, tools
from odoo.exceptions import AccessError, UserError
from odoo.fields import Command
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

# The role builder speaks about apps and levels, never about groups. Every
# privilege (Odoo 19's «app permission») is placed in a section and each of its
# levels gets one plain sentence saying what a person with it can do. A
# privilege missing from this list still shows up, under «Other», with Odoo's
# own names - so a module installed later is never invisible here.
SECTIONS = [
    ("sales", _lt("Sales and customers")),
    ("stock", _lt("Warehouse and production")),
    ("money", _lt("Money")),
    ("people", _lt("Staff")),
    ("other", _lt("Other")),
]

PRIVILEGES = {
    "sales_team.res_groups_privilege_sales": ("sales", {
        "sales_team.group_sale_salesman": _lt("Creates quotations and orders and sees only their own."),
        "sales_team.group_sale_salesman_all_leads": _lt("Sees and edits the orders of every salesperson."),
        "sales_team.group_sale_manager": _lt("Everything in Sales, including prices, teams and settings."),
    }),
    "base.res_groups_privilege_contact": ("sales", {
        "base.group_partner_manager": _lt("Creates and edits customers and suppliers."),
    }),
    "product.res_groups_privilege_product": ("sales", {
        "product.group_product_manager": _lt("Creates and edits products and their prices."),
    }),
    "project.res_groups_privilege_project": ("sales", {
        "project.group_project_user": _lt("Works on projects and tasks."),
        "project.group_project_manager": _lt("Creates projects and manages their settings."),
    }),
    "stock.res_groups_privilege_inventory": ("stock", {
        "stock.group_stock_user": _lt("Receives, moves and ships goods, sees stock on hand."),
        "stock.group_stock_manager": _lt("The whole warehouse: adjustments, warehouses, routes, settings."),
    }),
    "cst_kerama_wh_control.privilege_khatdecor_warehouse": ("stock", {
        "cst_kerama_wh_control.group_wh_supervisor": _lt("May validate receipts without a photo and transfers on the receiver's behalf."),
    }),
    "cst_kerama_dispatch.privilege_dispatch": ("stock", {
        "cst_kerama_dispatch.group_dispatch_warehouse": _lt("Prepares the goods of an order in the warehouse."),
        "cst_kerama_dispatch.group_dispatch_gate": _lt("Checks the goods leaving at the gate."),
        "cst_kerama_dispatch.group_dispatch_transfer": _lt("Only internal transfers between warehouses."),
        "cst_kerama_dispatch.group_dispatch_manager": _lt("Warehouse, gate and internal transfers together."),
    }),
    "purchase.res_groups_privilege_purchase": ("stock", {
        "purchase.group_purchase_user": _lt("Creates purchase orders and receives the goods."),
        "purchase.group_purchase_manager": _lt("Also approves purchases and manages the settings."),
    }),
    "mrp.res_groups_privilege_manufacturing": ("stock", {
        "mrp.group_mrp_user": _lt("Works with manufacturing orders."),
        "mrp.group_mrp_manager": _lt("Also bills of materials (texkarta), work centres and settings."),
    }),
    "cst_kerama_shift.privilege_shift": ("stock", {
        "cst_kerama_shift.group_shift_manager": _lt("Runs the shifts of their own department."),
        "cst_kerama_shift.group_shift_admin": _lt("Every department, shift settings and KPI."),
        "cst_kerama_shift.group_doc_correction": _lt("Also corrects shifts and transfers that are already finished."),
    }),
    "quality.res_groups_privilege_quality": ("stock", {
        "quality.group_quality_user": _lt("Records quality checks."),
        "quality.group_quality_manager": _lt("Also sets up quality control points."),
    }),
    "cst_kerama_no_negative.privilege_khatdecor_controls": ("stock", {
        "cst_kerama_no_negative.group_allow_negative_stock": _lt("May take a warehouse below zero."),
        "cst_kerama_no_negative.group_allow_negative_cash": _lt("May take a cash desk below zero."),
    }),
    "account.res_groups_privilege_accounting": ("money", {
        "account.group_account_readonly": _lt("Only looks at invoices, payments and reports."),
        "account.group_account_invoice": _lt("Creates invoices and bills and registers payments."),
        "account.group_account_basic": _lt("Also works with bank and cash statements."),
        "account.group_account_user": _lt("Bookkeeper: journal entries, reconciliation, all reports."),
        "account.group_account_manager": _lt("Everything in accounting, including settings and closing."),
    }),
    "account.res_group_privilege_accounting_bank": ("money", {
        "account.group_validate_bank_account": _lt("Confirms the bank account numbers of partners."),
    }),
    "cst_kerama_kassa.privilege_kassa": ("money", {
        "cst_kerama_kassa.group_kassa_user": _lt("Opens and closes the cash day, receives and pays money."),
        "cst_kerama_kassa.group_kassa_manager": _lt("Also confirms and reopens cash days, manages cash desks."),
    }),
    "cst_kerama_payroll.privilege_khatdecor_payroll": ("money", {
        "cst_kerama_payroll.group_payroll_user": _lt("Prepares the payroll."),
        "cst_kerama_payroll.group_payroll_manager": _lt("Also approves and pays the payroll, sets KPI rates."),
    }),
    "hr.res_groups_privilege_employees": ("people", {
        "hr.group_hr_user": _lt("Manages the cards of all employees."),
        "hr.group_hr_manager": _lt("Also departments, contracts and HR settings."),
    }),
    "hr_attendance.res_groups_privilege_attendances": ("people", {
        "hr_attendance.group_hr_attendance_user": _lt("Sees and corrects everybody's attendance."),
        "hr_attendance.group_hr_attendance_manager": _lt("Also the attendance settings and devices."),
    }),
    "hr_expense.res_groups_privilege_expenses": ("people", {
        "hr_expense.group_hr_expense_team_approver": _lt("Approves the expenses of their own team."),
        "hr_expense.group_hr_expense_user": _lt("Approves everybody's expenses."),
        "hr_expense.group_hr_expense_manager": _lt("Also expense categories and settings."),
    }),
    "base.res_groups_privilege_export": ("other", {
        "base.group_allow_export": _lt("May export lists to Excel."),
    }),
    "access_roles.access_roles_privilege_category": ("other", {
        "access_roles.access_role_group_user": _lt("Sees the roles."),
        "access_roles.access_role_group_administrator": _lt("Creates and edits roles (this screen)."),
    }),
    "spreadsheet_dashboard.res_groups_privilege_dashboard": ("other", {
        "spreadsheet_dashboard.group_dashboard_manager": _lt("Creates and edits dashboards."),
    }),
}

# Groups that do not belong to any app but matter when setting up a role. The
# rest of the app-less groups are switches of features and live in a folded
# «Technical options» list.
KEY_EXTRA_GROUPS = {
    "base.group_multi_company": ("normal", _lt("May switch between the companies (branches).")),
    "base.group_erp_manager": ("danger", _lt("Manages users and their access rights.")),
    "base.group_system": ("danger", _lt("Full administrator: every setting of the system.")),
}
NEVER_SHOWN_GROUPS = (
    "base.group_user", "base.group_portal", "base.group_public", "base.group_no_one",
)

# Menus users never need to be offered as an app of a role.
HIDDEN_APPS = ("base.menu_tests", "base.menu_management", "utm.menu_link_tracker_root")

MODEL_BY_ACTION = {
    "ir.actions.act_window": "res_model",
    "ir.actions.report": "model",
    "ir.actions.server": "model_name",
}


class CstRoleBuilder(models.AbstractModel):
    """Backend of the «Role builder» screen.

    A role is two records in the Access Roles app: ``access.role`` holds the
    groups (what a person may do) and ``role.management`` holds the menus and
    restrictions (what a person sees). The builder edits both as one thing and
    keeps the users of the role in step.
    """

    _name = "cst.role.builder"
    _description = "Role builder"

    # ------------------------------------------------------------ access
    def _check_builder_access(self):
        user = self.env.user
        if not (user.has_group("access_roles.access_role_group_administrator")
                or user.has_group("base.group_erp_manager")):
            raise AccessError(self.env._("Only the administrator of the roles may change them."))

    # ------------------------------------------------------------ catalog
    @api.model
    def _xmlid_map(self, model, ids):
        rows = self.env["ir.model.data"].sudo().search_read(
            [("model", "=", model), ("res_id", "in", list(ids))], ["module", "name", "res_id"])
        result = {}
        for row in rows:
            result.setdefault(row["res_id"], f"{row['module']}.{row['name']}")
        return result

    @api.model
    def _catalog(self):
        """Apps, permissions and their levels, in the user's language."""
        Groups = self.env["res.groups"].sudo()
        hierarchy = Groups._get_view_group_hierarchy()
        groups = hierarchy["groups"]
        privilege_xmlids = self._xmlid_map("res.groups.privilege", hierarchy["privileges"].keys())
        help_by_group = {}
        section_by_privilege = {}
        for privilege_xmlid, (section, levels) in PRIVILEGES.items():
            section_by_privilege[privilege_xmlid] = section
            for group_xmlid, text in levels.items():
                group = self.env.ref(group_xmlid, raise_if_not_found=False)
                if group:
                    help_by_group[group.id] = str(text)
        order = {key: index for index, key in enumerate(PRIVILEGES)}

        privileges = []
        for privilege in hierarchy["privileges"].values():
            level_ids = [gid for gid in privilege["group_ids"] if gid in groups]
            if not level_ids:
                continue
            xmlid = privilege_xmlids.get(privilege["id"], "")
            in_privilege = set(level_ids)
            # flags that do not build on each other are ticked one by one,
            # real levels are picked as one of a row
            independent = len(level_ids) > 1 and not any(
                (set(groups[gid]["all_implied_ids"]) - {gid}) & in_privilege for gid in level_ids)
            privileges.append({
                "id": privilege["id"],
                "xmlid": xmlid,
                "name": privilege["name"],
                "section": section_by_privilege.get(xmlid, "other"),
                "sequence": order.get(xmlid, 1000),
                "multi": independent,
                "levels": [{
                    "id": gid,
                    "name": groups[gid]["name"],
                    "help": help_by_group.get(gid) or groups[gid]["comment"] or "",
                } for gid in level_ids],
            })
        privileges.sort(key=lambda p: (p["sequence"], p["name"]))

        group_user = self.env.ref("base.group_user")
        always = set(group_user.all_implied_ids.ids)
        never = {self.env.ref(x).id for x in NEVER_SHOWN_GROUPS if self.env.ref(x, raise_if_not_found=False)}
        key_extra, technical = [], []
        key_ids = {}
        for xmlid, (tone, text) in KEY_EXTRA_GROUPS.items():
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                key_ids[group.id] = (tone, str(text))
        for gid, group in groups.items():
            if group["privilege_id"] or gid in never:
                continue
            if gid in key_ids:
                tone, text = key_ids[gid]
                key_extra.append({"id": gid, "name": group["name"], "help": text, "tone": tone})
            elif gid not in always:
                technical.append({"id": gid, "name": group["name"], "help": group["comment"] or ""})
        key_extra.sort(key=lambda g: list(key_ids).index(g["id"]))
        technical.sort(key=lambda g: g["name"])

        return {
            "sections": [{"key": key, "name": str(name)} for key, name in SECTIONS],
            "privileges": privileges,
            "key_extra": key_extra,
            "technical": technical,
            "implied": {gid: g["all_implied_ids"] for gid, g in groups.items()},
            "group_names": {gid: g["name"] for gid, g in groups.items()},
            "group_user_id": group_user.id,
            "apps": self._apps(),
        }

    @api.model
    def _apps(self):
        """Every app of the home screen with its first two menu levels."""
        Menu = self.env["ir.ui.menu"].sudo()
        hidden = {self.env.ref(x).id for x in HIDDEN_APPS if self.env.ref(x, raise_if_not_found=False)}

        def node(menu, depth):
            children = []
            if depth < 2:
                children = [node(child, depth + 1) for child in menu.child_id.sorted("sequence")]
            return {"id": menu.id, "name": menu.name, "children": children}

        apps = []
        for menu in Menu.search([("parent_id", "=", False)], order="sequence, id"):
            if menu.id in hidden:
                continue
            icon = False
            if menu.web_icon and "," in menu.web_icon:
                module, path = menu.web_icon.split(",", 1)
                icon = f"/{module}/{path}"
            apps.append({**node(menu, 0), "icon": icon})
        return apps

    # ------------------------------------------------------------ simulation
    @api.model
    @tools.ormcache()
    def _menu_index(self):
        """Every active menu as (parent, groups, model of its action) and, per
        model, the groups that may read it. Cleared with the registry cache,
        which Odoo does whenever a menu or an access right changes."""
        menus = self.env["ir.ui.menu"].sudo().with_context({}).search_fetch(
            [], ["parent_id", "action", "group_ids"], order="id")
        actions = defaultdict(list)
        for action in menus.mapped("action"):
            if action:
                actions[action._name].append(action.id)
        model_of = {}
        for action_model, ids in actions.items():
            records = self.env[action_model].sudo().with_context(active_test=False).browse(ids).exists()
            field = MODEL_BY_ACTION.get(action_model)
            for record in records:
                model_of[(action_model, record.id)] = (record[field] or "") if field else ""
        index = {}
        for menu in menus:
            action = menu.action
            target = model_of.get((action._name, action.id)) if action else None
            index[menu.id] = (menu.parent_id.id, frozenset(menu.group_ids.ids), target)
        model_names = {m["id"]: m["model"] for m in self.env["ir.model"].sudo().search_read([], ["model"])}
        readers = defaultdict(set)
        for row in self.env["ir.model.access"].sudo().search_read(
                [("perm_read", "=", True), ("active", "=", True)], ["model_id", "group_id"]):
            model = model_names.get(row["model_id"][0])
            readers[model].add(row["group_id"][0] if row["group_id"] else 0)
        return index, dict(readers)

    @api.model
    def _visible_menu_ids(self, group_ids):
        """The menus a user holding exactly ``group_ids`` would see, before
        any hiding by the role - the same rules as ``ir.ui.menu``: the menu's
        groups, and for a menu with an action, read access to its model."""
        all_ids = set(self.env["res.groups"].sudo().browse(group_ids).exists().all_implied_ids.ids)
        all_ids.discard(self.env.ref("base.group_no_one").id)
        all_ids.add(0)
        index, readers = self._menu_index()
        allowed = {mid for mid, (_p, groups, _t) in index.items() if not groups or groups & all_ids}
        visible = set()
        for menu_id in allowed:
            parent_id, _groups, target = index[menu_id]
            if target is None:
                continue
            if target and not readers.get(target, set()) & all_ids:
                continue
            while menu_id and menu_id not in visible and menu_id in allowed:
                visible.add(menu_id)
                menu_id = index[menu_id][0]
        return visible

    @api.model
    def _apply_role_menus(self, visible, mode, shown_ids, hidden_ids):
        """Narrow ``visible`` the way the role's Role Management record does."""
        visible = set(visible) - set(hidden_ids)
        if mode != "only":
            return visible
        if not shown_ids:
            return set()
        shown = self.env["ir.ui.menu"].sudo().browse(shown_ids).exists()
        keep = set()
        for menu in shown:
            keep.update(int(i) for i in menu.parent_path.strip("/").split("/"))
        for menu in self.env["ir.ui.menu"].sudo().browse(list(visible)):
            path = [int(i) for i in menu.parent_path.strip("/").split("/")]
            if any(root in path for root in shown.ids):
                keep.add(menu.id)
        return visible & keep

    @api.model
    def preview(self, group_ids, mode, shown_ids, hidden_ids):
        """What the home screen of a user with this role would look like, and
        for each app the role offers but cannot open, the permission that
        would open it."""
        self._check_builder_access()
        visible = self._visible_menu_ids(group_ids)
        final = self._apply_role_menus(visible, mode, shown_ids, hidden_ids)
        apps = self._apps()
        app_ids = [app["id"] for app in apps]
        offered = set(app_ids) if mode != "only" else {
            self._root_of(menu_id) for menu_id in shown_ids}
        offered -= set(hidden_ids)
        missing = {}
        for app_id in app_ids:
            if app_id in offered and app_id not in visible:
                missing[app_id] = self._suggest_group(app_id, group_ids)
        if mode == "only":
            # sections ticked one by one, whose app does open
            for menu_id in shown_ids:
                root = self._root_of(menu_id)
                if menu_id != root and root not in missing and menu_id not in visible:
                    missing[menu_id] = self._suggest_group(menu_id, group_ids)
        return {
            "visible_app_ids": [app_id for app_id in app_ids if app_id in final],
            "visible_menu_ids": sorted(final),
            "group_menu_ids": sorted(visible),
            "missing": missing,
        }

    @api.model
    def _root_of(self, menu_id):
        menu = self.env["ir.ui.menu"].sudo().browse(menu_id)
        return int(menu.parent_path.split("/")[0]) if menu.exists() else False

    @api.model
    def _suggest_group(self, menu_id, group_ids):
        """The lowest level of a permission that makes ``menu_id`` appear, the
        permissions used by its own menus tried first. Administrator rights
        are never offered as a fix: when only they open the menu, the answer
        says so instead."""
        Menu = self.env["ir.ui.menu"].sudo()
        hierarchy = self.env["res.groups"].sudo()._get_view_group_hierarchy()
        used = set(Menu.search([("id", "child_of", menu_id)]).group_ids.ids)
        admin_ids = [self.env.ref(x).id for x in ("base.group_erp_manager", "base.group_system")]
        candidates = []
        for privilege in hierarchy["privileges"].values():
            lowest = privilege["group_ids"][0] if privilege["group_ids"] else False
            if not lowest or lowest in group_ids or lowest in admin_ids:
                continue
            first = bool(used & set(privilege["group_ids"]))
            candidates.append((0 if first else 1, lowest, privilege["name"]))
        for _rank, gid, privilege_name in sorted(candidates, key=lambda c: c[0]):
            if menu_id in self._visible_menu_ids(list(group_ids) + [gid]):
                group = self.env["res.groups"].sudo().browse(gid)
                return {"group_id": gid, "privilege": privilege_name, "level": group.name}
        if menu_id in self._visible_menu_ids(list(group_ids) + admin_ids):
            return {"admin_only": True}
        return False

    # ------------------------------------------------------------ read
    @api.model
    def load(self):
        self._check_builder_access()
        roles = self.env["access.role"].sudo().search([], order="id")
        return {
            "catalog": self._catalog(),
            "roles": [self._role_data(role) for role in roles],
            "my_role_id": self.env.user.access_role_id.id,
        }

    @api.model
    def _role_users(self, role):
        return self.env["res.users"].sudo().search(
            [("access_role_id", "=", role.id), ("share", "=", False)], order="name")

    @api.model
    def _role_data(self, role):
        rm = role.role_management_id
        users = self._role_users(role)
        advanced = bool(rm and (rm.field_access_ids or rm.model_access_ids or rm.button_access_ids
                                or rm.filter_access_ids or rm.domain_ids))
        visible = self._apply_role_menus(
            self._visible_menu_ids(role.groups_ids.ids),
            "only" if rm.cst_shown_menu_ids else "all",
            rm.cst_shown_menu_ids.ids, rm.menu_ids.ids)
        return {
            "id": role.id,
            "name": role.name,
            "description": role.cst_description or "",
            "group_ids": role.groups_ids.ids,
            "users": [{"id": u.id, "name": u.name, "login": u.login} for u in users],
            "mode": "only" if rm.cst_shown_menu_ids else "all",
            "shown_menu_ids": rm.cst_shown_menu_ids.ids,
            "hidden_menu_ids": rm.menu_ids.ids,
            "is_readonly": rm.is_readonly,
            "is_chatter": rm.is_chatter,
            "is_debug": rm.is_debug,
            "rm_id": rm.id,
            "advanced": advanced,
            "visible_app_ids": [app["id"] for app in self._apps() if app["id"] in visible],
        }

    @api.model
    def search_users(self, term, limit=8):
        self._check_builder_access()
        domain = [("share", "=", False)]
        if term:
            domain += ["|", ("name", "ilike", term), ("login", "ilike", term)]
        users = self.env["res.users"].sudo().search(domain, limit=limit, order="name")
        return [{"id": u.id, "name": u.name, "login": u.login,
                 "role": u.access_role_id.name or ""} for u in users]

    # ------------------------------------------------------------ write
    @api.model
    def save_role(self, role_id, values):
        """Create or update a role from the builder. ``values`` holds name,
        description, group_ids, user_ids, mode, shown_menu_ids,
        hidden_menu_ids, is_readonly, is_chatter, is_debug."""
        self._check_builder_access()
        _ = self.env._
        name = (values.get("name") or "").strip()
        if not name:
            raise UserError(_("Give the role a name."))
        Role = self.env["access.role"]
        group_ids = set(values.get("group_ids") or [])
        group_ids.add(self.env.ref("base.group_user").id)
        user_ids = set(values.get("user_ids") or [])
        me = self.env.user
        role = Role.browse(role_id) if role_id else Role
        if role and me.access_role_id == role:
            self._check_not_locked_out(group_ids, me.id in user_ids, values)

        role_vals = {
            "name": name,
            "cst_description": values.get("description") or False,
            "groups_ids": [Command.set(list(group_ids))],
        }
        if role:
            role.write(role_vals)
        else:
            role = Role.create(role_vals)

        # users: those leaving the role are left with no role (Internal User
        # only), those joining get exactly the role's groups
        current = self._role_users(role)
        Users = self.env["res.users"]
        leaving = current - Users.browse(list(user_ids))
        joining = Users.browse(list(user_ids)).exists() - current
        if me in leaving:
            raise UserError(_("You cannot take yourself out of your own role here."))
        if leaving:
            leaving.write({"access_role_id": False})
        if joining:
            joining.write({"access_role_id": role.id})

        self._save_menus(role, values)
        return role.id

    @api.model
    def _check_not_locked_out(self, group_ids, staying, values):
        all_ids = set(self.env["res.groups"].sudo().browse(list(group_ids)).all_implied_ids.ids)
        keys = {self.env.ref("access_roles.access_role_group_administrator").id,
                self.env.ref("base.group_erp_manager").id}
        if not staying or not all_ids & keys:
            raise UserError(self.env._(
                "This is your own role. Saving it like this would take away your right to "
                "manage roles - keep «Access Role: Administrator» or «Access Rights» on it."))
        root = self.env.ref("access_roles.access_role_menu_root")
        app = set(self.env["ir.ui.menu"].sudo().search([("id", "child_of", root.id)]).ids)
        hidden = set(values.get("hidden_menu_ids") or [])
        shown = set(values.get("shown_menu_ids") or [])
        if root.id in hidden or (values.get("mode") == "only" and not shown & app):
            raise UserError(self.env._(
                "This is your own role. Keep the «%(app)s» app switched on in part 2, "
                "otherwise you would no longer reach this screen.", app=root.name))

    @api.model
    def _save_menus(self, role, values):
        RoleManagement = self.env["role.management"]
        rm = role.role_management_id
        if rm and len(rm.role_ids) > 1:
            # another role shares these settings - give this one its own copy
            shared = rm
            rm = shared.copy({"name": role.name, "role_ids": [Command.set([role.id])]})
            shared.role_ids = [Command.unlink(role.id)]
        mode = values.get("mode") or "all"
        rm_vals = {
            "cst_shown_menu_ids": [Command.set(values.get("shown_menu_ids") or [] if mode == "only" else [])],
            "menu_ids": [Command.set(values.get("hidden_menu_ids") or [])],
            "is_readonly": bool(values.get("is_readonly")),
            "is_chatter": bool(values.get("is_chatter")),
            "is_debug": bool(values.get("is_debug")),
        }
        if rm:
            rm.write(rm_vals)
        else:
            rm = RoleManagement.create({**rm_vals, "name": role.name,
                                        "role_ids": [Command.set([role.id])]})
        if role.role_management_id != rm:
            role.role_management_id = rm

    @api.model
    def copy_role(self, role_id):
        self._check_builder_access()
        role = self.env["access.role"].browse(role_id)
        data = self._role_data(role.sudo())
        new_id = self.save_role(False, {
            **data,
            "name": self.env._("%(name)s (copy)", name=role.name),
            "user_ids": [],
        })
        return new_id

    @api.model
    def delete_role(self, role_id):
        self._check_builder_access()
        role = self.env["access.role"].browse(role_id)
        if self._role_users(role):
            raise UserError(self.env._("Move the users of this role to another role first."))
        rm = role.role_management_id
        role.unlink()
        if rm and not rm.role_ids:
            rm.unlink()
        return True
