import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { useBus, useService } from "@web/core/utils/hooks";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { formatFloat } from "@web/core/utils/numbers";

const MODEL = "cst.transfer.ui";

const STATUS = {
    new: { label: "Yangi", cls: "o_cst_tr_st_new" },
    sent: { label: "Jo'natildi", cls: "o_cst_tr_st_sent" },
    done: { label: "Qabul qilindi", cls: "o_cst_tr_st_done" },
    cancel: { label: "Bekor qilindi", cls: "o_cst_tr_st_cancel" },
};

export class TransferSection extends Component {
    static template = "cst_kerama_dispatch.TransferSection";
    static props = { onHome: Function, userName: { type: String, optional: true } };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.barcode = useService("barcode");
        this.cameraSupported = isBarcodeScannerSupported();
        this.state = useState({
            view: "list",
            filter: "all",
            search: "",
            f: { status: "", kind: "", src_wh: "", dest_wh: "", date_from: "", date_to: "" },
            warehouses: [],
            kinds: [],
            count: 0,
            limited: false,
            rows: [],
            toMe: 0,
            options: { locations: [], users: [], multi_company: false },
            t: null, // the transfer on screen
            productSearch: "",
            results: [],
            recent: { chips: [], repeat_id: false, repeat_name: "" },
            saving: "",
            busy: false,
        });
        this.timers = {};
        useBus(this.barcode.bus, "barcode_scanned", (ev) => this.onBarcode(ev.detail.barcode));
        onWillStart(async () => {
            this.state.options = await this.call("ui_options");
            await this.refresh();
        });
        onWillUnmount(() => Object.values(this.timers).forEach((t) => clearTimeout(t)));
    }

    // ------------------------------------------------------------ helpers
    async call(method, args = [], kwargs = {}) {
        this.state.busy = true;
        try {
            return await this.orm.call(MODEL, method, args, kwargs);
        } finally {
            this.state.busy = false;
        }
    }
    fmt(n) {
        return formatFloat(n || 0, { digits: [16, 3], trailingZeros: false });
    }
    status(code) {
        return STATUS[code] || STATUS.new;
    }
    debounce(key, fn, ms) {
        clearTimeout(this.timers[key]);
        this.timers[key] = setTimeout(fn, ms);
    }
    get t() {
        return this.state.t;
    }
    get editable() {
        return this.t && this.state.view === "edit";
    }
    get receiving() {
        return this.t && this.state.view === "view" && this.t.can_receive;
    }
    get srcOptions() {
        return this.state.options.locations.filter((l) => l.mine);
    }
    get destGroups() {
        const groups = {};
        for (const l of this.state.options.locations) {
            (groups[l.company] = groups[l.company] || []).push(l);
        }
        return Object.entries(groups).map(([company, locations]) => ({ company, locations }));
    }
    location(id) {
        return this.state.options.locations.find((l) => l.id === id);
    }
    get isIntercompany() {
        const src = this.location(this.t?.src_id);
        const dest = this.location(this.t?.dest_id);
        return Boolean(src && dest && src.company_id !== dest.company_id);
    }
    get receiverOptions() {
        const dest = this.location(this.t?.dest_id);
        const users = this.state.options.users;
        return dest ? users.filter((u) => u.company_ids.includes(dest.company_id)) : users;
    }
    get lineCount() {
        return (this.t?.lines || []).filter((l) => l.qty > 0).length;
    }
    get steps() {
        const order = ["new", "sent", "done"];
        const cur = order.indexOf(this.t?.status);
        return order.map((code, i) => ({
            code,
            label: STATUS[code].label,
            active: i === cur,
            passed: cur >= 0 && i < cur,
        }));
    }
    lineShort(l) {
        return this.editable && l.qty > l.onhand;
    }

    // ------------------------------------------------------------ list
    async refresh() {
        const f = this.state.f;
        const res = await this.call("ui_list", [], {
            filter: this.state.filter,
            search: this.state.search || null,
            status: f.status || null, kind: f.kind || null,
            src_wh: Number(f.src_wh) || null, dest_wh: Number(f.dest_wh) || null,
            date_from: f.date_from || null, date_to: f.date_to || null,
        });
        this.state.rows = res.rows;
        this.state.warehouses = res.warehouses || [];
        this.state.kinds = res.kinds || [];
        this.state.count = res.count || 0;
        this.state.limited = !!res.limited;
        this.state.toMe = res.to_me;
    }
    async setFilter(f) {
        this.state.filter = f;
        await this.refresh();
    }
    async setF(key, ev) {
        this.state.f[key] = ev.target.value;
        await this.refresh();
    }
    get hasF() {
        return Object.values(this.state.f).some(Boolean);
    }
    async clearF() {
        Object.assign(this.state.f, { status: "", kind: "", src_wh: "", dest_wh: "", date_from: "", date_to: "" });
        await this.refresh();
    }
    onSearch(ev) {
        this.state.search = ev.target.value;
        this.debounce("search", () => this.refresh(), 300);
    }
    async backToList() {
        await this.flush();
        this.state.view = "list";
        this.state.t = null;
        await this.refresh();
    }
    async back() {
        if (this.state.view === "list") {
            return this.props.onHome();
        }
        return this.backToList();
    }

    // ------------------------------------------------------------ open
    async newTransfer() {
        const src = this.srcOptions[0];
        this.state.t = {
            id: false,
            status: "new",
            src_id: src ? src.id : false,
            dest_id: false,
            receiver_id: false,
            note: "",
            lines: [],
            can_edit: true,
        };
        this.state.view = "edit";
        this.state.saving = "";
        this.state.results = [];
        this.state.productSearch = "";
        await this.loadRecent();
    }
    async open(row) {
        const data = await this.call("ui_load", [row.id]);
        this.state.t = data;
        this.state.view = data.can_edit ? "edit" : "view";
        this.state.saving = "";
        this.state.results = [];
        this.state.productSearch = "";
        if (data.can_edit) {
            await this.loadRecent();
        }
    }
    async loadRecent() {
        this.state.recent = await this.call("ui_recent", [], {
            src_id: this.t.src_id || null,
            dest_id: this.t.dest_id || null,
        });
    }

    // ------------------------------------------------------------ editing
    touch() {
        this.state.saving = "Saqlanmoqda…";
        this.debounce("save", () => this.save(), 700);
    }
    payload() {
        return {
            src_id: this.t.src_id,
            dest_id: this.t.dest_id,
            receiver_id: this.t.receiver_id,
            note: this.t.note,
            lines: this.t.lines.map((l) => ({ product_id: l.product_id, qty: l.qty })),
        };
    }
    async save() {
        clearTimeout(this.timers.save);
        if (!this.editable || !this.t.src_id) {
            this.state.saving = "";
            return;
        }
        try {
            this.t.id = await this.call("ui_save", [this.t.id || false, this.payload()]);
            this.state.saving = "Saqlandi";
        } catch (e) {
            this.state.saving = "";
            throw e;
        }
    }
    async flush() {
        if (this.timers.save && this.state.saving === "Saqlanmoqda…") {
            await this.save();
        }
    }
    async onSrc(ev) {
        this.t.src_id = parseInt(ev.target.value) || false;
        if (this.t.src_id === this.t.dest_id) {
            this.t.dest_id = false;
        }
        const ids = this.t.lines.map((l) => l.product_id);
        if (ids.length && this.t.src_id) {
            const onhand = await this.call("ui_onhand", [this.t.src_id, ids]);
            for (const l of this.t.lines) {
                l.onhand = onhand[l.product_id] || 0;
            }
        }
        this.touch();
        await this.loadRecent();
    }
    async onDest(ev) {
        this.t.dest_id = parseInt(ev.target.value) || false;
        const dest = this.location(this.t.dest_id);
        const valid = this.receiverOptions.some((u) => u.id === this.t.receiver_id);
        if (dest && (!this.t.receiver_id || !valid)) {
            this.t.receiver_id = dest.receiver_id || false;
        }
        this.touch();
        await this.loadRecent();
    }
    onReceiver(ev) {
        this.t.receiver_id = parseInt(ev.target.value) || false;
        this.touch();
    }
    onNote(ev) {
        this.t.note = ev.target.value;
        this.touch();
    }
    onQty(line, ev) {
        const v = parseFloat(String(ev.target.value).replace(",", "."));
        line.qty = isNaN(v) || v < 0 ? 0 : v;
        this.touch();
    }
    removeLine(line) {
        this.t.lines = this.t.lines.filter((l) => l !== line);
        this.touch();
    }
    addProduct(p, qty = 1) {
        const line = this.t.lines.find((l) => l.product_id === p.id);
        if (line) {
            line.qty += qty;
        } else {
            this.t.lines.push({
                product_id: p.id,
                product: p.product || p.name,
                char: p.char || "",
                barcode: p.barcode,
                uom: p.uom,
                qty,
                onhand: p.onhand || 0,
            });
        }
        this.state.results = [];
        this.state.productSearch = "";
        this.touch();
    }
    onProductSearch(ev) {
        this.state.productSearch = ev.target.value;
        this.debounce("psearch", async () => {
            this.state.results = await this.call("ui_search_products", [
                this.t.src_id || false,
                this.state.productSearch,
            ]);
        }, 300);
    }
    async onProductKey(ev) {
        if (ev.key === "Enter" && this.state.results.length) {
            this.addProduct(this.state.results[0]);
        }
    }
    async repeatLast() {
        if (!this.state.recent.repeat_id) {
            return;
        }
        const lines = await this.call("ui_repeat_lines", [this.state.recent.repeat_id], {
            location_id: this.t.src_id || null,
        });
        for (const l of lines) {
            this.addProduct({ id: l.product_id, product: l.product, char: l.char, barcode: l.barcode, uom: l.uom, onhand: l.onhand }, l.qty);
        }
        this.notification.add(`${this.state.recent.repeat_name} takrorlandi`, { type: "info" });
    }

    // ------------------------------------------------------------ scanning
    async onBarcode(code) {
        if (this.state.view === "list") {
            this.state.search = code;
            return this.refresh();
        }
        if (this.editable) {
            const p = await this.call("ui_product_by_barcode", [this.t.src_id || false, code]);
            if (p) {
                this.addProduct(p);
                this.notification.add(`${p.name}: +1`, { type: "success" });
            } else {
                this.notification.add(`«${code}» topilmadi`, { type: "danger" });
            }
        } else if (this.receiving) {
            const line = this.t.lines.find((l) => l.barcode === code);
            if (line) {
                this.notification.add(`${line.product}: ${this.fmt(line.received)} / ${this.fmt(line.qty)}`, { type: "info" });
            } else {
                this.notification.add(`«${code}» bu ichki o'tkazmada yo'q`, { type: "danger" });
            }
        }
    }
    async openCamera() {
        try {
            const code = await scanBarcode(this.env);
            if (code) {
                await this.onBarcode(code);
            }
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "warning" });
        }
    }

    // ------------------------------------------------------------ actions
    async saveDraft() {
        await this.save();
        this.notification.add("Qoralama saqlandi", { type: "info" });
        await this.backToList();
    }
    send() {
        const dest = this.location(this.t.dest_id);
        const receiver = this.state.options.users.find((u) => u.id === this.t.receiver_id);
        if (!dest) {
            return this.notification.add("«Qayerga» omborini tanlang", { type: "warning" });
        }
        if (!receiver) {
            return this.notification.add("Qabul qiluvchini tanlang", { type: "warning" });
        }
        if (!this.lineCount) {
            return this.notification.add("Kamida bitta mahsulot qo'shing", { type: "warning" });
        }
        let body = `${this.lineCount} ta mahsulot → ${dest.name}\nQabul qiluvchi: ${receiver.name}`;
        if (this.isIntercompany) {
            body += `\n\nKompaniyalararo: mahsulot hozir ombordan chiqadi, «${dest.company}» da ${receiver.name} qabul qiladi.`;
        }
        this.dialog.add(ConfirmationDialog, {
            title: "Yuborish",
            body,
            confirmLabel: "Yuborish",
            cancelLabel: "Bekor",
            confirm: async () => {
                await this.save();
                await this.call("ui_send", [this.t.id]);
                this.notification.add("Jo'natildi", { type: "success" });
                this.state.filter = "mine";
                await this.backToList();
            },
            cancel: () => {},
        });
    }
    receive() {
        const diffs = this.t.lines.filter((l) => l.received !== l.qty);
        let body = `${this.t.name}: ${this.t.src} → ${this.t.dest}\nJo'natdi: ${this.t.sender}`;
        if (diffs.length) {
            body += "\n\nFarq bor:\n" + diffs.map((l) => `• ${l.product}: ${this.fmt(l.qty)} → ${this.fmt(l.received)}`).join("\n");
            body += "\nQabul qilinmagan qism jo'natgan omborda qoladi.";
        }
        this.dialog.add(ConfirmationDialog, {
            title: "Qabul qilish",
            body,
            confirmLabel: "Qabul qildim",
            cancelLabel: "Bekor",
            confirm: async () => {
                const quantities = {};
                for (const l of this.t.lines) {
                    quantities[l.move_id] = l.received;
                }
                await this.call("ui_receive", [this.t.id, quantities]);
                this.notification.add("Qabul qilindi", { type: "success" });
                await this.open({ id: this.t.id });
            },
            cancel: () => {},
        });
    }
    onReceived(line, ev) {
        const v = parseFloat(String(ev.target.value).replace(",", "."));
        line.received = isNaN(v) || v < 0 ? 0 : Math.min(v, line.qty);
        ev.target.value = line.received;
    }
    cancelTransfer() {
        this.dialog.add(ConfirmationDialog, {
            title: "Bekor qilish",
            body: "Bu ichki o'tkazma bekor qilinsinmi?",
            confirmLabel: "Ha, bekor qilish",
            cancelLabel: "Yo'q",
            confirm: async () => {
                if (this.t.id) {
                    await this.call("ui_cancel", [this.t.id]);
                }
                clearTimeout(this.timers.save);
                this.state.saving = "";
                this.state.view = "list";
                this.state.t = null;
                await this.refresh();
            },
            cancel: () => {},
        });
    }
}
