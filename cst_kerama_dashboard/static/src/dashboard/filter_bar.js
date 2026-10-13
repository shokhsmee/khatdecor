/** @odoo-module **/

import { Component } from "@odoo/owl";

/**
 * Shared filter bar. Owns no state: it reads the current `filters` and emits a
 * new merged filters object through `onChange`. `options` carries the dropdown
 * data (salespersons, companies) loaded once by the parent.
 */
export class FilterBar extends Component {
    static template = "cst_kerama_dashboard.FilterBar";
    static props = {
        filters: { type: Object },
        options: { type: Object },
        onChange: { type: Function },
        onReset: { type: Function },
        fields: { type: Array, optional: true },
    };

    has(field) {
        return !this.props.fields || this.props.fields.includes(field);
    }

    update(key, value) {
        this.props.onChange({ ...this.props.filters, [key]: value });
    }

    onInput(ev, key) {
        this.update(key, ev.target.value);
    }

    onSalesperson(ev) {
        const val = ev.target.value;
        this.update("salesperson_id", val ? parseInt(val, 10) : false);
    }

    onJournal(ev) {
        const val = ev.target.value;
        this.update("journal_id", val ? parseInt(val, 10) : false);
    }

    onSaleOrder(ev) {
        const val = ev.target.value;
        this.update("so_id", val ? parseInt(val, 10) : false);
    }

    onWarehouse(ev) {
        const val = ev.target.value;
        this.update("warehouse_id", val ? parseInt(val, 10) : false);
    }

    get selectedCompanies() {
        return this.props.filters.company_ids || [];
    }

    toggleCompany(ev, companyId) {
        const current = this.selectedCompanies;
        const next = ev.target.checked
            ? [...current, companyId]
            : current.filter((id) => id !== companyId);
        this.update("company_ids", next);
    }
}
