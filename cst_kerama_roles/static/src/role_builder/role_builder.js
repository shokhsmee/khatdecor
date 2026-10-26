import { Component, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

const MODEL = "cst.role.builder";

/**
 * Role builder: the roles of the company as cards (or a matrix), and one
 * screen per role in four numbered parts - main, apps, permissions,
 * restrictions - with a live preview of the home screen the role gives.
 * The person setting it up never sees a «group»: apps are tiles, permissions
 * are levels with a sentence each.
 */
export class RoleBuilder extends Component {
    static template = "cst_kerama_roles.RoleBuilder";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.action = useService("action");
        this.root = useRef("root");
        this.state = useState({
            loaded: false,
            screen: "list",
            view: "cards",
            showHelp: false,
            roles: [],
            draft: null,
            dirty: false,
            busy: false,
            preview: { visible_app_ids: [], visible_menu_ids: [], group_menu_ids: [], missing: {} },
            userTerm: "",
            userResults: [],
            openApp: false,
            showTechnical: false,
            appFilter: "",
        });
        this.catalog = null;
        this.previewTimer = null;
        this.userTimer = null;
        onWillStart(async () => {
            await this.reload();
            const roleId = this.props.action?.params?.role_id;
            if (roleId && this.state.roles.find((r) => r.id === roleId)) {
                this.openRole(roleId);
            }
        });
        onWillUnmount(() => {
            clearTimeout(this.previewTimer);
            clearTimeout(this.userTimer);
        });
    }

    // ------------------------------------------------------------ data
    async reload() {
        const data = await this.orm.call(MODEL, "load", []);
        this.catalog = data.catalog;
        this.myRoleId = data.my_role_id;
        this.appById = {};
        this.menuInfo = {};
        for (const app of this.catalog.apps) {
            this.appById[app.id] = app;
            const walk = (node, parentId, appId, depth) => {
                this.menuInfo[node.id] = { node, parentId, appId, depth };
                for (const child of node.children) {
                    walk(child, node.id, appId, depth + 1);
                }
            };
            walk(app, false, app.id, 0);
        }
        this.levelRank = {};
        for (const privilege of this.catalog.privileges) {
            privilege.levels.forEach((level, index) => {
                this.levelRank[level.id] = { privilege, index };
            });
        }
        this.state.roles = data.roles;
        this.state.loaded = true;
    }

    get sections() {
        return this.catalog.sections
            .map((section) => ({
                ...section,
                privileges: this.catalog.privileges.filter((p) => p.section === section.key),
            }))
            .filter((section) => section.privileges.length);
    }

    // ------------------------------------------------------------ list screen
    appsOfRole(role) {
        return role.visible_app_ids.map((id) => this.appById[id]).filter(Boolean);
    }

    initials(name) {
        return (name || "?")
            .split(/\s+/)
            .slice(0, 2)
            .map((w) => w[0])
            .join("")
            .toUpperCase();
    }

    get matrixPrivileges() {
        // only the permissions some role actually uses, in section order
        const used = new Set(this.state.roles.flatMap((r) => r.group_ids));
        const result = [];
        for (const section of this.sections) {
            for (const privilege of section.privileges) {
                if (privilege.levels.some((l) => used.has(l.id))) {
                    result.push(privilege);
                }
            }
        }
        return result;
    }

    matrixCell(role, privilege) {
        const implied = this.impliedOf(role.group_ids);
        const index = this.effectiveIndex(privilege, implied);
        if (index < 0) {
            return { label: "—", tone: 0, title: _t("No access") };
        }
        const level = privilege.levels[index];
        const tone = privilege.multi ? 2 : Math.max(1, Math.round(((index + 1) / privilege.levels.length) * 3));
        const names = privilege.multi
            ? privilege.levels.filter((l) => implied.has(l.id)).map((l) => l.name).join(", ")
            : level.name;
        return { label: names, tone, title: `${privilege.name}: ${names}` };
    }

    newRole() {
        this.openDraft({
            id: false,
            name: "",
            description: "",
            group_ids: [this.catalog.group_user_id],
            users: [],
            mode: "only",
            shown_menu_ids: [],
            hidden_menu_ids: [],
            is_readonly: false,
            is_chatter: false,
            is_debug: false,
            advanced: false,
            rm_id: false,
        });
        this.state.dirty = true;
    }

    openRole(roleId) {
        const role = this.state.roles.find((r) => r.id === roleId);
        this.openDraft(JSON.parse(JSON.stringify(role)));
    }

    openDraft(draft) {
        this.state.draft = draft;
        this.state.dirty = false;
        this.state.screen = "edit";
        this.state.openApp = false;
        this.state.userTerm = "";
        this.state.userResults = [];
        this.refreshPreview(true);
        this.scrollTop();
    }

    scrollTop() {
        const el = this.root.el?.closest(".o_action") || this.root.el;
        if (el) {
            el.scrollTop = 0;
        }
    }

    async copyRole(role) {
        const newId = await this.orm.call(MODEL, "copy_role", [role.id]);
        await this.reload();
        this.notification.add(_t("A copy of «%s» was made. Rename it and adjust it.", role.name), {
            type: "success",
        });
        this.openRole(newId);
    }

    deleteRole(role) {
        if (role.users.length) {
            this.notification.add(_t("Move the users of this role to another role first."), {
                type: "warning",
            });
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete role"),
            body: _t("Delete the role «%s»? This cannot be undone.", role.name),
            confirmLabel: _t("Delete"),
            confirm: async () => {
                await this.orm.call(MODEL, "delete_role", [role.id]);
                await this.reload();
                this.state.screen = "list";
                this.notification.add(_t("Role deleted."), { type: "success" });
            },
            cancel: () => {},
        });
    }

    // ------------------------------------------------------------ editor
    get d() {
        return this.state.draft;
    }

    touch() {
        this.state.dirty = true;
        this.refreshPreview();
    }

    back() {
        if (!this.state.dirty) {
            this.state.screen = "list";
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: _t("Unsaved changes"),
            body: _t("The changes to this role are not saved. Leave without saving?"),
            confirmLabel: _t("Leave without saving"),
            confirm: () => {
                this.state.dirty = false;
                this.state.screen = "list";
            },
            cancel: () => {},
        });
    }

    discard() {
        if (this.d.id) {
            this.openRole(this.d.id);
        } else {
            this.state.dirty = false;
            this.state.screen = "list";
        }
    }

    async save() {
        if (!this.d.name.trim()) {
            this.notification.add(_t("Give the role a name."), { type: "warning" });
            this.goTo("main");
            return;
        }
        this.state.busy = true;
        try {
            const roleId = await this.orm.call(MODEL, "save_role", [
                this.d.id,
                {
                    name: this.d.name,
                    description: this.d.description,
                    group_ids: this.d.group_ids,
                    user_ids: this.d.users.map((u) => u.id),
                    mode: this.d.mode,
                    shown_menu_ids: this.d.shown_menu_ids,
                    hidden_menu_ids: this.d.hidden_menu_ids,
                    is_readonly: this.d.is_readonly,
                    is_chatter: this.d.is_chatter,
                    is_debug: this.d.is_debug,
                },
            ]);
            await this.reload();
            this.openRole(roleId);
            const count = this.d.users.length;
            this.notification.add(
                count
                    ? _t("Saved. The access of %s user(s) was updated.", count)
                    : _t("Saved."),
                { type: "success" }
            );
        } finally {
            this.state.busy = false;
        }
    }

    goTo(part) {
        const el = this.root.el?.querySelector(`[data-part="${part}"]`);
        if (el) {
            el.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }

    // ---- preview
    refreshPreview(now = false) {
        clearTimeout(this.previewTimer);
        const run = async () => {
            const draft = this.d;
            if (!draft) {
                return;
            }
            const result = await this.orm.call(MODEL, "preview", [
                draft.group_ids,
                draft.mode,
                draft.shown_menu_ids,
                draft.hidden_menu_ids,
            ]);
            if (draft === this.d) {
                this.state.preview = result;
            }
        };
        if (now) {
            run();
        } else {
            this.previewTimer = setTimeout(run, 250);
        }
    }

    get previewApps() {
        return this.state.preview.visible_app_ids.map((id) => this.appById[id]).filter(Boolean);
    }

    get warnings() {
        return Object.entries(this.state.preview.missing).map(([menuId, fix]) => {
            const info = this.menuInfo[menuId];
            const app = info && this.appById[info.appId];
            const label = !info ? "" : info.depth ? `${app.name} ▸ ${info.node.name}` : app.name;
            return { id: Number(menuId), label, fix };
        });
    }

    // ---- users
    onUserInput(ev) {
        this.state.userTerm = ev.target.value;
        clearTimeout(this.userTimer);
        this.userTimer = setTimeout(() => this.searchUsers(), 200);
    }

    async searchUsers() {
        const results = await this.orm.call(MODEL, "search_users", [this.state.userTerm]);
        const taken = new Set(this.d.users.map((u) => u.id));
        this.state.userResults = results.filter((u) => !taken.has(u.id));
    }

    addUser(user) {
        this.d.users.push({ id: user.id, name: user.name, login: user.login, from: user.role });
        this.state.userTerm = "";
        this.state.userResults = [];
        this.touch();
    }

    movesFrom(user) {
        return _t("moves here from «%s»", user.from);
    }

    removeUser(user) {
        this.d.users = this.d.users.filter((u) => u.id !== user.id);
        this.touch();
    }

    // ---- apps
    setMode(mode) {
        if (this.d.mode === mode) {
            return;
        }
        if (mode === "only") {
            // start from what is visible right now
            this.d.shown_menu_ids = [...this.state.preview.visible_app_ids];
            this.d.hidden_menu_ids = [];
        } else {
            this.d.shown_menu_ids = [];
            this.d.hidden_menu_ids = [];
        }
        this.d.mode = mode;
        this.touch();
    }

    ancestors(menuId) {
        const result = [];
        let info = this.menuInfo[menuId];
        while (info && info.parentId) {
            result.push(info.parentId);
            info = this.menuInfo[info.parentId];
        }
        return result;
    }

    isMenuOn(menuId) {
        const chain = [menuId, ...this.ancestors(menuId)];
        if (this.d.mode === "only") {
            return chain.some((id) => this.d.shown_menu_ids.includes(id));
        }
        return !chain.some((id) => this.d.hidden_menu_ids.includes(id));
    }

    appState(app) {
        if (this.d.mode === "only") {
            if (this.d.shown_menu_ids.includes(app.id)) {
                return "on";
            }
            const partial = this.d.shown_menu_ids.some((id) => this.menuInfo[id]?.appId === app.id);
            return partial ? "partial" : "off";
        }
        if (this.d.hidden_menu_ids.includes(app.id)) {
            return "off";
        }
        const partial = this.d.hidden_menu_ids.some((id) => this.menuInfo[id]?.appId === app.id);
        return partial ? "partial" : "on";
    }

    appBlocked(app) {
        return Boolean(this.state.preview.missing[app.id]);
    }

    appVisibleByRights(app) {
        return this.state.preview.group_menu_ids.includes(app.id);
    }

    get filteredApps() {
        const term = this.state.appFilter.trim().toLowerCase();
        return this.catalog.apps.filter((a) => !term || a.name.toLowerCase().includes(term));
    }

    toggleApp(app) {
        const within = (id) => this.menuInfo[id]?.appId === app.id;
        const state = this.appState(app);
        if (this.d.mode === "only") {
            const others = this.d.shown_menu_ids.filter((id) => !within(id));
            this.d.shown_menu_ids = state === "off" ? [...others, app.id] : others;
        } else {
            const others = this.d.hidden_menu_ids.filter((id) => !within(id));
            this.d.hidden_menu_ids = state === "on" ? [...others, app.id] : others;
        }
        this.touch();
    }

    sectionsHint(app) {
        return _t(
            "Tick the sections of «%s» this role should see. Greyed sections need a permission from part 3.",
            app.name
        );
    }

    fixLabel(fix) {
        // «Jo'natish: Jo'natish: ombor menejeri» reads better without the repeat
        const level = fix.level.startsWith(`${fix.privilege}:`)
            ? fix.level.slice(fix.privilege.length + 1).trim()
            : fix.level;
        return _t("Give «%(privilege)s: %(level)s»", { privilege: fix.privilege, level });
    }

    toggleOpenApp(app) {
        this.state.openApp = this.state.openApp === app.id ? false : app.id;
    }

    toggleMenu(menuId) {
        const on = this.isMenuOn(menuId);
        const key = this.d.mode === "only" ? "shown_menu_ids" : "hidden_menu_ids";
        const list = [...this.d[key]];
        // whether the change adds or removes the menu from the list
        const adding = this.d.mode === "only" ? !on : on;
        const descendants = (id) =>
            Object.keys(this.menuInfo)
                .map(Number)
                .filter((mid) => this.ancestors(mid).includes(id));
        if (adding) {
            const inside = new Set(descendants(menuId));
            this.d[key] = [...list.filter((id) => !inside.has(id)), menuId];
        } else if (list.includes(menuId)) {
            this.d[key] = list.filter((id) => id !== menuId);
        } else {
            // an ancestor is in the list: open it up into its children,
            // all of them but the branch that leads to this menu
            const chain = [menuId, ...this.ancestors(menuId)];
            const top = chain.find((id) => list.includes(id));
            let result = list.filter((id) => id !== top);
            let current = top;
            for (const step of chain.slice(0, chain.indexOf(top)).reverse()) {
                const siblings = this.menuInfo[current].node.children.map((c) => c.id);
                result = result.concat(siblings.filter((id) => id !== step));
                current = step;
            }
            this.d[key] = result;
        }
        this.touch();
    }

    menuRights(menuId) {
        return this.state.preview.group_menu_ids.includes(menuId);
    }

    fixApp(appId) {
        const fix = this.state.preview.missing[appId];
        if (!fix || fix.admin_only) {
            return;
        }
        this.addGroup(fix.group_id);
        this.notification.add(
            _t("Permission added: %(privilege)s — %(level)s", {
                privilege: fix.privilege,
                level: fix.level,
            }),
            { type: "info" }
        );
    }

    // ---- permissions
    impliedOf(groupIds) {
        const result = new Set();
        for (const gid of groupIds) {
            for (const implied of this.catalog.implied[gid] || [gid]) {
                result.add(implied);
            }
        }
        return result;
    }

    get implied() {
        return this.impliedOf(this.d.group_ids);
    }

    effectiveIndex(privilege, implied) {
        for (let i = privilege.levels.length - 1; i >= 0; i--) {
            if (implied.has(privilege.levels[i].id)) {
                return i;
            }
        }
        return -1;
    }

    explicitIndex(privilege) {
        for (let i = privilege.levels.length - 1; i >= 0; i--) {
            if (this.d.group_ids.includes(privilege.levels[i].id)) {
                return i;
            }
        }
        return -1;
    }

    /** The highest level of ``privilege`` given by *another* permission. */
    autoInfo(privilege) {
        const own = new Set(privilege.levels.map((l) => l.id));
        const others = this.d.group_ids.filter((gid) => !own.has(gid));
        const implied = this.impliedOf(others);
        const index = this.effectiveIndex(privilege, implied);
        if (index < 0) {
            return null;
        }
        const level = privilege.levels[index];
        const source = others.find((gid) => (this.catalog.implied[gid] || []).includes(level.id));
        const sourceRank = this.levelRank[source];
        const sourceName = sourceRank
            ? `${sourceRank.privilege.name}: ${this.catalog.group_names[source]}`
            : this.catalog.group_names[source];
        return { index, level, sourceName };
    }

    autoText(auto) {
        return _t("At least «%(level)s» comes with «%(source)s».", {
            level: auto.level.name,
            source: auto.sourceName,
        });
    }

    levelState(privilege, index) {
        const current = this.effectiveIndex(privilege, this.implied);
        const auto = this.autoInfo(privilege);
        return {
            active: index === current,
            included: index < current,
            locked: auto && index <= auto.index,
        };
    }

    setLevel(privilege, index) {
        const own = new Set(privilege.levels.map((l) => l.id));
        const groups = this.d.group_ids.filter((gid) => !own.has(gid));
        if (index >= 0) {
            groups.push(privilege.levels[index].id);
        }
        this.d.group_ids = groups;
        this.touch();
    }

    currentHelp(privilege) {
        const index = this.effectiveIndex(privilege, this.implied);
        return index < 0 ? _t("No access to this part.") : privilege.levels[index].help;
    }

    hasGroup(gid) {
        return this.d.group_ids.includes(gid);
    }

    isImplied(gid) {
        return !this.hasGroup(gid) && this.implied.has(gid);
    }

    toggleGroup(gid) {
        if (this.hasGroup(gid)) {
            this.d.group_ids = this.d.group_ids.filter((g) => g !== gid);
        } else {
            this.d.group_ids = [...this.d.group_ids, gid];
        }
        this.touch();
    }

    addGroup(gid) {
        const rank = this.levelRank[gid];
        if (rank && !rank.privilege.multi) {
            this.setLevel(rank.privilege, Math.max(rank.index, this.explicitIndex(rank.privilege)));
        } else if (!this.hasGroup(gid)) {
            this.toggleGroup(gid);
        }
    }

    // ---- restrictions
    toggleFlag(name) {
        this.d[name] = !this.d[name];
        this.touch();
    }

    openAdvanced() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "role.management",
            res_id: this.d.rm_id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("cst_role_builder", RoleBuilder);
