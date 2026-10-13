/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { cookie } from "@web/core/browser/cookie";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

const CYR = { а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "yo", ж: "j", з: "z", и: "i", й: "y", к: "k", л: "l",
    м: "m", н: "n", о: "o", п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f", х: "h", ц: "ts", ч: "ch", ш: "sh", щ: "sh",
    ъ: "", ы: "i", ь: "", э: "e", ю: "yu", я: "ya", ў: "o", қ: "k", ғ: "g", ҳ: "h" };
/** Cyrillic and Latin spellings fold to one key: «kashmir» finds «Кашмир». */
function skeleton(text) {
    let out = "";
    for (const ch of String(text || "").toLowerCase()) out += ch in CYR ? CYR[ch] : ch;
    return out.replace(/kh/g, "h").replace(/x/g, "h").replace(/q/g, "k").replace(/['\u2018\u2019`\u02bb\u02bc]/g, "").replace(/[^a-z0-9]+/g, "");
}

/**
 * Bo'lim oynasi — one department's shift screen, laid out after the shop's
 * own mock, reworked for the floor: orders as a wide board (waiting, one
 * column per line, done) with the result history below; shifts, people,
 * today's plan, quality and raw material in one sidebar on the right.
 */
export class ShiftFloor extends Component {
    static template = "cst_kerama_shift.ShiftFloor";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dialogService = useService("dialog");
        const action = this.props.action || {};
        const fromAction = (action.params && action.params.department_id) || (action.context && action.context.active_id);
        this.dark = cookie.get("color_scheme") === "dark";
        this.state = useState({
            loading: true,
            busy: false,
            departments: [],
            departmentId: fromAction ? Number(fromAction) : null,
            d: null,
            tab: "queue",
            selectedLineId: null,
            dialog: null, // "open" | "pull" | "entry" | "close" | "employees"
            form: {},
            error: null,
            side: this._sideStored(),
        });
        onWillStart(async () => {
            this.state.departments = await this.orm.call("cst.production.floor", "get_departments", []);
            if (!this.state.departmentId && this.state.departments.length === 1) {
                this.state.departmentId = this.state.departments[0].id;
            }
            await this.load();
        });
    }

    // ------------------------------------------------------------------ data
    async load() {
        if (!this.state.departmentId) {
            this.state.loading = false;
            return;
        }
        this.state.loading = true;
        try {
            this.state.d = await this.orm.call("cst.production.floor", "get_department_data", [this.state.departmentId]);
            this.state.error = null;
            if (this.state.selectedLineId && !this.lines.find((l) => l.id === this.state.selectedLineId)) {
                this.state.selectedLineId = null;
            }
            if (!this.state.selectedLineId && this.runningLines.length) {
                this.state.selectedLineId = this.runningLines[0].id;
            }
        } catch (e) {
            this.state.error = (e.data && e.data.message) || e.message || String(e);
        }
        this.state.loading = false;
    }

    /** Run an action on the server; the fresh screen comes back with it. */
    async call(method, args, close = true) {
        // a second click while the first is still on its way made the same
        // order twice (ЯП/MO/00021 and 00023, 3 s apart)
        if (this.state.busy) return false;
        this.state.busy = true;
        try {
            const data = await this.orm.call("cst.production.floor", method, args);
            this.state.d = data;
            if (close) {
                this.state.dialog = null;
            }
            return true;
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || String(e), { type: "danger" });
            return false;
        } finally {
            this.state.busy = false;
        }
    }

    /** The side panel (shifts, people, plan) stays shut unless the manager opens it. */
    _sideStored() {
        try { return window.localStorage.getItem("cst_sf_side") === "1"; } catch { return false; }
    }
    toggleSide() {
        this.state.side = !this.state.side;
        try { window.localStorage.setItem("cst_sf_side", this.state.side ? "1" : "0"); } catch { /* private mode */ }
    }

    pickDepartment(id) {
        this.state.departmentId = Number(id);
        this.state.selectedLineId = null;
        this.load();
    }

    // ------------------------------------------------------------------ getters
    get d() { return this.state.d; }
    get shift() { return this.d && this.d.shift; }
    get lines() { return (this.shift && this.shift.lines) || []; }
    get runningLines() { return this.lines.filter((l) => ["todo", "progress", "paused"].includes(l.state)); }
    get doneLines() { return this.lines.filter((l) => ["done", "carried"].includes(l.state)); }
    get selectedLine() { return this.lines.find((l) => l.id === this.state.selectedLineId) || null; }
    get tabRows() {
        if (this.state.tab === "queue") return this.d.queue;
        if (this.state.tab === "running") return this.runningLines;
        return this.doneLines;
    }
    /** One board column per line of the department, plus any other line an
     *  order of this shift happens to run on (an alternative workcenter). */
    get boardColumns() {
        const cols = (this.d.department.lines || []).map((wc) => ({ id: wc.id, name: wc.name, lines: [] }));
        const byId = new Map(cols.map((c) => [c.id, c]));
        for (const line of this.runningLines) {
            let col = byId.get(line.workcenter_id);
            if (!col) {
                col = { id: line.workcenter_id, name: line.workcenter, lines: [] };
                byId.set(col.id, col);
                cols.push(col);
            }
            col.lines.push(line);
        }
        return cols;
    }
    get entryMaterial() {
        const f = this.state.form || {};
        return ((f.opts && f.opts.materials) || []).find((m) => m.id === Number(f.material_product_id)) || null;
    }
    get shiftEmployees() { return (this.d.employees || []).filter((e) => e.in_shift); }
    /* OWL templates cannot reach globals such as Number or Math: keep those here. */
    barStyle(bar, dep) {
        const h = bar.value ? Math.max(8, Math.round((bar.value / (dep.bars_max || 1)) * 56)) : 3;
        return `height: ${h}px`;
    }
    barsTitle(dep) {
        return (dep.bars || []).map((b) => `${b.label}: ${b.value}`).join(" · ");
    }
    get selectedProductId() { return Number(this.state.form.product_id); }
    get selectedPick() { return this.state.form.pick || ""; }
    get waitingTemplates() { return (this.d.templates || []).filter((t) => t.state === "waiting"); }
    get sharesOk() {
        const f = this.state.form || {};
        const sums = this.shareSums;
        return {
            kpi: Math.round(sums.kpi) === Math.round(Number(f.kpi_total || 0)),
            penalty: Math.round(sums.penalty) === Math.round(Number(f.penalty_total || 0)),
        };
    }
    get canAct() { return this.d && this.d.can_manage && this.shift && this.shift.state === "open"; }

    // ------------------------------------------------------------------ formatting
    num(value, digits = 0) {
        return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 0, maximumFractionDigits: digits }).format(value || 0);
    }
    money(value) { return this.num(value, 0); }
    pct(value) { return `${Math.round(value || 0)}%`; }
    barWidth(value, total) {
        if (!total) return "0%";
        return `${Math.min(100, Math.max(0, (value / total) * 100))}%`;
    }
    stateClass(state) {
        return { progress: "run", paused: "warn", done: "ok", carried: "muted", todo: "muted",
                 ready: "ok", pending: "muted", waiting: "warn", open: "ok", closed: "muted", waiting_t: "muted" }[state] || "muted";
    }
    /** Quality donut: three arcs on a 100-unit circle. */
    donut() {
        const k = this.d.kpis;
        const parts = [["good", k.good_pct], ["second", k.second_pct], ["scrap", k.scrap_pct]];
        let offset = 25;
        return parts.map(([key, pct]) => {
            const seg = { key, pct, dash: `${pct} ${100 - pct}`, offset };
            offset -= pct;
            return seg;
        });
    }

    // ------------------------------------------------------------------ dialogs
    openDialog(name, form = {}) {
        this.state.form = form;
        this.state.dialog = name;
    }
    closeDialog() { this.state.dialog = null; }

    startOpenShift(template) {
        const present = this.d.employees.filter((e) => e.present).map((e) => e.id);
        const staff = this.d.employees.filter((e) => e.staff).map((e) => e.id);
        this.openDialog("open", {
            template_id: template ? template.id : (this.d.templates[0] && this.d.templates[0].id),
            date: this.d.department.today,
            employee_ids: present.length ? present : staff,
        });
    }
    toggleFormEmployee(id) {
        const set = new Set(this.state.form.employee_ids || []);
        set.has(id) ? set.delete(id) : set.add(id);
        this.state.form.employee_ids = [...set];
    }
    async confirmOpenShift() {
        const f = this.state.form;
        await this.call("open_shift", [this.state.departmentId, Number(f.template_id), f.date, f.employee_ids]);
    }

    startPull(row) {
        this.state.form = {
            row, workorder_id: row.workorder_id, workcenter_id: row.workcenter_id,
            planned_qty: row.remaining || row.qty, employee_ids: this.shift.employee_ids.slice(), materials: null, start: true,
        };
        this.state.dialog = "pull";
        this.orm.call("cst.production.floor", "check_materials", [row.workorder_id]).then((rows) => {
            this.state.form.materials = rows;
        });
    }
    async confirmPull() {
        const f = this.state.form;
        await this.call("pull_order", [this.shift.id, f.workorder_id, Number(f.workcenter_id), Number(f.planned_qty), f.employee_ids, f.start]);
    }

    startEntry(line) {
        this.state.selectedLineId = line.id;
        // what is left of the order fills 1-sort; 2-sort and brak come out of it
        const total = Math.max(0, line.final ? Math.min(line.remaining, line.order_left) : line.remaining);
        this.openDialog("entry", { line, total, good: total || "", second: "", scrap: "", note: "", opts: null,
            second_product_id: "", material_product_id: "", material_qty: "" });
        const form = this.state.form;
        this.orm.call("cst.production.floor", "entry_options", [line.id]).then((opts) => { form.opts = opts; });
    }
    /** 2-sort or brak typed: 1-sort is what is left of the total. 1-sort typed
     *  by hand: that becomes the new total. */
    onEntryInput(field, ev) {
        const f = this.state.form;
        f[field] = ev.target.value;
        const second = Number(f.second || 0);
        const scrap = Number(f.scrap || 0);
        if (field === "good") {
            f.total = Number(f.good || 0) + second + scrap;
        } else {
            f.good = Math.max(0, Number(f.total || 0) - second - scrap);
            f.total = Number(f.good) + second + scrap;
        }
    }
    async confirmEntry(finish = false) {
        const f = this.state.form;
        if (f.material_product_id && !Number(f.material_qty)) {
            this.notification.add("Material braki miqdorini kiriting.", { type: "warning" });
            return;
        }
        if (finish === true && !Number(f.good || 0) && !Number(f.second || 0) && !Number(f.scrap || 0) && !f.material_product_id) {
            await this.call("line_action", [f.line.id, "finish"]);
            return;
        }
        await this.call("add_entry", [f.line.id, Number(f.good || 0), Number(f.second || 0), Number(f.scrap || 0), f.note || "",
            Number(f.second_product_id) || false, Number(f.material_product_id) || false, Number(f.material_qty || 0), finish === true]);
    }

    async lineAction(line, action) {
        this.state.selectedLineId = line.id;
        if (action === "finish" && !Number(line.total || 0)) {
            // nothing typed: the server books the whole rest as 1-sort
            const left = line.final ? line.order_left : line.remaining;
            const ok = await new Promise((resolve) => this.dialogService.add(ConfirmationDialog, {
                title: "Natija kiritilmagan",
                body: `${line.mo}: natija kiritilmagan. ${left} dona 1-sort deb to'liq yakunlansinmi?`,
                confirmLabel: "Ha, to'liq yakunlash", cancelLabel: "Bekor qilish",
                confirm: () => resolve(true), cancel: () => resolve(false),
            }, { onClose: () => resolve(false) }));
            if (!ok) return;
        }
        await this.call("line_action", [line.id, action], false);
    }

    /** A wrong order (wrong characteristic, a double) goes away before any result. */
    async cancelOrder(row, isLine) {
        if (!row.can_cancel) {
            this.notification.add(`${row.mo}: natija kiritilgan yoki omborda harakat bo'lgan — bekor qilib bo'lmaydi. Avval yakunlang, so'ng «Bajarilganlar»dan o'chiring.`, { type: "warning" });
            return;
        }
        const ok = await new Promise((resolve) => this.dialogService.add(ConfirmationDialog, {
            title: "Buyurtmani bekor qilish",
            body: `${row.mo}: buyurtma bekor qilinadi (xomashyo zaxirasi bo'shatiladi). Davom etilsinmi?`,
            confirmLabel: "Ha, bekor qilish", cancelLabel: "Yo'q",
            confirm: () => resolve(true), cancel: () => resolve(false),
        }, { onClose: () => resolve(false) }));
        if (!ok) return;
        await this.call("cancel_order", [this.state.departmentId, isLine ? row.id : false, isLine ? false : row.workorder_id], false);
    }

    /** 🗑 on a finished card: unbuild — the pieces leave stock, materials return. */
    async undoDone(line) {
        if (line.undo_blocker) {
            this.notification.add(`${line.mo}: o'chirib bo'lmaydi — ${line.undo_blocker}.`, { type: "warning" });
            return;
        }
        const ok = await new Promise((resolve) => this.dialogService.add(ConfirmationDialog, {
            title: "Bajarilgan buyurtmani o'chirish",
            body: `${line.mo}: ${line.good} dona ombordan chiqariladi, xomashyo omborga qaytariladi va natija smenadan o'chiriladi. Davom etilsinmi?`,
            confirmLabel: "Ha, o'chirish", cancelLabel: "Yo'q",
            confirm: () => resolve(true), cancel: () => resolve(false),
        }, { onClose: () => resolve(false) }));
        if (!ok) return;
        await this.call("undo_done", [this.state.departmentId, line.id], false);
    }

    async startClose() {
        const preview = await this.orm.call("cst.production.floor", "close_preview", [this.shift.id, this.shift.kpi_total || 0, this.shift.penalty_total || 0]);
        this.openDialog("close", {
            kpi_total: this.shift.kpi_total || 0, penalty_total: this.shift.penalty_total || 0,
            shares: preview.shares, open_lines: preview.open_lines, note: "",
        });
    }
    async recomputeShares() {
        const f = this.state.form;
        const preview = await this.orm.call("cst.production.floor", "close_preview", [this.shift.id, Number(f.kpi_total || 0), Number(f.penalty_total || 0)]);
        f.shares = preview.shares;
    }
    get shareSums() {
        const shares = (this.state.form && this.state.form.shares) || [];
        return {
            kpi: shares.reduce((s, r) => s + Number(r.kpi_amount || 0), 0),
            penalty: shares.reduce((s, r) => s + Number(r.penalty_amount || 0), 0),
        };
    }
    async confirmClose() {
        const f = this.state.form;
        await this.call("close_shift", [this.shift.id, Number(f.kpi_total || 0), Number(f.penalty_total || 0),
            f.shares.map((r) => ({ employee_id: r.employee_id, kpi_amount: Number(r.kpi_amount || 0), penalty_amount: Number(r.penalty_amount || 0) })), f.note || ""]);
    }

    /** «Yangi buyurtma qo'shish»: a product of this department, a quantity, a line,
     *  and the material list the manager may trim, top up or extend. */
    async startNewOrder(allProducts = false) {
        allProducts = allProducts === true;  // never the click event
        const products = await this.orm.call("cst.production.floor", "product_options", [this.state.departmentId, allProducts]);
        const first = products.find((p) => !p.foreign) || products[0];
        this.openDialog("new", {
            products, allProducts, product_id: first ? first.id : null, bom_id: first ? first.bom_id : null,
            pick: first ? first.key : "", charFilter: "", havolaFilter: "", qty: "",
            workcenter_id: this.d.department.lines.length ? this.d.department.lines[0].id : null,
            employee_ids: this.shift.employee_ids.slice(), materials: null, start: true, filter: "",
            extraQuery: "", extraResults: [], edited: false, removedIds: [],
        });
        if (first) this.refreshNewMaterials();
    }
    async toggleAllProducts() {
        const f = this.state.form;
        f.allProducts = !f.allProducts;
        f.products = await this.orm.call("cst.production.floor", "product_options", [this.state.departmentId, f.allProducts]);
        f.charFilter = ""; f.havolaFilter = "";
    }
    /** Values for the «Xarakteristika» and «Havola» dropdowns, from what is listed. */
    _distinct(field) {
        return [...new Set((this.state.form.products || []).map((p) => p[field]).filter(Boolean))]
            .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    }
    get characteristicOptions() { return this._distinct("characteristic"); }
    get havolaOptions() { return this._distinct("havola"); }
    get filteredProducts() {
        // every typed word on its own: «бел лдсп» finds «Белый Корона ЛДСП»,
        // which one skeleton of the whole text («belldsp») never could
        const f = this.state.form;
        const words = String(f.filter || "").split(/[\s,;]+/).map(skeleton).filter(Boolean);
        return (f.products || []).filter((p) =>
            (!f.charFilter || p.characteristic === f.charFilter)
            && (!f.havolaFilter || p.havola === f.havolaFilter)
            && words.every((w) => p.search.includes(w)));
    }
    get selectedProduct() {
        return (this.state.form.products || []).find((p) => p.key === this.state.form.pick) || null;
    }
    clearProductFilters() {
        Object.assign(this.state.form, { filter: "", charFilter: "", havolaFilter: "" });
    }
    /** The exploded list for the typed quantity. A quantity the manager typed
     *  on a row, a row they removed and a material they added all survive a
     *  refresh; only the bill-of-materials requirement is recomputed. */
    async refreshNewMaterials(force = false) {
        const f = this.state.form;
        if (!f.product_id) { f.materials = []; return; }
        const fresh = (await this.orm.call("cst.production.floor", "bom_materials", [Number(f.product_id), Number(f.qty || 1), f.bom_id || false, this.state.departmentId]))
            .map((m) => ({ ...m, qty: m.needed, extra: false, touched: false }));
        if (force || !f.edited) {
            f.materials = fresh;
            f.removedIds = [];
            f.edited = false;
            return;
        }
        const prev = f.materials || [];
        const removed = new Set(f.removedIds || []);
        const byId = new Map(prev.map((m) => [m.id, m]));
        const kept = fresh.filter((m) => !removed.has(m.id)).map((m) => {
            const old = byId.get(m.id);
            return old && old.touched ? { ...m, qty: old.qty, touched: true, ok: m.free >= old.qty } : m;
        });
        f.materials = [...kept, ...prev.filter((m) => m.extra)];
    }
    onNewQtyInput(ev) {
        this.state.form.qty = ev.target.value;
        clearTimeout(this._qtyTimer);
        this._qtyTimer = setTimeout(() => this.refreshNewMaterials(), 350);
    }
    onNewProductChange(ev) {
        const f = this.state.form;
        const row = (f.products || []).find((p) => p.key === ev.target.value);
        if (!row) return;
        f.pick = row.key;
        f.product_id = row.id;
        f.bom_id = row.bom_id;
        f.edited = false;
        this.refreshNewMaterials(true);
    }
    resetMaterials() {
        this.state.form.edited = false;
        this.refreshNewMaterials(true);
    }
    setMaterialQty(row, ev) {
        row.qty = Number(ev.target.value || 0);
        row.ok = row.free >= row.qty;
        row.touched = true;
        this.state.form.edited = true;
    }
    removeMaterial(row) {
        const f = this.state.form;
        if (!row.extra) f.removedIds = [...(f.removedIds || []), row.id];
        f.materials = f.materials.filter((m) => m !== row);
        f.edited = true;
    }
    onExtraInput(ev) {
        const f = this.state.form;
        f.extraQuery = ev.target.value;
        clearTimeout(this._extraTimer);
        this._extraTimer = setTimeout(async () => {
            f.extraResults = f.extraQuery.trim().length >= 2
                ? await this.orm.call("cst.production.floor", "search_products", [f.extraQuery.trim(), 12, this.state.departmentId]) : [];
        }, 300);
    }
    addExtraMaterial(p) {
        const f = this.state.form;
        if (!(f.materials || []).some((m) => m.id === p.id)) {
            f.materials = [...(f.materials || []), { id: p.id, product: p.product, characteristic: p.characteristic,
                needed: 0, qty: 1, free: p.free, uom: p.uom, ok: p.free >= 1, extra: true, touched: true }];
        }
        f.extraQuery = ""; f.extraResults = []; f.edited = true;
    }
    async confirmNewOrder() {
        const f = this.state.form;
        if (!f.product_id || !Number(f.qty)) {
            this.notification.add("Mahsulot va miqdorni kiriting.", { type: "warning" });
            return;
        }
        const chosen = this.selectedProduct;
        if (chosen && chosen.foreign) {
            this.notification.add("Bu mahsulot texkartasida shu bo'lim operatsiyasi yo'q; u boshqa bo'lim navbatiga tushadi.", { type: "warning" });
        }
        const materials = f.edited ? (f.materials || []).map((m) => ({ product_id: m.id, qty: Number(m.qty || 0) })) : null;
        await this.call("create_order", [this.shift.id, Number(f.product_id), Number(f.qty), Number(f.workcenter_id), f.employee_ids, f.start, materials, f.bom_id || false]);
    }

    startEmployees() {
        this.openDialog("employees", { employee_ids: this.shift.employee_ids.slice() });
    }
    async confirmEmployees() {
        await this.call("update_employees", [this.shift.id, this.state.form.employee_ids]);
    }

    openRecord(model, id) {
        if (!id) return;
        this.action.doAction({ type: "ir.actions.act_window", res_model: model, res_id: id, views: [[false, "form"]], target: "current" });
    }
    openShiftForm() { if (this.shift) this.openRecord("cst.production.shift", this.shift.id); }
}

registry.category("actions").add("cst_shift_floor", ShiftFloor);
