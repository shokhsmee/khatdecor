/** @odoo-module **/

import { Component, onWillStart, useState, useRef, markup } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { cookie } from "@web/core/browser/cookie";
import { _t } from "@web/core/l10n/translation";

// ---------------------------------------------------------------- numbers
/** 50 100 000 → "50,1 mln"; 3 100 → "3 100"; 950 → "950".
 *
 *  Since the books moved to USD the amounts are small, and rounding to whole
 *  thousands («3 ming» for 3 100, «1 ming» for 1 105) hid the part that
 *  matters.  Below a million the number is shown in full. */
export function compact(value) {
    const v = value || 0;
    const a = Math.abs(v);
    const sign = v < 0 ? "−" : "";
    const trim = (s) => s.replace(/\.?0+$/, "").replace(".", ",");
    if (a >= 1e9) return `${sign}${trim((a / 1e9).toFixed(2))} mlrd`;
    if (a >= 1e6) return `${sign}${trim((a / 1e6).toFixed(2))} mln`;
    return `${sign}${full(a)}`;
}
export function full(value) {
    return (value || 0).toLocaleString("ru-RU", { maximumFractionDigits: 0 });
}
function pct(p) {
    return p === null || p === undefined ? null : `${Math.abs(p).toFixed(0).replace(".", ",")}%`;
}
function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function niceTicks(vmax, n = 4) {
    if (vmax <= 0) return [0, 1];
    const raw = vmax / n;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    let step = raw / mag;
    step = (step <= 1 ? 1 : step <= 2 ? 2 : step <= 5 ? 5 : 10) * mag;
    const top = step * Math.ceil(vmax / step);
    const out = [];
    for (let t = 0; t <= top + 1e-9; t += step) out.push(t);
    return out;
}

// ---------------------------------------------------------------- SVG marks
/** Vertical bar with a 4px rounded data-end and a square baseline. */
function vbar(x, y0, y1, w, cls) {
    const r = Math.min(4, w / 2, Math.abs(y1 - y0));
    const f = (n) => n.toFixed(1);
    if (y1 <= y0) {
        return `<path class="${cls}" d="M${f(x)},${f(y0)} V${f(y1 + r)} Q${f(x)},${f(y1)} ${f(x + r)},${f(y1)} H${f(x + w - r)} Q${f(x + w)},${f(y1)} ${f(x + w)},${f(y1 + r)} V${f(y0)} Z"/>`;
    }
    return `<path class="${cls}" d="M${f(x)},${f(y0)} V${f(y1 - r)} Q${f(x)},${f(y1)} ${f(x + r)},${f(y1)} H${f(x + w - r)} Q${f(x + w)},${f(y1)} ${f(x + w)},${f(y1 - r)} V${f(y0)} Z"/>`;
}
/** Horizontal bar, rounded at the data end. */
function hbar(x, yc, len, thick, cls) {
    const r = Math.min(4, thick / 2, len);
    const f = (n) => n.toFixed(1);
    const t = thick / 2;
    return `<path class="${cls}" d="M${f(x)},${f(yc - t)} H${f(x + len - r)} Q${f(x + len)},${f(yc - t)} ${f(x + len)},${f(yc - t + r)} V${f(yc + t - r)} Q${f(x + len)},${f(yc + t)} ${f(x + len - r)},${f(yc + t)} H${f(x)} Z"/>`;
}

/**
 * «Rahbar oynasi» — the company's money at a glance.
 *
 * One hero figure (the cash position), the cash history as a line, a row of
 * stat tiles with deltas against last month, then the detail: daily in/out,
 * expenses by group, debtors and the age of the debt, sellers, products,
 * companies. Every chart has a table twin, every card opens the detail.
 * Charts are inline SVG so the marks follow the house rules exactly: 2px
 * lines, thin bars with rounded data-ends, hairline gridlines, crosshair
 * tooltips that read every series at once.
 */
export class DirectorDashboard extends Component {
    static template = "cst_kerama_reports.DirectorDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.compact = compact;
        this.full = full;
        this.pct = pct;
        this.markup = markup;
        this.dark = cookie.get("color_scheme") === "dark";
        this.cashWrap = useRef("cashWrap");
        this.flowWrap = useRef("flowWrap");
        this.state = useState({
            loading: true,
            busy: false,
            error: null,
            days: 30,
            companyIds: [],
            data: null,
            view: { cash: "chart", flow: "chart", expenses: "chart", debtors: "chart" },
            tip: null,
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.busy = true;
        this.state.error = null;
        try {
            const data = await this.orm.call("cst.director.dashboard", "get_data", [
                { days: this.state.days, company_ids: this.state.companyIds },
            ]);
            this.state.data = data;
            if (!this.state.companyIds.length) {
                this.state.companyIds = data.meta.selected_company_ids;
            }
        } catch (error) {
            this.state.error = error.data?.message || error.message || String(error);
        } finally {
            this.state.loading = false;
            this.state.busy = false;
        }
    }

    setDays(days) {
        if (this.state.days === days) return;
        this.state.days = days;
        this.load();
    }
    toggleCompany(id) {
        const ids = new Set(this.state.companyIds);
        if (ids.has(id)) {
            if (ids.size === 1) return;
            ids.delete(id);
        } else {
            ids.add(id);
        }
        this.state.companyIds = [...ids];
        this.load();
    }
    setView(key, mode) {
        this.state.view[key] = mode;
    }

    // ------------------------------------------------------------ derived
    get d() {
        return this.state.data;
    }
    get periodDelta() {
        const c = this.d.cash;
        const first = c.series.balance[0];
        const delta = c.period_delta;
        return {
            up: delta >= 0,
            text: first ? `${delta >= 0 ? "▲" : "▼"} ${pct((delta / Math.abs(first)) * 100)} · ${this.d.meta.days} kunda`
                        : `${delta >= 0 ? "+" : ""}${compact(delta)} · ${this.d.meta.days} kunda`,
        };
    }
    get agingTotal() {
        return this.d.debts.aging.reduce((s, a) => s + a.amount, 0) || 1;
    }
    get tiles() {
        const { meta, sales, expenses, debts, stock, production, payroll } = this.d;
        const cur = meta.currency;
        return [
            {
                key: "sales", label: `Savdo, ${meta.month_label}`, value: compact(sales.month.amount), unit: cur,
                delta: sales.delta_pct, upGood: true, spark: sales.series,
                sub: `${sales.month.count} buyurtma · o'tgan oy ${compact(sales.prev_month.amount)}`,
                action: () => this.action.doAction("sale.action_order_report_all"),
            },
            {
                key: "expenses", label: `Xarajat, ${meta.month_label}`, value: compact(expenses.month), unit: cur,
                delta: expenses.delta_pct, upGood: false, spark: expenses.series,
                sub: `o'tgan oy ${compact(expenses.prev_month)}`,
                action: () => this.action.doAction("cst_kerama_reports.action_expense_report_all"),
            },
            {
                key: "receivable", label: "Mijozlar qarzi (haqqimiz)", value: compact(debts.receivable), unit: cur,
                sub: `muddati o'tgan ${compact(debts.overdue)} · ${debts.overdue_count} hujjat`,
                action: () => this.action.doAction("account_reports.action_account_report_ar"),
            },
            {
                key: "payable", label: "Ta'minotchi qarzi (qarzimiz)", value: compact(debts.payable), unit: cur,
                sub: "kreditorlik qoldig'i",
                action: () => this.action.doAction("account_reports.action_account_report_ap"),
            },
            {
                key: "stock", label: "Ombor qiymati", value: compact(stock.value), unit: cur,
                sub: `kam qolgan ${stock.low_stock} · chiqarildi ${compact(stock.writeoff_month_value)}`,
                action: () => this.action.doAction("cst_kerama_reports.action_stock_ledger_report"),
            },
            {
                key: "production", label: `Ishlab chiqarish, ${meta.month_label}`, value: String(production.month.count), unit: "buyurtma",
                sub: `${full(production.month.qty)} dona · jarayonda ${production.in_progress}`,
                action: () => this.action.doAction("mrp.mrp_production_action"),
            },
            {
                key: "payroll", label: "Xodimlarga qarz (oylik)", value: compact(payroll.owed), unit: cur,
                sub: `bu oy hisoblandi ${compact(payroll.month_accrued)}`,
                action: () => this.action.doAction("cst_kerama_payroll.action_payroll_report"),
            },
        ];
    }

    // ------------------------------------------------------------ SVG
    sparkline(values) {
        const w = 64, h = 26;
        if (!values || values.length < 2 || Math.max(...values) === Math.min(...values)) {
            return markup(`<svg class="cst_dd_tile_spark" width="${w}" height="${h}"><path class="line" d="M1,${h / 2} H${w - 1}"/></svg>`);
        }
        const min = Math.min(...values), max = Math.max(...values);
        const x = (i) => 1 + ((w - 2) * i) / (values.length - 1);
        const y = (v) => h - 2 - ((h - 4) * (v - min)) / (max - min);
        const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
        const [lx, ly] = pts[pts.length - 1].split(",");
        return markup(`<svg class="cst_dd_tile_spark" width="${w}" height="${h}"><path class="line" d="M${pts.slice(0, -1).join(" L")}"/><path class="last" d="M${pts[pts.length - 2]} L${pts[pts.length - 1]}"/><circle cx="${lx}" cy="${ly}" r="3"/></svg>`);
    }

    /** geometry shared by the cash line and its crosshair */
    get cashGeom() {
        const s = this.d.cash.series;
        const w = 860, h = 230, padL = 60, padR = 78, padT = 12, padB = 26;
        const iw = w - padL - padR, ih = h - padT - padB;
        const vmin = Math.min(0, ...s.balance), vmax = Math.max(0, ...s.balance);
        const ticks = niceTicks(vmax);
        const top = ticks[ticks.length - 1] || 1;
        const n = s.balance.length;
        return {
            w, h, padL, padR, padT, padB, iw, ih, vmin, top, ticks, n,
            x: (i) => padL + (iw * i) / Math.max(n - 1, 1),
            y: (v) => padT + ih - (ih * (v - vmin)) / (top - vmin || 1),
        };
    }
    get cashChart() {
        const s = this.d.cash.series;
        const g = this.cashGeom;
        const out = [`<svg class="cst_dd_chart" viewBox="0 0 ${g.w} ${g.h}" preserveAspectRatio="none" style="height:${g.h}px">`];
        for (const t of g.ticks) {
            out.push(`<line class="grid" x1="${g.padL}" x2="${g.w - g.padR}" y1="${g.y(t).toFixed(1)}" y2="${g.y(t).toFixed(1)}"/>`);
            out.push(`<text class="tick" x="${g.padL - 8}" y="${g.y(t).toFixed(1)}" dy="4" text-anchor="end">${compact(t)}</text>`);
        }
        out.push(`<line class="axis" x1="${g.padL}" x2="${g.w - g.padR}" y1="${g.y(g.vmin).toFixed(1)}" y2="${g.y(g.vmin).toFixed(1)}"/>`);
        const pts = s.balance.map((v, i) => `${g.x(i).toFixed(1)},${g.y(v).toFixed(1)}`);
        out.push(`<path class="wash" d="M${g.x(0).toFixed(1)},${g.y(g.vmin).toFixed(1)} L${pts.join(" L")} L${g.x(g.n - 1).toFixed(1)},${g.y(g.vmin).toFixed(1)} Z"/>`);
        out.push(`<polyline class="line" points="${pts.join(" ")}"/>`);
        const step = Math.max(1, Math.floor(g.n / 6));
        for (let i = 0; i < g.n; i += step) {
            out.push(`<text class="tick" x="${g.x(i).toFixed(1)}" y="${g.h - 8}" text-anchor="middle">${esc(s.labels[i])}</text>`);
        }
        const last = s.balance[g.n - 1];
        out.push(`<circle class="dot" cx="${g.x(g.n - 1).toFixed(1)}" cy="${g.y(last).toFixed(1)}" r="4.5"/>`);
        out.push(`<text class="end_label" x="${(g.x(g.n - 1) + 10).toFixed(1)}" y="${g.y(last).toFixed(1)}" dy="4">${compact(last)}</text>`);
        const tip = this.state.tip;
        if (tip && tip.chart === "cash") {
            out.push(`<line class="cross" x1="${g.x(tip.i).toFixed(1)}" x2="${g.x(tip.i).toFixed(1)}" y1="${g.padT}" y2="${g.padT + g.ih}"/>`);
            out.push(`<circle class="dot" cx="${g.x(tip.i).toFixed(1)}" cy="${g.y(s.balance[tip.i]).toFixed(1)}" r="4.5"/>`);
        }
        out.push("</svg>");
        return markup(out.join(""));
    }

    get flowGeom() {
        const s = this.d.cash.series;
        const w = 860, h = 220, padL = 72, padR = 16, padT = 10, padB = 26;
        const iw = w - padL - padR, ih = h - padT - padB;
        const up = niceTicks(Math.max(1, ...s.inflow), 3);
        const dn = niceTicks(Math.max(0, ...s.outflow), 2);
        const upMax = up[up.length - 1], dnMax = Math.max(...s.outflow) > 0 ? dn[dn.length - 1] : 0;
        const scale = ih / (upMax + dnMax || 1);
        const y0 = padT + upMax * scale;
        const n = s.labels.length, slot = iw / n;
        return { w, h, padL, padR, padT, padB, iw, ih, up, dn, upMax, dnMax, y0, n, slot,
                 bw: Math.min(14, Math.max(2, slot - 2)), y: (v) => y0 - v * scale,
                 x: (i) => padL + slot * i + slot / 2 };
    }
    get flowChart() {
        const s = this.d.cash.series;
        const g = this.flowGeom;
        const out = [`<svg class="cst_dd_chart" viewBox="0 0 ${g.w} ${g.h}" preserveAspectRatio="none" style="height:${g.h}px">`];
        const f = (n) => n.toFixed(1);
        let lastTickY = -99;
        for (const t of g.up.slice(1)) {
            out.push(`<line class="grid" x1="${g.padL}" x2="${g.w - g.padR}" y1="${f(g.y(t))}" y2="${f(g.y(t))}"/><text class="tick" x="${g.padL - 8}" y="${f(g.y(t))}" dy="4" text-anchor="end">${compact(t)}</text>`);
        }
        if (g.dnMax) {
            for (const t of g.dn.slice(1)) {
                const yy = g.y(-t);
                out.push(`<line class="grid" x1="${g.padL}" x2="${g.w - g.padR}" y1="${f(yy)}" y2="${f(yy)}"/>`);
                if (yy - g.y0 > 14 && yy - lastTickY > 14) {  // never on top of the zero tick
                    out.push(`<text class="tick" x="${g.padL - 8}" y="${f(yy)}" dy="4" text-anchor="end">−${compact(t)}</text>`);
                    lastTickY = yy;
                }
            }
        }
        out.push(`<line class="axis" x1="${g.padL}" x2="${g.w - g.padR}" y1="${f(g.y0)}" y2="${f(g.y0)}"/>`);
        out.push(`<text class="tick" x="${g.padL - 8}" y="${f(g.y0)}" dy="4" text-anchor="end">0</text>`);
        const tip = this.state.tip;
        for (let i = 0; i < g.n; i++) {
            const x = g.x(i) - g.bw / 2;
            const hot = tip && tip.chart === "flow" && tip.i === i ? " hot" : "";
            if (s.inflow[i]) out.push(vbar(x, g.y0 - 1, g.y(s.inflow[i]), g.bw, "bar_in" + hot));
            if (s.outflow[i]) out.push(vbar(x, g.y0 + 1, g.y(-s.outflow[i]), g.bw, "bar_out" + hot));
        }
        const step = Math.max(1, Math.floor(g.n / 6));
        for (let i = 0; i < g.n; i += step) {
            out.push(`<text class="tick" x="${f(g.x(i))}" y="${g.h - 8}" text-anchor="middle">${esc(s.labels[i])}</text>`);
        }
        if (tip && tip.chart === "flow") {
            out.push(`<line class="cross" x1="${f(g.x(tip.i))}" x2="${f(g.x(tip.i))}" y1="${g.padT}" y2="${g.padT + g.ih}"/>`);
        }
        out.push("</svg>");
        return markup(out.join(""));
    }

    hbars(rows, cls = "bar") {
        if (!rows || !rows.length) return null;
        const w = 420, labelW = 150, rowH = 28;
        const h = rowH * rows.length + 4;
        const vmax = Math.max(...rows.map((r) => r.amount)) || 1;
        const barW = w - labelW - 90;
        const out = [`<svg class="cst_dd_chart" viewBox="0 0 ${w} ${h}" style="height:${h}px">`];
        rows.forEach((r, i) => {
            const y = 2 + i * rowH + rowH / 2;
            const len = Math.max(2, (barW * r.amount) / vmax);
            const name = r.name.length > 22 ? r.name.slice(0, 21) + "…" : r.name;
            out.push(`<g class="cst_dd_row" data-i="${i}"><title>${esc(r.name)}: ${esc(full(r.amount))}</title>`);
            out.push(`<rect class="hit" x="0" y="${(y - rowH / 2).toFixed(1)}" width="${w}" height="${rowH}"/>`);
            out.push(`<text class="cat_label" x="0" y="${y.toFixed(1)}" dy="4">${esc(name)}</text>`);
            out.push(hbar(labelW, y, len, 12, cls));
            out.push(`<text class="bar_label" x="${(labelW + len + 8).toFixed(1)}" y="${y.toFixed(1)}" dy="4">${compact(r.amount)}</text></g>`);
        });
        out.push("</svg>");
        return markup(out.join(""));
    }
    get expenseBars() { return this.hbars(this.d.expenses.by_group); }
    get debtorBars() { return this.hbars(this.d.debts.top_debtors); }

    // ------------------------------------------------------------ hover
    _index(ev, wrapRef, geom) {
        const svg = wrapRef.el && wrapRef.el.querySelector("svg");
        if (!svg) return null;
        const rect = svg.getBoundingClientRect();
        const vx = ((ev.clientX - rect.left) / rect.width) * geom.w;
        const rel = (vx - geom.padL) / geom.iw;
        return { i: Math.max(0, Math.min(geom.n - 1, Math.round(rel * (geom.n - 1)))), rect };
    }
    onCashMove(ev) {
        const hit = this._index(ev, this.cashWrap, this.cashGeom);
        if (!hit) return;
        const s = this.d.cash.series;
        const i = hit.i;
        this.state.tip = {
            chart: "cash", i,
            x: ev.clientX - hit.rect.left + 12, y: ev.clientY - hit.rect.top - 10,
            title: s.labels[i], rows: [
                { k: "series", label: "Qoldiq", v: full(s.balance[i]) },
                { k: "in", label: "Kirim", v: full(s.inflow[i]) },
                { k: "out", label: "Chiqim", v: full(s.outflow[i]) },
            ],
        };
    }
    onFlowMove(ev) {
        const g = this.flowGeom;
        const svg = this.flowWrap.el && this.flowWrap.el.querySelector("svg");
        if (!svg) return;
        const rect = svg.getBoundingClientRect();
        const vx = ((ev.clientX - rect.left) / rect.width) * g.w;
        const i = Math.max(0, Math.min(g.n - 1, Math.floor((vx - g.padL) / g.slot)));
        const s = this.d.cash.series;
        this.state.tip = {
            chart: "flow", i,
            x: ev.clientX - rect.left + 12, y: ev.clientY - rect.top - 10,
            title: s.labels[i], rows: [
                { k: "in", label: "Kirim", v: full(s.inflow[i]) },
                { k: "out", label: "Chiqim", v: full(s.outflow[i]) },
                { k: "series", label: "Sof", v: full(s.inflow[i] - s.outflow[i]) },
            ],
        };
    }
    onLeave() {
        this.state.tip = null;
    }

    // ------------------------------------------------------------ drill-downs
    openCashReport() {
        this.action.doAction("cst_kerama_reports.action_cash_report");
    }
    openJournal(box) {
        this.action.doAction({
            type: "ir.actions.act_window", name: box.name, res_model: "account.move.line",
            view_mode: "list", views: [[false, "list"]],
            domain: [["journal_id", "=", box.id], ["parent_state", "=", "posted"]],
            context: { search_default_group_by_date: 1 },
        });
    }
    openReceivables() { this.action.doAction("account_reports.action_account_report_ar"); }
    openOverdue() {
        this.action.doAction({
            type: "ir.actions.act_window", name: _t("Muddati o'tgan buyurtmalar"),
            res_model: "sale.order", view_mode: "list,form", views: [[false, "list"], [false, "form"]],
            domain: [["id", "in", this.d.debts.overdue_order_ids || []]],
        });
    }
    async openDebtor(debtor) {
        const action = await this.orm.call("res.partner", "action_cst_akt_sverka", [[debtor.id]]);
        this.action.doAction(action);
    }
    openProduct(p) {
        this.action.doAction({ type: "ir.actions.act_window", res_model: "product.product", res_id: p.id,
                               view_mode: "form", views: [[false, "form"]] });
    }
    openSellers() { this.action.doAction("sale.action_order_report_salesperson"); }
    openExpenseReport() { this.action.doAction("cst_kerama_reports.action_expense_report_all"); }
    openSales() { this.action.doAction("sale.action_order_report_all"); }
}

registry.category("actions").add("cst_reports_director_dashboard", DirectorDashboard);
