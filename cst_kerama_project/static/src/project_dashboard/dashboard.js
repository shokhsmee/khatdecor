/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { KpiCard } from "@cst_kerama_dashboard/dashboard/kpi_card";
import { ChartRenderer } from "@cst_kerama_dashboard/dashboard/chart_renderer";

const PALETTE = {
    income: "#017e84",
    cost: "#d9534f",
    margin: "#714B67",
    paid: "#5cb85c",
    due: "#d9534f",
    purchases: "#f0ad4e",
    expenses: "#9b59b6",
    bars: [
        "#714B67", "#017e84", "#f0ad4e", "#d9534f", "#5bc0de",
        "#5cb85c", "#9b59b6", "#34495e", "#e67e22", "#1abc9c",
    ],
};

const PERIODS = [
    { key: "all", label: _t("All Time") },
    { key: "year", label: _t("This Year") },
    { key: "quarter", label: _t("This Quarter") },
    { key: "month", label: _t("This Month") },
];

/**
 * Khatdecor project dashboard: income (paid/due), purchases, expenses,
 * margin and MRF statistics across all projects.
 */
export class ProjectDashboard extends Component {
    static template = "cst_kerama_project.ProjectDashboard";
    static components = { KpiCard, ChartRenderer };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.periods = PERIODS;
        this.state = useState({
            loading: true, period: "all", data: null,
            currencies: [], currencyId: null,
        });
        onWillStart(async () => {
            const options = await this.orm.call(
                "kerama.project.dashboard", "get_currency_options", []
            );
            this.state.currencies = options.currencies || [];
            this.state.currencyId = options.company_currency_id || null;
            await this.load();
        });
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call(
            "kerama.project.dashboard",
            "get_project_overview",
            [{ period: this.state.period, currency_id: this.state.currencyId }]
        );
        this.state.loading = false;
    }

    setPeriod(period) {
        this.state.period = period;
        this.load();
    }

    /** Read every figure in another currency, converted at each document's date. */
    onCurrencyChange(ev) {
        const value = ev.target.value;
        this.state.currencyId = value ? Number(value) : null;
        this.load();
    }

    /** Wrap a scalar into the {currency: amount} map KpiCard expects. */
    money(amount) {
        const ccy = this.state.data ? this.state.data.currency : "";
        return { [ccy]: amount || 0 };
    }

    fmt(amount) {
        return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(
            amount || 0
        );
    }

    // ------------------------------------------------------------------
    //  Chart configs
    // ------------------------------------------------------------------
    get marginConfig() {
        const data = this.state.data;
        if (!data || !data.projects.length) {
            return null;
        }
        const top = data.projects.slice(0, 10);
        return {
            type: "bar",
            data: {
                labels: top.map((p) => p.name),
                datasets: [
                    { label: _t("Income"), backgroundColor: PALETTE.income, data: top.map((p) => p.income) },
                    { label: _t("Cost"), backgroundColor: PALETTE.cost, data: top.map((p) => p.purchases + p.expenses) },
                    { label: _t("Margin"), backgroundColor: PALETTE.margin, data: top.map((p) => p.margin) },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "bottom" } },
            },
        };
    }

    get overTimeConfig() {
        const data = this.state.data;
        if (!data || !data.over_time.labels.length) {
            return null;
        }
        return {
            type: "line",
            data: {
                labels: data.over_time.labels,
                datasets: [
                    {
                        label: _t("Income"),
                        borderColor: PALETTE.income,
                        backgroundColor: PALETTE.income + "33",
                        fill: true,
                        tension: 0.3,
                        data: data.over_time.income,
                    },
                    {
                        label: _t("Cost (purchases + expenses)"),
                        borderColor: PALETTE.cost,
                        backgroundColor: PALETTE.cost + "33",
                        fill: true,
                        tension: 0.3,
                        data: data.over_time.cost,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "bottom" } },
            },
        };
    }

    get costSplitConfig() {
        const data = this.state.data;
        if (!data || (!data.cost_split.purchases && !data.cost_split.expenses)) {
            return null;
        }
        return {
            type: "doughnut",
            data: {
                labels: [_t("Purchases"), _t("Expenses")],
                datasets: [{
                    data: [data.cost_split.purchases, data.cost_split.expenses],
                    backgroundColor: [PALETTE.purchases, PALETTE.expenses],
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "bottom" } },
            },
        };
    }

    get dueConfig() {
        const data = this.state.data;
        if (!data || !data.due_by_project.length) {
            return null;
        }
        return {
            type: "bar",
            data: {
                labels: data.due_by_project.map((r) => r.name),
                datasets: [{
                    label: _t("Amount Due"),
                    backgroundColor: PALETTE.due,
                    data: data.due_by_project.map((r) => r.due),
                }],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
            },
        };
    }

    get mrfConfig() {
        const data = this.state.data;
        const entries = Object.entries(data ? data.mrf_by_state : {});
        if (!entries.length) {
            return null;
        }
        return {
            type: "doughnut",
            data: {
                labels: entries.map(([label]) => label),
                datasets: [{
                    data: entries.map(([, count]) => count),
                    backgroundColor: PALETTE.bars.slice(0, entries.length),
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "bottom" } },
            },
        };
    }

    openProject(projectId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.project",
            res_id: projectId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("kerama_project_dashboard", ProjectDashboard);
