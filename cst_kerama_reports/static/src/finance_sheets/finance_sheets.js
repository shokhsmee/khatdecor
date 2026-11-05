/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/core/utils/numbers";

function iso(d) {
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function ddmmyyyy(value) {
    if (!value) {
        return "";
    }
    const [y, m, d] = value.split("-");
    return `${d}.${m}.${y}`;
}

/**
 * Period + company bar and the plumbing both sheets share; a subclass names
 * its model, its Excel URL and whether several companies may be picked.
 */
class FinanceSheetBase extends Component {
    static props = ["*"];
    static model = "";
    static xlsxUrl = "";
    static multiCompany = false;

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            dateFrom: "",
            dateTo: "",
            companyIds: [],
            companies: [],
            data: null,
            open: {},
            detailXlsx: false,
        });
        onWillStart(async () => {
            const d = await this.orm.call(this.constructor.model, "get_defaults", []);
            Object.assign(this.state, {
                dateFrom: d.date_from,
                dateTo: d.date_to,
                companyIds: d.company_ids,
                companies: d.companies,
            });
            await this.load();
        });
    }

    get options() {
        return { date_from: this.state.dateFrom, date_to: this.state.dateTo, company_ids: this.state.companyIds };
    }

    get multiCompany() {
        return this.constructor.multiCompany;
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call(this.constructor.model, "get_data", [this.options]);
        } finally {
            this.state.loading = false;
        }
    }

    setPeriod(kind) {
        const now = new Date();
        let from = new Date(now.getFullYear(), now.getMonth(), 1);
        let to = new Date(now);
        if (kind === "prev_month") {
            from = new Date(now.getFullYear(), now.getMonth() - 1, 1);
            to = new Date(now.getFullYear(), now.getMonth(), 0);
        } else if (kind === "quarter") {
            from = new Date(now.getFullYear(), Math.floor(now.getMonth() / 3) * 3, 1);
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

    toggleCompany(id) {
        if (!this.multiCompany) {
            this.state.companyIds = [id];
        } else if (this.state.companyIds.includes(id)) {
            if (this.state.companyIds.length === 1) {
                return;
            }
            this.state.companyIds = this.state.companyIds.filter((c) => c !== id);
        } else {
            this.state.companyIds = [...this.state.companyIds, id];
        }
        this.load();
    }

    toggle(key) {
        this.state.open[key] = !this.state.open[key];
    }

    expandAll(keys) {
        const allOpen = keys.every((k) => this.state.open[k]);
        for (const k of keys) {
            this.state.open[k] = !allOpen;
        }
    }

    fmt(value) {
        if (!value || Math.abs(value) < 0.005) {
            return "";
        }
        return formatFloat(value, { digits: [16, 2] });
    }

    ddmmyyyy(value) {
        return ddmmyyyy(value);
    }

    async openDoc(model, resId) {
        if (!model || !resId || model === "correction") {
            return;
        }
        const action = await this.orm.call("cst.balance.sheet", "action_open", [model, resId]);
        if (action) {
            this.action.doAction(action);
        }
    }

    exportXlsx() {
        const params = new URLSearchParams({
            options: JSON.stringify(this.options),
            detail: this.state.detailXlsx ? "1" : "0",
        });
        this.action.doAction({
            type: "ir.actions.act_url",
            url: `${this.constructor.xlsxUrl}?${params.toString()}`,
            target: "download",
        });
    }
}

/** «Foyda va zarar (Excel shakli)» — the company's 16-row P&L. */
export class PlSheet extends FinanceSheetBase {
    static template = "cst_kerama_reports.PlSheet";
    static model = "cst.pl.sheet";
    static xlsxUrl = "/cst_reports/pl_sheet/xlsx";
    static multiCompany = true;

    rowKey(block, row) {
        return `${block.id}_${row.key}`;
    }

    get allKeys() {
        const data = this.state.data;
        return data ? data.companies.flatMap((b) => b.rows.filter((r) => r.details.length).map((r) => this.rowKey(b, r))) : [];
    }
}

/** «Balans (Excel shakli)» — opening, turnover and closing per row. */
export class BalanceSheet extends FinanceSheetBase {
    static template = "cst_kerama_reports.BalanceSheet";
    static model = "cst.balance.sheet";
    static xlsxUrl = "/cst_reports/balance_sheet/xlsx";

    get allKeys() {
        const data = this.state.data;
        return data ? data.rows.filter((r) => r.details.length).map((r) => r.key) : [];
    }

    side(value, positive) {
        if (!value || Math.abs(value) < 0.005) {
            return "";
        }
        return (value > 0) === positive ? this.fmt(Math.abs(value)) : "";
    }

    openOdooBalance() {
        this.action.doAction("account_reports.action_account_report_bs");
    }
}

registry.category("actions").add("cst_pl_sheet", PlSheet);
registry.category("actions").add("cst_balance_sheet", BalanceSheet);
