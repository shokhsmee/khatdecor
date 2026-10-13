import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

const CYR = {
    а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "yo", ж: "j", з: "z", и: "i", й: "y", к: "k",
    л: "l", м: "m", н: "n", о: "o", п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f", х: "h", ц: "ts",
    ч: "ch", ш: "sh", щ: "sh", ъ: "", ы: "i", ь: "", э: "e", ю: "yu", я: "ya", ў: "o", қ: "k", ғ: "g", ҳ: "h",
};

/** Cyrillic and Latin spellings of the same word fold to one key. */
export function skeleton(text) {
    let out = "";
    for (const ch of (text || "").toLowerCase()) {
        out += ch in CYR ? CYR[ch] : ch;
    }
    out = out.replace(/kh/g, "h").replace(/x/g, "h").replace(/q/g, "k");
    out = out.replace(/['‘’`ʻʼ]/g, "");
    return out.replace(/[^a-z0-9]+/g, "");
}

export function fmtNumber(value, digits = 2) {
    const n = Number(value || 0);
    return Number.isInteger(n) ? String(n) : n.toFixed(digits).replace(/\.?0+$/, "");
}

/**
 * «Yangi buyurtma»: one dialog for raising a manufacturing order, used by the
 * Shop Floor and by the Project Hub.
 *
 * Pick a product (variant), type the quantity, get the bill of materials
 * exploded against free stock, then shape it — drop or add components, change
 * quantities — and choose which operations run and on which line. The bill of
 * materials itself is never changed.
 *
 * The three server calls are given as props, so each screen keeps its own
 * rules about what may be made and what the order is stamped with:
 *   optionsCall  → { products: [...], workcenters: [...], plan?: [...] }
 *   previewCall  (…, product_id, qty) → { materials: [...], operations: [...] }
 *   createCall   (…, product_id, qty, materials, operations) → { id, name }
 */
export class CstMoDialog extends Component {
    static template = "cst_kerama_shift.MoDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        onCreated: Function,
        title: { type: String, optional: true },
        subtitle: { type: String, optional: true },
        optionsCall: Object,
        previewCall: Object,
        createCall: Object,
        searchCall: { type: Object, optional: true },
        defaults: { type: Object, optional: true },
        plan: { type: Array, optional: true },
        planTitle: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            busy: false,
            products: [],
            workcenters: [],
            plan: this.props.plan || [],
            filter: "",
            productId: null,
            qty: "",
            materials: null,
            operations: [],
            edited: false,
            removedIds: [],
            extraQuery: "",
            extraResults: [],
        });
        onWillStart(async () => {
            const res = await this.call(this.props.optionsCall);
            this.state.products = res.products || [];
            this.state.workcenters = res.workcenters || [];
            if (res.plan && res.plan.length) {
                this.state.plan = res.plan;
            }
            const defaults = this.props.defaults || {};
            const first = defaults.product_id || (this.state.plan.length ? this.state.plan[0].product_id : null);
            this.state.loading = false;
            if (first) {
                const qty = defaults.qty || (this.state.plan.length ? this.state.plan[0].qty : "");
                this.state.productId = Number(first);
                this.state.qty = qty ? String(qty) : "";
                await this.refresh(true);
            }
        });
    }

    call(spec, extra = []) {
        return this.orm.call(spec.model, spec.method, [...(spec.args || []), ...extra]);
    }

    get title() {
        return this.props.title || _t("Yangi buyurtma");
    }

    // ------------------------------------------------------------ products
    get filteredProducts() {
        const key = skeleton(this.state.filter);
        const rows = key ? this.state.products.filter((p) => p.key.includes(key)) : this.state.products;
        return rows.slice(0, 80);
    }

    get filteredCount() {
        const key = skeleton(this.state.filter);
        return key ? this.state.products.filter((p) => p.key.includes(key)).length : this.state.products.length;
    }

    get selectedProduct() {
        return this.state.products.find((p) => p.id === this.state.productId) || null;
    }

    onFilterInput(ev) {
        this.state.filter = ev.target.value;
    }

    selectProduct(product) {
        if (this.state.productId === product.id) {
            return;
        }
        this.state.productId = product.id;
        this.state.edited = false;
        this.state.operations = [];
        this.refresh(true);
    }

    /** A row of the calling screen's plan: «this is what is still to be made». */
    pickPlanRow(row) {
        this.state.productId = Number(row.product_id);
        this.state.qty = String(row.qty || "");
        this.state.edited = false;
        this.state.operations = [];
        this.refresh(true);
    }

    onQtyInput(ev) {
        this.state.qty = ev.target.value;
        clearTimeout(this._qtyTimer);
        this._qtyTimer = setTimeout(() => this.refresh(), 350);
    }

    // ------------------------------------------------------------ bill of materials
    /** Reload the exploded list for the typed quantity. Rows the user touched,
     *  removed or added survive; only the requirement is recomputed. */
    async refresh(force = false) {
        const s = this.state;
        if (!s.productId) {
            s.materials = [];
            s.operations = [];
            return;
        }
        const res = await this.call(this.props.previewCall, [s.productId, Number(s.qty || 1)]);
        const fresh = (res.materials || []).map((m) => ({ ...m, qty: m.needed, extra: false, touched: false }));
        if (force || !s.operations.length) {
            s.operations = res.operations || [];
        }
        if (force || !s.edited) {
            s.materials = fresh;
            s.removedIds = [];
            s.edited = false;
            return;
        }
        const prev = s.materials || [];
        const removed = new Set(s.removedIds || []);
        const byId = new Map(prev.map((m) => [m.id, m]));
        const kept = fresh
            .filter((m) => !removed.has(m.id))
            .map((m) => {
                const old = byId.get(m.id);
                return old && old.touched ? { ...m, qty: old.qty, touched: true, ok: m.free >= old.qty } : m;
            });
        s.materials = [...kept, ...prev.filter((m) => m.extra)];
    }

    resetMaterials() {
        this.state.edited = false;
        this.refresh(true);
    }

    setMaterialQty(row, ev) {
        row.qty = Number(ev.target.value || 0);
        row.ok = row.free >= row.qty;
        row.touched = true;
        this.state.edited = true;
    }

    removeMaterial(row) {
        const s = this.state;
        if (!row.extra) {
            s.removedIds = [...(s.removedIds || []), row.id];
        }
        s.materials = s.materials.filter((m) => m !== row);
        s.edited = true;
    }

    onExtraInput(ev) {
        const s = this.state;
        s.extraQuery = ev.target.value;
        clearTimeout(this._extraTimer);
        this._extraTimer = setTimeout(async () => {
            const query = s.extraQuery.trim();
            const spec = this.props.searchCall || { model: "cst.mo.builder", method: "mo_search_products", args: [] };
            s.extraResults = query.length >= 2 ? await this.call(spec, [query, 12]) : [];
        }, 300);
    }

    addExtraMaterial(product) {
        const s = this.state;
        if (!(s.materials || []).some((m) => m.id === product.id)) {
            s.materials = [
                ...(s.materials || []),
                {
                    id: product.id, product: product.product, characteristic: product.characteristic,
                    needed: 0, qty: 1, free: product.free, uom: product.uom, ok: product.free >= 1,
                    extra: true, touched: true,
                },
            ];
        }
        s.extraQuery = "";
        s.extraResults = [];
        s.edited = true;
    }

    // ------------------------------------------------------------ operations
    toggleOperation(op) {
        op.selected = !op.selected;
    }

    setOperationWc(op, ev) {
        op.workcenter_id = Number(ev.target.value);
    }

    // ------------------------------------------------------------ confirm
    fmt(value) {
        return fmtNumber(value);
    }

    get shortMaterials() {
        return (this.state.materials || []).filter((m) => !m.ok);
    }

    get canConfirm() {
        const s = this.state;
        return !!s.productId && Number(s.qty) > 0 && s.operations.some((o) => o.selected) && !s.busy;
    }

    async confirm() {
        const s = this.state;
        if (!this.canConfirm) {
            return;
        }
        s.busy = true;
        const materials = s.edited
            ? s.materials.filter((m) => Number(m.qty) > 0).map((m) => ({ product_id: m.id, qty: Number(m.qty) }))
            : null;
        const operations = s.operations.map((o) => ({ id: o.id, selected: !!o.selected, workcenter_id: o.workcenter_id }));
        try {
            const res = await this.call(this.props.createCall, [s.productId, Number(s.qty), materials, operations]);
            this.notification.add(_t("%s yaratildi", res.name), { type: "success" });
            await this.props.onCreated(res);
            this.props.close();
        } catch (error) {
            s.busy = false;
            throw error;
        }
    }
}
