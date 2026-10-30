/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/core/utils/numbers";
import { parseFloat } from "@web/views/fields/parsers";

/**
 * «KPI narxlari» — per department, what each worker earns for a shift whose
 * plan is met 100 %. A changed price is saved as a new row from its date, so
 * the shifts already closed keep the price of their own day.
 */
export class KpiPrices extends Component {
    static template = "cst_kerama_shift.KpiPrices";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            loading: true, busy: false, board: null, deptId: null,
            rows: [], history: {}, adding: false, query: "", options: [],
        });
        onWillStart(() => this.load());
    }

    async load(keepDept = true) {
        const board = await this.orm.call("cst.shift.kpi.price", "kpi_price_board", []);
        this.applyBoard(board, keepDept);
    }

    applyBoard(board, keepDept = true) {
        this.state.board = board;
        const ids = board.departments.map((d) => d.id);
        if (!keepDept || !ids.includes(this.state.deptId)) {
            this.state.deptId = ids.length ? ids[0] : null;
        }
        this.resetRows();
        this.state.loading = false;
    }

    resetRows() {
        const dept = this.department;
        this.state.rows = dept ? dept.rows.map((r) => ({
            ...r, input: r.amount ? this.fmt(r.amount) : "", newDate: this.defaultDate(r), dirty: false,
        })) : [];
        this.state.history = {};
        this.state.adding = false;
        this.state.query = "";
        this.state.options = [];
    }

    get department() {
        const board = this.state.board;
        return board && board.departments.find((d) => d.id === this.state.deptId);
    }
    get canEdit() { return this.state.board && this.state.board.can_edit; }
    get dirtyRows() { return this.state.rows.filter((r) => r.dirty); }

    fmt(value) { return formatFloat(value || 0, { digits: [16, 2] }); }
    /** A changed price counts from today; a worker's first price from the
     *  start of the month, so the shifts already closed this month get it. */
    defaultDate(row) {
        return row.date_from ? this.state.board.today : this.state.board.month_start;
    }
    fmtDate(value) {
        if (!value) return "—";
        const [y, m, d] = value.split("-");
        return `${d}.${m}.${y}`;
    }

    pickDepartment(id) {
        if (this.dirtyRows.length && !window.confirm("Saqlanmagan o'zgarishlar bor. Ular bekor qilinsinmi?")) {
            return;
        }
        this.state.deptId = id;
        this.resetRows();
    }

    onInput(row, ev) {
        row.input = ev.target.value;
        let value;
        try {
            value = parseFloat(row.input || "0");
        } catch {
            value = NaN;
        }
        row.value = value;
        row.dirty = !Number.isNaN(value) && Math.abs(value - (row.amount || 0)) > 0.0001;
        row.invalid = Number.isNaN(value) || value < 0;
    }
    onDate(row, ev) { row.newDate = ev.target.value; }

    async toggleHistory(row) {
        if (this.state.history[row.employee_id]) {
            delete this.state.history[row.employee_id];
            return;
        }
        this.state.history[row.employee_id] = await this.orm.call(
            "cst.shift.kpi.price", "kpi_price_history", [this.state.deptId, row.employee_id]);
    }
    async deleteHistory(row, item) {
        if (!window.confirm(`${this.fmtDate(item.date_from)} dagi ${this.fmt(item.amount)} narx o'chirilsinmi?`)) return;
        await this.orm.call("cst.shift.kpi.price", "kpi_price_delete", [item.id]);
        await this.load();
    }

    startAdd() {
        this.state.adding = true;
        this.searchPeople("");
    }
    async searchPeople(query) {
        this.state.query = query;
        const exclude = this.state.rows.map((r) => r.employee_id);
        this.state.options = await this.orm.call(
            "cst.shift.kpi.price", "kpi_price_employees", [this.state.deptId, query, exclude]);
    }
    addPerson(person) {
        this.state.rows.push({
            employee_id: person.id, name: person.name, amount: 0, date_from: false, history: 0, staff: false,
            input: "", newDate: this.state.board.month_start, dirty: false,
        });
        this.state.adding = false;
    }

    discard() { this.resetRows(); }

    async save() {
        const rows = this.dirtyRows;
        if (!rows.length || this.state.busy) return;
        if (rows.some((r) => r.invalid)) {
            this.notification.add("Narx noto'g'ri yozilgan (son, manfiy emas).", { type: "danger" });
            return;
        }
        this.state.busy = true;
        try {
            const board = await this.orm.call("cst.shift.kpi.price", "kpi_price_save", [this.state.deptId,
                rows.map((r) => ({ employee_id: r.employee_id, amount: r.value, date_from: r.newDate }))]);
            this.applyBoard(board);
            this.notification.add(`${rows.length} ta xodimning KPI narxi saqlandi.`, { type: "success" });
        } finally {
            this.state.busy = false;
        }
    }

    openFullHistory() {
        this.action.doAction("cst_kerama_shift.action_kpi_price_history", {
            additionalContext: { search_default_department_id: this.state.deptId },
        });
    }
}

registry.category("actions").add("cst_kpi_prices", KpiPrices);
