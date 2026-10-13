import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { formatFloat } from "@web/core/utils/numbers";
import { TransferSection } from "./transfer";

const MODEL = "cst.dispatch";

export class DispatchApp extends Component {
    static template = "cst_kerama_dispatch.DispatchApp";
    static props = ["*"];
    static components = { TransferSection };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.barcode = useService("barcode");
        this.cameraSupported = isBarcodeScannerSupported();
        this.state = useState({
            screen: "home",
            home: {},
            list: [],
            search: "",
            dispatch: null,
            flashId: false,
            productSearch: "",
            productResults: [],
            showAdd: false,
            busy: false,
        });
        useBus(this.barcode.bus, "barcode_scanned", (ev) => this.onBarcode(ev.detail.barcode));
        this.searchTimer = null;
        onWillStart(async () => {
            await this.loadHome();
            const did = this.props.action?.params?.dispatch_id;
            if (did) {
                await this.openDispatch(did);
            }
        });
        onWillUnmount(() => clearTimeout(this.searchTimer));
    }

    // ------------------------------------------------------------ helpers
    fmt(n) {
        return formatFloat(n || 0, { digits: [16, 3], trailingZeros: false });
    }
    money(n) {
        return formatFloat(n || 0, { digits: [16, 2] });
    }
    async call(method, args = [], kwargs = {}) {
        this.state.busy = true;
        try {
            return await this.orm.call(MODEL, method, args, kwargs);
        } finally {
            this.state.busy = false;
        }
    }
    get d() {
        return this.state.dispatch;
    }
    get isDraft() {
        return this.d && this.d.state === "draft";
    }
    get isReady() {
        return this.d && this.d.state === "ready";
    }
    get canEditQty() {
        return this.isDraft && this.state.home.can_wh;
    }
    get canCheck() {
        return this.isReady && this.state.home.can_gate;
    }
    get stateLabel() {
        return {
            draft: "Tayyorlanmoqda",
            ready: "Jo'natishga tayyor",
            done: "Chiqarildi",
            cancel: "Bekor qilindi",
        }[this.d?.state] || "";
    }
    get progress() {
        const lines = (this.d?.line_list || []).filter((l) => l.qty > 0);
        const ok = lines.filter((l) => l.checked === l.qty).length;
        return { ok, total: lines.length };
    }
    get allChecked() {
        const lines = this.d?.line_list || [];
        return lines.every((l) => l.checked === l.qty);
    }
    get differences() {
        return (this.d?.line_list || []).filter((l) => this.lineFinal(l) !== l.remaining);
    }
    lineFinal(l) {
        return this.d.state === "draft" ? l.qty : this.d.state === "ready" ? l.checked : l.qty;
    }
    lineClass(l) {
        const cls = [];
        if (l.id === this.state.flashId) {
            cls.push("o_cst_dp_flash");
        }
        if (this.d.state === "ready" || this.d.state === "done") {
            if (l.qty === 0 && l.checked === 0) {
                cls.push("o_cst_dp_muted");
            } else if (l.checked === l.qty) {
                cls.push("o_cst_dp_ok");
            } else if (l.checked > l.qty) {
                cls.push("o_cst_dp_over");
            } else if (l.checked > 0) {
                cls.push("o_cst_dp_partial");
            }
        } else if (l.qty === 0) {
            cls.push("o_cst_dp_muted");
        } else if (l.qty > l.onhand) {
            cls.push("o_cst_dp_short");
        }
        return cls.join(" ");
    }
    diffBadge(l) {
        if (l.is_extra) {
            return { cls: "text-bg-info", text: "Qo'shimcha mahsulot" };
        }
        const diff = this.lineFinal(l) - l.remaining;
        if (Math.abs(diff) < 0.0005) {
            return false;
        }
        return diff > 0
            ? { cls: "text-bg-primary", text: `+${this.fmt(diff)} ortiqcha` }
            : { cls: "text-bg-danger", text: `${this.fmt(diff)} kam` };
    }

    // ------------------------------------------------------------ navigation
    async loadHome() {
        this.state.home = await this.call("ui_home");
    }
    async goHome() {
        this.state.screen = "home";
        this.state.dispatch = null;
        this.state.search = "";
        await this.loadHome();
    }
    goTransfers() {
        this.state.screen = "transfers";
    }
    async goList(screen) {
        this.state.screen = screen;
        this.state.search = "";
        await this.refreshList();
    }
    async refreshList() {
        const method = { orders: "ui_orders", ready: "ui_ready", history: "ui_history" }[
            this.state.screen
        ];
        this.state.list = await this.call(method, [], { search: this.state.search || null });
    }
    onSearchInput(ev) {
        this.state.search = ev.target.value;
        clearTimeout(this.searchTimer);
        this.searchTimer = setTimeout(() => this.refreshList(), 300);
    }
    async back() {
        if (this.state.screen === "dispatch") {
            const from = this.state.from || "home";
            if (from === "home") {
                return this.goHome();
            }
            await this.loadHome();
            return this.goList(from);
        }
        return this.goHome();
    }
    async openOrder(order) {
        const id = await this.call("ui_start", [order.id]);
        this.state.from = "orders";
        await this.openDispatch(id);
    }
    async openCard(card) {
        this.state.from = this.state.screen;
        await this.openDispatch(card.id);
    }
    async openDispatch(id) {
        this.state.dispatch = await this.call("ui_load", [id]);
        this.state.screen = "dispatch";
        this.state.showAdd = false;
    }
    async reload() {
        if (this.d) {
            this.state.dispatch = await this.call("ui_load", [this.d.id]);
        }
    }
    flash(lineId) {
        this.state.flashId = lineId;
        setTimeout(() => {
            if (this.state.flashId === lineId) {
                this.state.flashId = false;
            }
        }, 900);
        setTimeout(() => {
            const el = document.querySelector(`[data-line-id="${lineId}"]`);
            el?.scrollIntoView({ block: "center", behavior: "smooth" });
        }, 50);
    }

    // ------------------------------------------------------------ printing
    printWaybill(size) {
        window.open(`/kerama/dispatch/waybill/${this.d.id}?size=${size}`, "_blank");
    }

    // ------------------------------------------------------------ scanning
    async onBarcode(barcode) {
        if (this.state.screen !== "dispatch" || !this.d) {
            if (["orders", "ready", "history"].includes(this.state.screen)) {
                this.state.search = barcode;
                await this.refreshList();
            }
            return;
        }
        if (!(this.canEditQty || this.canCheck)) {
            return;
        }
        const res = await this.call("ui_scan", [this.d.id, barcode]);
        if (res.ok) {
            this.notification.add(res.message, { type: "success" });
            await this.reload();
            this.flash(res.line_id);
        } else {
            this.notification.add(res.message, { type: "danger", sticky: false });
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

    // ------------------------------------------------------------ line edits
    async setQty(line, value) {
        const field = this.isDraft ? "qty" : "checked_qty";
        await this.call("ui_set_qty", [line.id, Math.max(0, value)], { field });
        await this.reload();
    }
    async onQtyChange(line, ev) {
        const v = parseFloat(String(ev.target.value).replace(",", "."));
        await this.setQty(line, isNaN(v) ? 0 : v);
    }
    async inc(line, step) {
        const cur = this.isDraft ? line.qty : line.checked;
        await this.setQty(line, cur + step);
        this.flash(line.id);
    }
    async checkLine(line) {
        await this.setQty(line, line.qty);
        this.flash(line.id);
    }
    async checkAll() {
        await this.call("ui_check_all", [this.d.id]);
        await this.reload();
    }
    async removeLine(line) {
        await this.call("ui_remove_line", [line.id]);
        await this.reload();
    }

    // ------------------------------------------------------------ add product
    toggleAdd() {
        this.state.showAdd = !this.state.showAdd;
        this.state.productSearch = "";
        this.state.productResults = [];
    }
    onProductSearch(ev) {
        this.state.productSearch = ev.target.value;
        clearTimeout(this.searchTimer);
        this.searchTimer = setTimeout(async () => {
            this.state.productResults = await this.call("ui_search_products", [
                this.d.id,
                this.state.productSearch,
            ]);
        }, 300);
    }
    async addProduct(p) {
        const lineId = await this.call("ui_add_product", [this.d.id, p.id, 1]);
        this.state.showAdd = false;
        await this.reload();
        this.flash(lineId);
    }

    // ------------------------------------------------------------ state changes
    get canEditVehicle() {
        return this.canEditQty || this.canCheck;
    }
    async onFieldChange(field, ev) {
        this.d[field] = ev.target.value;
        await this.call("ui_set_vehicle", [this.d.id, { [field]: ev.target.value }]);
    }
    confirmReady() {
        this.dialog.add(ConfirmationDialog, {
            title: "Jo'natishga tayyor",
            body: `${this.d.order} — ${this.d.partner}\nBuyurtma eshik qorovuliga yuboriladi.`,
            confirmLabel: "Tasdiqlash",
            cancelLabel: "Bekor",
            confirm: async () => {
                await this.call("ui_confirm", [this.d.id]);
                this.notification.add("Jo'natishga tayyor — eshikka yuborildi", { type: "success" });
                await this.loadHome();
                await this.goList("orders");
            },
            cancel: () => {},
        });
    }
    cancelDispatch() {
        this.dialog.add(ConfirmationDialog, {
            title: "Bekor qilish",
            body: "Bu tayyorlov bekor qilinsinmi? Sotuv buyurtmasi o'zgarmaydi.",
            confirmLabel: "Ha, bekor qilish",
            cancelLabel: "Yo'q",
            confirm: async () => {
                await this.call("ui_cancel", [this.d.id]);
                await this.loadHome();
                await this.goList("orders");
            },
            cancel: () => {},
        });
    }
    backToWarehouse() {
        this.dialog.add(ConfirmationDialog, {
            title: "Omborga qaytarish",
            body: "Buyurtma qayta tayyorlash uchun ombor menejeriga qaytariladi. Sanoq tozalanadi.",
            confirmLabel: "Qaytarish",
            cancelLabel: "Bekor",
            confirm: async () => {
                await this.call("ui_back_to_draft", [this.d.id], { reason: "Eshikdan qaytarildi" });
                await this.loadHome();
                await this.goList("ready");
            },
            cancel: () => {},
        });
    }
    approveGate() {
        const diffs = this.differences;
        let body = `${this.d.order} — ${this.d.partner}\n`;
        if (!this.allChecked) {
            body += "\n⚠ Hamma qatorlar sanalmagan! Sanalgan miqdor jo'natiladi.\n";
        }
        if (diffs.length) {
            body += "\nSotuv buyurtmasi o'zgaradi:\n";
            for (const l of diffs) {
                const d = l.checked - l.remaining;
                body += `• ${l.product}: ${this.fmt(l.remaining)} → ${this.fmt(l.checked)} (${d > 0 ? "+" : ""}${this.fmt(d)})\n`;
            }
            body += `\nSumma: ${this.money(this.d.order_amount)} → ~${this.money(this.d.estimate)} ${this.d.currency}`;
        } else {
            body += "\nFarq yo'q — buyurtma bo'yicha to'liq chiqadi.";
        }
        this.dialog.add(ConfirmationDialog, {
            title: "Chiqarishni tasdiqlash",
            body,
            confirmLabel: "Tasdiqlash va chiqarish",
            cancelLabel: "Bekor",
            confirm: async () => {
                await this.call("ui_done", [this.d.id]);
                this.notification.add("Chiqarildi. Sotuv buyurtmasi yangilandi.", { type: "success" });
                await this.openDispatch(this.d.id);
                await this.loadHome();
            },
            cancel: () => {},
        });
    }
}

registry.category("actions").add("cst_dispatch_app", DispatchApp);
