/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { ChartRenderer } from "@cst_kerama_dashboard/dashboard/chart_renderer";
import { openProjectMoDialog } from "@cst_kerama_project/mo_button/project_mo_button";

const C = {
    income: "#12a594",
    paid: "#22c55e",
    due: "#ef4444",
    purchases: "#f2a03d",
    expenses: "#8b5cf6",
    materials: "#3b82f6",
    manufacturing: "#3b82f6",
    margin: "#6366f1",
    grid: "rgba(128,128,128,.16)",
    wheel: ["#12a594", "#3b82f6", "#f2a03d", "#8b5cf6", "#ef4444", "#22c55e",
            "#6366f1", "#ec4899", "#14b8a6", "#f59e0b"],
};

const PERIODS = [
    { key: "all", label: _t("All") },
    { key: "month", label: _t("Month") },
    { key: "quarter", label: _t("Quarter") },
    { key: "year", label: _t("Year") },
    { key: "last12", label: _t("12 months") },
    { key: "custom", label: _t("Custom") },
];

const TABS = [
    { key: "sales", label: _t("Sales"), icon: "fa-shopping-bag", model: "sale.order" },
    { key: "purchases", label: _t("Purchases"), icon: "fa-shopping-cart", model: "purchase.order" },
    { key: "productions", label: _t("Manufacturing"), icon: "fa-wrench", model: "mrp.production" },
    { key: "expenses", label: _t("Expenses"), icon: "fa-money", model: "hr.expense" },
    { key: "materials", label: _t("Materials"), icon: "fa-cubes", model: null },
    { key: "mrfs", label: _t("Requests"), icon: "fa-file-text-o", model: "cst.material.request" },
];

/** Per-project analytics: sales, purchases, manufacturing and expenses in one place. */
export class ProjectHub extends Component {
    static template = "cst_kerama_project.ProjectHub";
    static components = { ChartRenderer };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.periods = PERIODS;
        this.tabs = TABS;

        const action = this.props.action || {};
        const fromAction =
            (action.params && action.params.project_id) ||
            (action.context && action.context.active_id);

        this.state = useState({
            loading: true,
            projectId: fromAction ? Number(fromAction) : null,
            projects: [],
            data: null,
            tab: "sales",
            search: "",
            sort: { key: null, asc: false },
            currencies: [],
            filters: {
                period: "all",
                date_from: "",
                date_to: "",
                include_draft: false,
                granularity: "month",
                currency_id: null,
            },
        });

        onWillStart(async () => {
            const [projects, currencies] = await Promise.all([
                this.orm.call("kerama.project.dashboard", "get_project_list", []),
                this.orm.call("kerama.project.dashboard", "get_currency_options", []),
            ]);
            this.state.projects = projects;
            this.state.currencies = currencies.currencies || [];
            if (!this.state.projectId && this.state.projects.length) {
                this.state.projectId = this.state.projects[0].id;
            }
            await this.load();
        });
    }

    async load() {
        if (!this.state.projectId) {
            this.state.loading = false;
            return;
        }
        this.state.loading = true;
        const filters = { ...this.state.filters };
        if (filters.period !== "custom") {
            delete filters.date_from;
            delete filters.date_to;
        }
        this.state.data = await this.orm.call(
            "kerama.project.dashboard",
            "get_project_detail",
            [this.state.projectId, filters]
        );
        this.state.loading = false;
    }

    // ------------------------------------------------------------------
    //  Filter handling
    // ------------------------------------------------------------------
    setPeriod(key) {
        this.state.filters.period = key;
        if (key !== "custom") {
            this.load();
        }
    }

    onDateChange(which, ev) {
        this.state.filters[which] = ev.target.value;
        if (this.state.filters.date_from && this.state.filters.date_to) {
            this.load();
        }
    }

    toggleDrafts() {
        this.state.filters.include_draft = !this.state.filters.include_draft;
        this.load();
    }

    setGranularity(value) {
        this.state.filters.granularity = value;
        this.load();
    }

    onProjectChange(ev) {
        this.state.projectId = Number(ev.target.value);
        this.state.search = "";
        // each project remembers the currency it is read in; let it speak again
        this.state.filters.currency_id = null;
        this.load();
    }

    /** Read every figure in another currency, converted at each document's date. */
    onCurrencyChange(ev) {
        const value = ev.target.value;
        this.state.filters.currency_id = value ? Number(value) : null;
        this.load();
    }

    get periodLabel() {
        const f = this.state.filters;
        if (f.period === "custom" && f.date_from && f.date_to) {
            return `${f.date_from} → ${f.date_to}`;
        }
        return (PERIODS.find((p) => p.key === f.period) || {}).label || "";
    }

    // ------------------------------------------------------------------
    //  Formatting
    // ------------------------------------------------------------------
    get currency() {
        return this.state.data ? this.state.data.currency : "";
    }

    /** The currency the figures are actually in, whatever the filter says. */
    get currencyId() {
        return this.state.data ? this.state.data.currency_id : null;
    }

    /** Short form for headline figures: 12.4M, 380k … */
    compact(amount) {
        const value = amount || 0;
        const abs = Math.abs(value);
        if (abs >= 1e9) return (value / 1e9).toFixed(2).replace(/\.?0+$/, "") + "B";
        if (abs >= 1e6) return (value / 1e6).toFixed(2).replace(/\.?0+$/, "") + "M";
        if (abs >= 1e3) return (value / 1e3).toFixed(1).replace(/\.?0+$/, "") + "k";
        return this.num(value);
    }

    num(value, digits = 0) {
        return new Intl.NumberFormat(undefined, {
            minimumFractionDigits: 0,
            maximumFractionDigits: digits,
        }).format(value || 0);
    }

    money(amount) {
        return `${this.num(amount, 2)} ${this.currency}`;
    }

    pct(value) {
        return `${(value || 0).toFixed(1)}%`;
    }

    /** Width for a meter bar, clamped to 0-100. */
    barWidth(value, total) {
        if (!total) return "0%";
        return `${Math.min(100, Math.max(0, (value / total) * 100))}%`;
    }

    stateClass(value) {
        const map = {
            sale: "ok", purchase: "ok", done: "ok", posted: "ok", paid: "ok",
            approved: "ok", progress: "run", to_close: "run", confirmed: "run",
            assigned: "run", purchased: "run", in_payment: "run", to_approve: "warn",
            reported: "warn", submitted: "warn", draft: "muted", sent: "muted",
            cancel: "bad", refused: "bad",
        };
        return `o_kph_pill o_kph_pill--${map[value] || "muted"}`;
    }

    // ------------------------------------------------------------------
    //  Tables
    // ------------------------------------------------------------------
    get tabCount() {
        const data = this.state.data;
        if (!data) return {};
        return {
            sales: data.sales.length,
            purchases: data.purchases.length,
            productions: data.productions.length,
            expenses: data.expenses.length,
            materials: data.materials.length,
            mrfs: data.mrfs.length,
        };
    }

    get rows() {
        const data = this.state.data;
        if (!data) return [];
        let rows = data[this.state.tab] || [];
        const term = this.state.search.trim().toLowerCase();
        if (term) {
            rows = rows.filter((row) =>
                Object.values(row).some(
                    (value) => typeof value === "string" && value.toLowerCase().includes(term)
                )
            );
        }
        const { key, asc } = this.state.sort;
        if (key) {
            rows = [...rows].sort((a, b) => {
                const x = a[key], y = b[key];
                if (typeof x === "number" && typeof y === "number") return asc ? x - y : y - x;
                return asc
                    ? String(x ?? "").localeCompare(String(y ?? ""))
                    : String(y ?? "").localeCompare(String(x ?? ""));
            });
        }
        return rows;
    }

    setTab(key) {
        this.state.tab = key;
        this.state.search = "";
        this.state.sort = { key: null, asc: false };
    }

    sortBy(key) {
        const sort = this.state.sort;
        this.state.sort = { key, asc: sort.key === key ? !sort.asc : false };
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
    }

    openRecord(model, resId) {
        if (!model || !resId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: resId,
            views: [[false, "form"]],
            target: "current",
            context: { from_project_action: true },
        });
    }

    openTabRecord(row) {
        const tab = TABS.find((t) => t.key === this.state.tab);
        if (tab && tab.model) {
            this.openRecord(tab.model, row.id);
        }
    }

    openProjectForm() {
        this.openRecord("project.project", this.state.projectId);
    }

    /** The same «Yangi buyurtma» dialog the Shop Floor uses, for this project. */
    newProduction() {
        openProjectMoDialog(this.dialog, this.state.projectId, {
            projectName: this.state.data && this.state.data.project ? this.state.data.project.name : "",
            onCreated: () => this.load(),
        });
    }

    async startManufacturing() {
        const action = await this.orm.call(
            "project.project", "action_cst_start_manufacturing", [[this.state.projectId]]);
        this.action.doAction(action, {
            onClose: () => this.load(),
        });
    }

    openList(model, domainField) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            domain: [[domainField, "=", this.state.projectId]],
            views: [[false, "list"], [false, "form"]],
            target: "current",
            context: { from_project_action: true },
        });
    }

    // ------------------------------------------------------------------
    //  Charts
    // ------------------------------------------------------------------
    get axisOptions() {
        return {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: "index" },
            plugins: {
                legend: {
                    position: "bottom",
                    labels: { usePointStyle: true, boxWidth: 8, padding: 16 },
                },
            },
            scales: {
                x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
                y: {
                    grid: { color: C.grid, drawBorder: false },
                    ticks: { callback: (v) => this.compact(v) },
                },
            },
        };
    }

    get flowConfig() {
        const data = this.state.data;
        if (!data || !data.over_time.labels.length) return null;
        return {
            type: "line",
            data: {
                labels: data.over_time.labels,
                datasets: [
                    {
                        label: _t("Income"),
                        data: data.over_time.income,
                        borderColor: C.income,
                        backgroundColor: C.income + "22",
                        borderWidth: 2,
                        fill: true,
                        tension: 0.35,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                    },
                    {
                        label: _t("Cost"),
                        data: data.over_time.cost,
                        borderColor: C.purchases,
                        backgroundColor: C.purchases + "1f",
                        borderWidth: 2,
                        fill: true,
                        tension: 0.35,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                    },
                ],
            },
            options: this.axisOptions,
        };
    }

    get costConfig() {
        const data = this.state.data;
        if (!data) return null;
        const values = [data.cost_split.materials, data.cost_split.expenses];
        if (!values.some((v) => v)) return null;
        return {
            type: "doughnut",
            data: {
                labels: [_t("Materials"), _t("Expenses")],
                datasets: [{
                    data: values,
                    backgroundColor: [C.materials, C.expenses],
                    borderWidth: 0,
                    hoverOffset: 6,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "68%",
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { usePointStyle: true, boxWidth: 8, padding: 16 },
                    },
                },
            },
        };
    }

    get moConfig() {
        const data = this.state.data;
        const entries = Object.entries(data ? data.mo_by_state : {});
        if (!entries.length) return null;
        return {
            type: "doughnut",
            data: {
                labels: entries.map(([label]) => label),
                datasets: [{
                    data: entries.map(([, count]) => count),
                    backgroundColor: C.wheel.slice(0, entries.length),
                    borderWidth: 0,
                    hoverOffset: 6,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "68%",
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { usePointStyle: true, boxWidth: 8, padding: 16 },
                    },
                },
            },
        };
    }

    get materialsConfig() {
        const data = this.state.data;
        if (!data || !data.materials_used.length) return null;
        const top = data.materials_used.slice(0, 8);
        return {
            type: "bar",
            data: {
                labels: top.map((m) => m.name),
                datasets: [{
                    label: _t("Consumed value"),
                    data: top.map((m) => m.cost),
                    backgroundColor: C.manufacturing,
                    borderRadius: 6,
                    maxBarThickness: 22,
                }],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: {
                        grid: { color: C.grid, drawBorder: false },
                        ticks: { callback: (v) => this.compact(v) },
                    },
                    y: { grid: { display: false } },
                },
            },
        };
    }
}

registry.category("actions").add("kerama_project_hub", ProjectHub);
