/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { ChartRenderer } from "./chart_renderer";
import { FilterBar } from "./filter_bar";
import { KpiCard } from "./kpi_card";

const PALETTE = {
    UZS: "#017e84",
    USD: "#2e7d32",
    primary: "#714B67",
    bars: [
        "#714B67", "#017e84", "#f0ad4e", "#d9534f", "#5bc0de",
        "#5cb85c", "#9b59b6", "#34495e", "#e67e22", "#1abc9c",
    ],
};

const TAB_LABELS = {
    sales: "Sales",
    accounting: "Accounting",
    debts: "Debts",
    inventory: "Inventory",
    stock: "Stock",
};

function isoDate(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
        d.getDate()
    ).padStart(2, "0")}`;
}

function defaultFilters() {
    const today = new Date();
    const first = new Date(today.getFullYear(), today.getMonth(), 1);
    return {
        date_from: isoDate(first),
        date_to: isoDate(today),
        so_search: "",
        salesperson_id: false,
        journal_id: false,
        so_id: false,
        warehouse_id: false,
        partner_search: "",
        product_search: "",
        currency: "all",
        company_ids: [],
    };
}

const FILTER_FIELDS = {
    sales: ["date", "so", "salesperson", "client", "currency", "company"],
    accounting: ["date", "journal", "salesperson", "client", "so", "currency", "company"],
    debts: ["date", "so_select", "client", "currency", "company"],
    inventory: ["date", "warehouse", "company"],
    stock: ["product", "warehouse", "company"],
};

export class KeramaDashboard extends Component {
    static template = "cst_kerama_dashboard.Dashboard";
    static components = { KpiCard, ChartRenderer, FilterBar };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        const ctx = (this.props.action && this.props.action.context) || {};
        this.state = useState({
            tab: ctx.default_tab || "sales",
            loading: true,
            filters: defaultFilters(),
            options: { salespersons: [], companies: [] },
            data: null,
        });
        onWillStart(async () => {
            this.state.options = await this.orm.call(
                "kerama.dashboard", "get_filter_options", []
            );
            this.state.filters.company_ids = this.defaultCompanyIds();
            await this.load();
        });
    }

    /**
     * Default company scope for the current tab. The Stock list starts on the
     * user's active company only (current_company_id); every other tab spans
     * all accessible companies. The user can still tick/untick from there.
     */
    defaultCompanyIds() {
        const all = this.state.options.companies.map((c) => c.id);
        if (this.state.tab === "stock") {
            const cur = this.state.options.current_company_id;
            return all.includes(cur) ? [cur] : all;
        }
        return all;
    }

    /**
     * Translate a literal label. Kept as a thin wrapper so KPI card titles and
     * other inline strings can be translated from the QWeb template, where the
     * module-scoped `_t` is not directly available.
     */
    t(label) {
        return _t(label);
    }

    get tabLabel() {
        return _t(TAB_LABELS[this.state.tab]);
    }

    get filterFields() {
        return FILTER_FIELDS[this.state.tab] || ["date", "company"];
    }

    formatMoney(amount, currency) {
        const text = new Intl.NumberFormat(undefined, {
            maximumFractionDigits: 2,
        }).format(amount || 0);
        return currency ? `${text} ${currency}` : text;
    }

    async load() {
        this.state.loading = true;
        try {
            if (this.state.tab === "sales") {
                this.state.data = await this.orm.call(
                    "kerama.dashboard", "get_sales_data", [this.state.filters]
                );
            } else if (this.state.tab === "accounting") {
                this.state.data = await this.orm.call(
                    "kerama.dashboard", "get_accounting_data", [this.state.filters]
                );
            } else if (this.state.tab === "debts") {
                this.state.data = await this.orm.call(
                    "kerama.dashboard", "get_debts_data", [this.state.filters]
                );
                this.state.options.debt_orders = this.state.data.debt_orders;
            } else if (this.state.tab === "inventory") {
                this.state.data = await this.orm.call(
                    "kerama.dashboard", "get_inventory_data", [this.state.filters]
                );
            } else if (this.state.tab === "stock") {
                this.state.data = await this.orm.call(
                    "kerama.dashboard", "get_stock_data", [this.state.filters]
                );
            }
        } finally {
            this.state.loading = false;
        }
    }

    async onFiltersChange(newFilters) {
        Object.assign(this.state.filters, newFilters);
        await this.load();
    }

    async onReset() {
        const reset = defaultFilters();
        reset.company_ids = this.defaultCompanyIds();
        Object.assign(this.state.filters, reset);
        await this.load();
    }

    // ------------------------------------------------------------------
    // Chart.js config builders (recomputed when state.data changes)
    // ------------------------------------------------------------------
    _palette(n) {
        return Array.from({ length: n }, (_, i) => PALETTE.bars[i % PALETTE.bars.length]);
    }

    get salesOverTimeConfig() {
        const d = this.state.data && this.state.data.charts.sales_over_time;
        if (!d || !d.labels.length) {
            return null;
        }
        return {
            type: "line",
            data: {
                labels: d.labels,
                datasets: d.series.map((s) => ({
                    label: s.currency,
                    data: s.data,
                    borderColor: PALETTE[s.currency] || PALETTE.primary,
                    backgroundColor: (PALETTE[s.currency] || PALETTE.primary) + "22",
                    tension: 0.3,
                    fill: true,
                    yAxisID: s.currency === "USD" ? "y1" : "y",
                })),
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: { legend: { position: "bottom" } },
                scales: {
                    y: { type: "linear", position: "left", title: { display: true, text: "UZS" } },
                    y1: {
                        type: "linear", position: "right",
                        title: { display: true, text: "USD" },
                        grid: { drawOnChartArea: false },
                    },
                },
            },
        };
    }

    _horizontalBar(rows, color) {
        if (!rows || !rows.length) {
            return null;
        }
        return {
            type: "bar",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [{ data: rows.map((r) => r.value), backgroundColor: color }],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
            },
        };
    }

    get topCustomersConfig() {
        return this._horizontalBar(
            this.state.data && this.state.data.charts.top_customers, PALETTE.bars[0]
        );
    }

    get topProductsConfig() {
        return this._horizontalBar(
            this.state.data && this.state.data.charts.top_products, PALETTE.bars[1]
        );
    }

    _doughnut(rows, colors) {
        if (!rows || !rows.length) {
            return null;
        }
        return {
            type: "doughnut",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [{ data: rows.map((r) => r.value), backgroundColor: colors }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "right" } },
            },
        };
    }

    get bySalespersonConfig() {
        const rows = this.state.data && this.state.data.charts.by_salesperson;
        return this._doughnut(rows, this._palette((rows || []).length));
    }

    get byCurrencyConfig() {
        const rows = this.state.data && this.state.data.charts.by_currency;
        return this._doughnut(
            rows, (rows || []).map((r) => PALETTE[r.label] || PALETTE.primary)
        );
    }

    get salesByCompanyConfig() {
        const d = this.state.data && this.state.data.charts.by_company;
        if (!d || !d.labels.length) {
            return null;
        }
        return {
            type: "bar",
            data: {
                labels: d.labels,
                datasets: d.series.map((s) => ({
                    label: s.currency,
                    data: s.data,
                    backgroundColor: PALETTE[s.currency] || PALETTE.primary,
                    borderRadius: 4,
                })),
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "bottom" } },
            },
        };
    }

    // ---- Accounting tab ----
    get flowOverTimeConfig() {
        const d = this.state.data && this.state.data.charts.flow_over_time;
        if (!d || !d.labels.length) {
            return null;
        }
        const colors = { Sales: "#017e84", Purchases: "#f0ad4e", Expenses: "#d9534f" };
        return {
            type: "line",
            data: {
                labels: d.labels,
                datasets: d.datasets.map((ds) => ({
                    label: ds.label,
                    data: ds.data,
                    borderColor: colors[ds.label] || PALETTE.primary,
                    backgroundColor: (colors[ds.label] || PALETTE.primary) + "22",
                    tension: 0.3,
                    fill: false,
                })),
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: { legend: { position: "bottom" } },
            },
        };
    }

    get paymentsByJournalConfig() {
        const rows = this.state.data && this.state.data.charts.payments_by_journal;
        return this._doughnut(rows, this._palette((rows || []).length));
    }

    get profitAndLossConfig() {
        const rows = this.state.data && this.state.data.charts.profit_and_loss;
        if (!rows || !rows.length) {
            return null;
        }
        const colorFor = (r) =>
            r.label === "Revenue" ? "#5cb85c"
                : r.label === "Expenses" ? "#d9534f"
                    : r.value >= 0 ? "#017e84" : "#d9534f";
        return {
            type: "bar",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [{
                    data: rows.map((r) => r.value),
                    backgroundColor: rows.map(colorFor),
                    borderRadius: 4,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
            },
        };
    }

    get cashInOutConfig() {
        const rows = this.state.data && this.state.data.charts.cash_in_out;
        return this._doughnut(rows, ["#5cb85c", "#d9534f"]);
    }

    get topExpensesConfig() {
        return this._horizontalBar(
            this.state.data && this.state.data.charts.top_expenses, "#d9534f"
        );
    }

    // ---- Debts tab ----
    get topDebtorsConfig() {
        return this._horizontalBar(
            this.state.data && this.state.data.charts.top_debtors, "#d9534f"
        );
    }

    get debtByCurrencyConfig() {
        const rows = this.state.data && this.state.data.charts.debt_by_currency;
        return this._doughnut(
            rows, (rows || []).map((r) => PALETTE[r.label] || PALETTE.primary)
        );
    }

    get agingConfig() {
        const rows = this.state.data && this.state.data.charts.aging;
        if (!rows || !rows.length) {
            return null;
        }
        return {
            type: "bar",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [{
                    data: rows.map((r) => r.value),
                    backgroundColor: ["#5cb85c", "#f0ad4e", "#e67e22", "#d9534f"],
                    borderRadius: 4,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
            },
        };
    }

    get debtOverTimeConfig() {
        const d = this.state.data && this.state.data.charts.over_time;
        if (!d || !d.labels.length) {
            return null;
        }
        return {
            type: "bar",
            data: {
                labels: d.labels,
                datasets: [{
                    label: "Debt",
                    data: d.data,
                    backgroundColor: "#714B67",
                    borderRadius: 4,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
            },
        };
    }

    // ---- Inventory tab ----
    get inventoryOps() {
        return (this.state.data && this.state.data.operations) || [];
    }

    opIcon(code) {
        return {
            incoming: "fa-arrow-circle-down",
            outgoing: "fa-arrow-circle-up",
            internal: "fa-exchange",
        }[code] || "fa-cubes";
    }

    opColor(code) {
        return {
            incoming: "#5cb85c",
            outgoing: "#714B67",
            internal: "#5bc0de",
        }[code] || "#714B67";
    }

    get movesOverTimeConfig() {
        const d = this.state.data && this.state.data.charts.moves_over_time;
        if (!d || !d.labels.length) {
            return null;
        }
        const colors = { In: "#5cb85c", Out: "#d9534f" };
        return {
            type: "bar",
            data: {
                labels: d.labels,
                datasets: d.datasets.map((ds) => ({
                    label: ds.label,
                    data: ds.data,
                    backgroundColor: colors[ds.label] || PALETTE.primary,
                    borderRadius: 4,
                })),
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "bottom" } },
            },
        };
    }

    get m2ByCategoryConfig() {
        const rows = this.state.data && this.state.data.charts.m2_by_category;
        return this._doughnut(rows, this._palette((rows || []).length));
    }

    get stockByWarehouseConfig() {
        return this._horizontalBar(
            this.state.data && this.state.data.charts.stock_by_warehouse, "#5bc0de"
        );
    }

    get topProductsQtyConfig() {
        return this._horizontalBar(
            this.state.data && this.state.data.charts.top_products_qty, "#017e84"
        );
    }

    get statusFunnelConfig() {
        const rows = this.state.data && this.state.data.charts.status_funnel;
        if (!rows || !rows.length) {
            return null;
        }
        return {
            type: "bar",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [{
                    data: rows.map((r) => r.value),
                    backgroundColor: [PALETTE.bars[4], PALETTE.bars[2], PALETTE.bars[5]],
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
            },
        };
    }
}

registry.category("actions").add("kerama_dashboard", KeramaDashboard);
