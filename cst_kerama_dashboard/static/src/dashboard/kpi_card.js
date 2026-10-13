/** @odoo-module **/

import { Component } from "@odoo/owl";

/**
 * A single KPI card. Either:
 *  - `values`: a {currency: amount} map -> renders one money line per currency, or
 *  - `value` (+ optional `suffix`): a single scalar (counts, m²...).
 */
export class KpiCard extends Component {
    static template = "cst_kerama_dashboard.KpiCard";
    static props = {
        title: { type: String },
        icon: { type: String, optional: true },
        color: { type: String, optional: true },
        values: { type: Object, optional: true },
        value: { type: [Number, String], optional: true },
        suffix: { type: String, optional: true },
        onClick: { type: Function, optional: true },
    };

    get lines() {
        const entries = Object.entries(this.props.values || {}).filter(
            ([, amount]) => amount
        );
        return entries.length ? entries : [["", 0]];
    }

    format(amount, currency) {
        const text = new Intl.NumberFormat(undefined, {
            maximumFractionDigits: 2,
        }).format(amount || 0);
        return currency ? `${text} ${currency}` : text;
    }
}
