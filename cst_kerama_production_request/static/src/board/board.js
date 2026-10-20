/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { cookie } from "@web/core/browser/cookie";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { CstMoDialog, skeleton, fmtNumber } from "@cst_kerama_shift/mo_builder/mo_dialog";

const MODEL = "cst.production.request.board";
const TABS = [
    { id: "all", label: _t("Hammasi") },
    { id: "need", label: _t("Berilmagan") },
    { id: "sent", label: _t("Yuborildi") },
    { id: "progress", label: _t("Ishlab chiqarilmoqda") },
    { id: "done", label: _t("Tayyor") },
    { id: "released", label: _t("Sotuvga chiqarilgan") },
];

/**
 * Ishlab chiqarish zayafkalari — the sales side's planning screen.
 *
 * What the open sales orders need and the sales warehouse cannot cover is
 * listed line by line; the planner picks the bill, types how much the shop
 * can take now (not always the whole shortage), ticks «Tezkor» for what must
 * come out first, and sends the rows to a department. Each becomes a new order
 * in that department's window. Raised requests stay on the screen with their
 * progress until the goods are released to the sales order.
 */
export class ProductionRequestBoard extends Component {
    static template = "cst_kerama_production_request.Board";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.dark = cookie.get("color_scheme") === "dark";
        this.tabs = TABS;
        this.timers = {};
        this.state = useState({
            loading: true,
            busy: false,
            error: null,
            rows: [],
            departments: [],
            tab: "need",
            kind: "all",
            departmentId: "",
            onlyShort: true,
            withoutBom: false,
            priority: "all",
            search: "",
            selected: {},
            expanded: null,
            target: "",
        });
        onWillStart(() => this.load());
    }

    // ------------------------------------------------------------------ data
    async load() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(MODEL, "get_data", []);
            const old = new Map(this.state.rows.map((r) => [r.key, r]));
            for (const row of data.rows) {
                const prev = old.get(row.key);
                // what the planner typed survives a refresh
                if (prev && row.type === "need" && prev.edited) {
                    row.qty = prev.qty;
                    row.bom_id = prev.bom_id;
                    row.urgent = prev.urgent;
                    row.edited = true;
                }
                row.search = skeleton(`${row.partner} ${row.order} ${row.product} ${row.characteristic} ${row.code} ${row.request || ""}`);
            }
            this.state.rows = data.rows;
            this.state.departments = data.departments;
            const keys = new Set(data.rows.map((r) => r.key));
            for (const key of Object.keys(this.state.selected)) {
                if (!keys.has(key)) delete this.state.selected[key];
            }
            this.state.error = null;
        } catch (e) {
            this.state.error = (e.data && e.data.message) || e.message || String(e);
        }
        this.state.loading = false;
    }

    async call(method, args) {
        if (this.state.busy) return null;
        this.state.busy = true;
        try {
            return await this.orm.call(MODEL, method, args);
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || String(e), { type: "danger" });
            return null;
        } finally {
            this.state.busy = false;
        }
    }

    // ------------------------------------------------------------------ filtering
    inTab(row, tab) {
        if (tab === "all") return row.state !== "released";
        return row.state === tab;
    }
    baseFilter(row) {
        const s = this.state;
        if (row.type === "need") {
            if (s.onlyShort && !(row.short > 0)) return false;
            if (!s.withoutBom && !row.boms.length) return false;
        }
        if (s.kind !== "all" && row.kind !== s.kind) return false;
        if (s.departmentId && row.department_id !== Number(s.departmentId)) return false;
        if (s.priority === "urgent" && !row.urgent) return false;
        if (s.priority === "normal" && row.urgent) return false;
        if (s.search) {
            const words = s.search.split(/\s+/).map(skeleton).filter(Boolean);
            if (!words.every((w) => row.search.includes(w))) return false;
        }
        return true;
    }
    get filtered() {
        return this.state.rows.filter((r) => this.baseFilter(r));
    }
    get visibleRows() {
        const rows = this.filtered.filter((r) => this.inTab(r, this.state.tab));
        return rows.sort((a, b) => (b.urgent - a.urgent) || (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
    }
    tabCount(tab) {
        return this.filtered.filter((r) => this.inTab(r, tab)).length;
    }

    // ------------------------------------------------------------------ selection
    isSelectable(row) {
        if (row.type === "need") return (row.boms.length && row.qty > 0) || row.can_release;
        return row.can_release || row.can_cancel;
    }
    toggle(row) {
        if (this.state.selected[row.key]) delete this.state.selected[row.key];
        else if (this.isSelectable(row)) this.state.selected[row.key] = true;
    }
    get allChecked() {
        const rows = this.visibleRows.filter((r) => this.isSelectable(r));
        return rows.length > 0 && rows.every((r) => this.state.selected[r.key]);
    }
    toggleAll() {
        const rows = this.visibleRows.filter((r) => this.isSelectable(r));
        const on = !this.allChecked;
        for (const r of rows) {
            if (on) this.state.selected[r.key] = true;
            else delete this.state.selected[r.key];
        }
    }
    get selectedRows() {
        return this.state.rows.filter((r) => this.state.selected[r.key]);
    }
    get toCreate() {
        return this.selectedRows.filter((r) => r.type === "need" && r.boms.length && r.qty > 0);
    }
    get toRelease() {
        return this.selectedRows.filter((r) => r.can_release);
    }
    get selectedQty() {
        return this.num(this.selectedRows.reduce((sum, r) => sum + Number(r.qty || 0), 0));
    }

    // ------------------------------------------------------------------ row edits
    num(value) { return fmtNumber(value); }
    bomOf(row) { return row.boms.find((b) => b.id === row.bom_id) || row.boms[0] || null; }
    departmentLabel(row) {
        if (row.type === "request") return row.department;
        if (this.state.target) {
            const dep = this.state.departments.find((d) => d.id === Number(this.state.target));
            return dep ? dep.name : "";
        }
        const bom = this.bomOf(row);
        return (bom && bom.department) || _t("bo'lim tanlanmagan");
    }
    onQty(row, ev) {
        const value = Number(String(ev.target.value).replace(",", "."));
        row.qty = Number.isFinite(value) && value > 0 ? value : 0;
        row.edited = true;
        if (row.qty > 0 && row.boms.length && !this.state.selected[row.key]) this.state.selected[row.key] = true;
        this.recheck(row);
    }
    onBom(row, ev) {
        row.bom_id = Number(ev.target.value);
        row.edited = true;
        this.recheck(row, 0);
    }
    onUrgent(row, ev) {
        const value = ev.target.checked;
        if (row.type === "request") {
            this.setUrgent(row, value);
            return;
        }
        row.urgent = value;
        row.edited = true;
    }
    async setUrgent(row, value) {
        const ok = await this.call("set_urgent", [row.request_id, value]);
        if (ok) {
            row.urgent = value;
            this.notification.add(value ? _t("%s: tezkor — navbat boshida", row.request) : _t("%s: oddiy navbat", row.request), { type: "info" });
        }
    }
    recheck(row, delay = 400) {
        clearTimeout(this.timers[row.key]);
        this.timers[row.key] = setTimeout(async () => {
            const dept = this.state.target || (this.bomOf(row) && this.bomOf(row).department_id) || false;
            try {
                row.material = await this.orm.call(MODEL, "check_row", [row.product_id, row.bom_id, row.qty || 1, dept]);
            } catch {
                /* keep the old answer */
            }
        }, delay);
    }
    onTarget(ev) {
        this.state.target = ev.target.value;
        for (const row of this.selectedRows.filter((r) => r.type === "need")) this.recheck(row, 0);
    }
    toggleExpand(row) {
        this.state.expanded = this.state.expanded === row.key ? null : row.key;
    }
    materialClass(row) {
        return `o_cpr_mat o_cpr_mat--${row.material.status}`;
    }
    stateClass(row) {
        return `o_cpr_state o_cpr_state--${row.state}`;
    }

    // ------------------------------------------------------------------ actions
    async createRequests() {
        const rows = this.toCreate;
        if (!rows.length) return;
        const payload = rows.map((r) => ({ sale_line_id: r.sale_line_id, bom_id: r.bom_id, qty: r.qty, urgent: r.urgent }));
        const res = await this.call("create_requests", [payload, this.state.target ? Number(this.state.target) : false]);
        if (!res) return;
        if (res.created.length) {
            this.notification.add(_t("Zayafka yaratildi: %s", res.created.join(", ")), { type: "success" });
        }
        for (const err of res.errors) this.notification.add(err, { type: "danger", sticky: true });
        for (const r of rows) {
            delete this.state.selected[r.key];
            r.edited = false;
        }
        await this.load();
    }
    releaseSelected() {
        const rows = this.toRelease;
        if (!rows.length) return;
        this.dialog.add(ConfirmationDialog, {
            title: _t("Sotuvga chiqarish"),
            body: _t("%s ta qator: tayyor mahsulot sotuv buyurtmasining jo'natmasiga band qilinadi.", rows.length),
            confirmLabel: _t("Chiqarish"),
            confirm: async () => {
                const res = await this.call("release", [rows.map((r) => r.key)]);
                if (!res) return;
                this.notification.add(_t("Sotuvga chiqarildi: %(n)s ta · band qilindi %(qty)s", { n: res.done.length, qty: this.num(res.reserved) }), { type: "success" });
                for (const r of rows) delete this.state.selected[r.key];
                await this.load();
            },
            cancel: () => {},
        });
    }
    cancelRequest(row) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Zayafkani bekor qilish"),
            body: _t("%s va uning ishlab chiqarish buyurtmasi bekor qilinadi.", row.request),
            confirmLabel: _t("Bekor qilish"),
            confirm: async () => {
                const ok = await this.call("cancel_request", [row.request_id]);
                if (ok) await this.load();
            },
            cancel: () => {},
        });
    }
    openStockRequest() {
        const spec = (method) => ({ model: MODEL, method, args: [] });
        this.dialog.add(CstMoDialog, {
            title: _t("Ombor to'ldirish zayafkasi"),
            subtitle: _t("Sotuv buyurtmasisiz — tayyor mahsulot omborga"),
            optionsCall: spec("mo_options"),
            previewCall: spec("mo_preview"),
            createCall: spec("create_stock_request"),
            searchCall: spec("mo_search_products"),
            onCreated: async (res) => {
                this.notification.add(_t("%(req)s: %(mo)s bo'lim navbatiga tushdi", { req: res.request, mo: res.name }), { type: "success" });
                await this.load();
            },
        });
    }
    openRecord(model, id) {
        this.action.doAction({ type: "ir.actions.act_window", res_model: model, res_id: id, views: [[false, "form"]] });
    }
    isDept(dep) { return this.state.departmentId === String(dep.id); }
    setTab(tab) { this.state.tab = tab; }
    pickDepartment(dep) {
        this.state.departmentId = this.state.departmentId === String(dep.id) ? "" : String(dep.id);
        if (this.state.departmentId && this.state.tab === "need") this.state.tab = "all";
    }
}

registry.category("actions").add("cst_production_request_board", ProductionRequestBoard);
