/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { MultiRecordSelector } from "@web/core/record_selectors/multi_record_selector";
import { formatFloat } from "@web/core/utils/numbers";

const TABS = [
    { id: "product", label: "Mahsulotlar" },
    { id: "partner", label: "Mijozlar" },
    { id: "user", label: "Sotuvchilar" },
    { id: "category", label: "Kategoriyalar" },
];

// [key, title, kind, band]
const FIGURES = [
    ["docs", "Hujjat", "int", "sale"],
    ["qty", "Miqdor", "qty", "sale"],
    ["price", "O'rtacha narx", "money", "sale"],
    ["unit_cost", "Tannarx (dona)", "money", "sale"],
    ["amount", "Summa", "money", "sale"],
    ["cost", "Tannarx summasi", "money", "sale"],
    ["ret_docs", "Hujjat", "int", "ret"],
    ["ret_qty", "Miqdor", "qty", "ret"],
    ["ret_price", "Narx", "money", "ret"],
    ["ret_amount", "Summa", "money", "ret"],
    ["ret_cost", "Tannarx summasi", "money", "ret"],
    ["markup", "Ustama %", "pct", "prof"],
    ["margin", "Marja %", "pct", "prof"],
    ["profit", "Foyda", "money", "prof"],
];
const NO_TOTAL = new Set(["price", "unit_cost", "ret_price"]);

function iso(d) {
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/**
 * «Mahsulot foyda/zarari» — sales, returns and profit for a period, grouped
 * by product / client / salesperson / category (МойСклад «Прибыльность»).
 * Figures come from cst.profitability.report.get_data.
 */
export class Profitability extends Component {
    static template = "cst_kerama_reports.Profitability";
    static components = { MultiRecordSelector };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.tabs = TABS;
        this.figures = FIGURES;
        this.state = useState({
            loading: true,
            groupBy: "product",
            dateFrom: "",
            dateTo: "",
            companyIds: [],
            warehouseIds: [],
            categIds: [],
            partnerIds: [],
            userIds: [],
            services: true,
            search: "",
            sortKey: "amount",
            sortAsc: false,
            data: null,
            showFilters: false,
        });
        onWillStart(async () => {
            const d = await this.orm.call("cst.profitability.report", "get_defaults", []);
            Object.assign(this.state, { dateFrom: d.date_from, dateTo: d.date_to, companyIds: d.company_ids });
            await this.load();
        });
    }

    get options() {
        const s = this.state;
        return {
            date_from: s.dateFrom,
            date_to: s.dateTo,
            company_ids: s.companyIds,
            warehouse_ids: s.warehouseIds,
            categ_ids: s.categIds,
            partner_ids: s.partnerIds,
            user_ids: s.userIds,
            services: s.services,
            group_by: s.groupBy,
        };
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("cst.profitability.report", "get_data", [this.options]);
        } finally {
            this.state.loading = false;
        }
    }

    setTab(id) {
        if (this.state.groupBy === id) {
            return;
        }
        this.state.groupBy = id;
        this.load();
    }

    setPeriod(kind) {
        const now = new Date();
        let from = new Date(now);
        let to = new Date(now);
        if (kind === "week") {
            from.setDate(now.getDate() - ((now.getDay() + 6) % 7));
        } else if (kind === "month") {
            from = new Date(now.getFullYear(), now.getMonth(), 1);
        } else if (kind === "prev_month") {
            from = new Date(now.getFullYear(), now.getMonth() - 1, 1);
            to = new Date(now.getFullYear(), now.getMonth(), 0);
        } else if (kind === "year") {
            from = new Date(now.getFullYear(), 0, 1);
        }
        this.state.dateFrom = iso(from);
        this.state.dateTo = iso(to);
        this.load();
    }

    onDate(key, ev) {
        this.state[key] = ev.target.value;
        if (this.state.dateFrom && this.state.dateTo) {
            this.load();
        }
    }

    onSelect(key, ids) {
        this.state[key] = ids;
        this.load();
    }

    toggleServices(ev) {
        this.state.services = ev.target.checked;
        this.load();
    }

    clearFilters() {
        Object.assign(this.state, { warehouseIds: [], categIds: [], partnerIds: [], userIds: [], search: "" });
        this.load();
    }

    get filterCount() {
        const s = this.state;
        return [s.warehouseIds, s.categIds, s.partnerIds, s.userIds].filter((x) => x.length).length;
    }

    sortBy(key) {
        if (this.state.sortKey === key) {
            this.state.sortAsc = !this.state.sortAsc;
        } else {
            this.state.sortKey = key;
            this.state.sortAsc = ["name", "char", "code"].includes(key);
        }
    }

    get isProduct() {
        return this.state.groupBy === "product";
    }

    get nameTitle() {
        return { product: "Mahsulot", partner: "Mijoz", user: "Sotuvchi", category: "Kategoriya" }[this.state.groupBy];
    }

    get rows() {
        const data = this.state.data;
        if (!data) {
            return [];
        }
        const q = this.state.search.trim().toLowerCase();
        let rows = data.rows;
        if (q) {
            const words = q.split(/\s+/);
            rows = rows.filter((r) => {
                const hay = [r.name, r.char, r.code, r.barcode].join(" ").toLowerCase();
                return words.every((w) => hay.includes(w));
            });
        }
        const key = this.state.sortKey;
        const dir = this.state.sortAsc ? 1 : -1;
        return [...rows].sort((a, b) => {
            const x = a[key];
            const y = b[key];
            if (x === y) {
                return 0;
            }
            if (x === null || x === undefined) {
                return 1;
            }
            if (y === null || y === undefined) {
                return -1;
            }
            if (typeof x === "string") {
                return x.localeCompare(y) * dir;
            }
            return (x - y) * dir;
        });
    }

    fmt(value, kind) {
        if (value === null || value === undefined || value === false) {
            return "—";
        }
        if (kind === "int") {
            return value ? String(value) : "";
        }
        if (kind === "qty") {
            return value ? formatFloat(value, { digits: [16, 3] }).replace(/([.,]\d*?)0+$/, "$1").replace(/[.,]$/, "") : "";
        }
        if (kind === "pct") {
            return `${formatFloat(value, { digits: [16, 2] })}%`;
        }
        return value ? formatFloat(value, { digits: [16, 2] }) : "";
    }

    totalCell(key, kind) {
        if (NO_TOTAL.has(key)) {
            return "";
        }
        return this.fmt(this.state.data.total[key], kind);
    }

    cellClass(key, row) {
        const v = row[key];
        const cls = [`o_cst_pf_${FIGURES.find((f) => f[0] === key)[3]}`];
        if (["profit", "markup", "margin"].includes(key) && typeof v === "number" && v < 0) {
            cls.push("text-danger");
        }
        if (key === "profit") {
            cls.push("fw-bold");
        }
        return cls.join(" ");
    }

    async openRow(row) {
        if (!row.order_ids.length) {
            return;
        }
        const action = await this.orm.call("cst.profitability.report", "action_open_orders", [
            row.order_ids,
            row.char ? `${row.name} ${row.char}` : row.name,
        ]);
        this.action.doAction(action);
    }

    exportXlsx() {
        const url = `/cst_reports/profitability/xlsx?options=${encodeURIComponent(JSON.stringify(this.options))}`;
        this.action.doAction({ type: "ir.actions.act_url", url, target: "download" });
    }
}

registry.category("actions").add("cst_profitability", Profitability);
