/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { download } from "@web/core/network/download";
import { _t } from "@web/core/l10n/translation";

/** First day of the month `offset` months from today, and its last day. */
function monthBounds(offset = 0) {
    const now = new Date();
    const from = new Date(now.getFullYear(), now.getMonth() + offset, 1);
    const to = new Date(now.getFullYear(), now.getMonth() + offset + 1, 0);
    return [from, to];
}

function iso(date) {
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${date.getFullYear()}-${month}-${day}`;
}

const PRESETS = [
    { key: "this_month", label: _t("Bu oy") },
    { key: "last_month", label: _t("O'tgan oy") },
    { key: "this_year", label: _t("Bu yil") },
    { key: "custom", label: _t("Boshqa") },
];

/**
 * «Ходимларга хисобланган иш хаки, бонуслар, жарималар ва берилган пуллар
 * буйича хисобот» — the running account the accounting department already
 * reads, with the one thing the workbook could never do: every figure opens.
 */
export class PayrollReport extends Component {
    static template = "cst_kerama_payroll.PayrollReport";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.presets = PRESETS;

        const [from, to] = monthBounds();
        this.state = useState({
            loading: true,
            error: null,
            preset: "this_month",
            dateFrom: iso(from),
            dateTo: iso(to),
            companyIds: (user.activeCompanies || []).map((company) => company.id),
            hideEmpty: true,
            includeDraft: false,
            search: "",
            data: null,
        });
        this.companies = user.allowedCompanies || [];

        onWillStart(() => this.load());
    }

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------
    get filters() {
        return {
            date_from: this.state.dateFrom,
            date_to: this.state.dateTo,
            company_ids: this.state.companyIds,
            hide_empty: this.state.hideEmpty,
            include_draft: this.state.includeDraft,
        };
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call(
                "cst.payroll.report", "get_report_data", [this.filters]);
        } catch (error) {
            this.state.error = (error && error.data && error.data.message) || String(error);
            this.state.data = null;
        } finally {
            this.state.loading = false;
        }
    }

    // ------------------------------------------------------------------
    // Filters
    // ------------------------------------------------------------------
    setPreset(key) {
        this.state.preset = key;
        if (key === "this_month" || key === "last_month") {
            const [from, to] = monthBounds(key === "this_month" ? 0 : -1);
            this.state.dateFrom = iso(from);
            this.state.dateTo = iso(to);
        } else if (key === "this_year") {
            const year = new Date().getFullYear();
            this.state.dateFrom = `${year}-01-01`;
            this.state.dateTo = `${year}-12-31`;
        }
        if (key !== "custom") {
            this.load();
        }
    }

    onDateChange(which, ev) {
        this.state[which] = ev.target.value;
        this.state.preset = "custom";
        if (this.state.dateFrom && this.state.dateTo) {
            this.load();
        }
    }

    toggleCompany(companyId) {
        const ids = this.state.companyIds;
        const next = ids.includes(companyId)
            ? ids.filter((id) => id !== companyId)
            : [...ids, companyId];
        // An empty selection would silently widen to every company; keep the
        // last one instead of surprising the user.
        this.state.companyIds = next.length ? next : ids;
        this.load();
    }

    toggle(flag) {
        this.state[flag] = !this.state[flag];
        this.load();
    }

    // ------------------------------------------------------------------
    // Rendering helpers
    // ------------------------------------------------------------------
    get columns() {
        return (this.state.data && this.state.data.columns) || { accruals: [], deductions: [] };
    }

    /** Total number of table columns, for colspans on the grouping rows. */
    get colCount() {
        return 4 + this.columns.accruals.length + this.columns.deductions.length + 2;
    }

    visibleRows(company) {
        const needle = this.state.search.trim().toLowerCase();
        if (!needle) {
            return company.rows;
        }
        return company.rows.filter((row) =>
            row.name.toLowerCase().includes(needle) ||
            (row.personnel_no || "").toLowerCase().includes(needle));
    }

    /** Blank for zero, grouped thousands otherwise — the workbook's habit. */
    /** ISO date to the dd.mm.yyyy the accountants read. */
    fmtDate(value) {
        if (!value) {
            return "";
        }
        const [year, month, day] = value.split("-");
        return `${day}.${month}.${year}`;
    }

    fmt(value) {
        if (!value || Math.abs(value) < 0.005) {
            return "";
        }
        return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value);
    }

    cls(value) {
        if (!value || Math.abs(value) < 0.005) {
            return "";
        }
        return value < 0 ? "o_kpr_neg" : "";
    }

    // ------------------------------------------------------------------
    // Drill-down and export
    // ------------------------------------------------------------------
    async openCell(employeeId, componentId, opening = false) {
        const action = await this.orm.call(
            "cst.payroll.report", "action_open_lines",
            [this.filters, employeeId, componentId || null, opening]);
        this.action.doAction(action);
    }

    exportXlsx() {
        download({
            url: "/cst_payroll/report/xlsx",
            data: { filters: JSON.stringify(this.filters) },
        });
    }
}

registry.category("actions").add("cst_payroll_report", PayrollReport);
