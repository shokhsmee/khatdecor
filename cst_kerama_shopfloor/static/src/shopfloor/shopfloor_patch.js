/**
 * Khatdecor patches to the Enterprise Shop Floor (mrp_display).
 *
 *  - operator mode: only the user's own employee on the panel, only the
 *    lines they are attached to as tabs, only their own work orders;
 *  - Face ID: red banner when the session owner has no open attendance,
 *    a live clock since check-in when they do;
 *  - «Yangi buyurtma» button (product, quantity, editable bill of materials,
 *    operations and lines);
 *  - the card shows the sale order reference and the 2-sort / brak counted,
 *    with a dialog to type them.
 */
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { onWillStart, onWillUnmount, onWillRender, useState, useSubEnv } from "@odoo/owl";
import { MrpDisplayAction } from "@mrp_workorder/mrp_display/mrp_display_action";
import { MrpDisplay } from "@mrp_workorder/mrp_display/mrp_display";
import { MrpDisplayRecord } from "@mrp_workorder/mrp_display/mrp_display_record";
import { MrpDisplaySearchModel } from "@mrp_workorder/mrp_display/search_model";
import { MrpMenuDialog } from "@mrp_workorder/mrp_display/dialog/mrp_menu_dialog";
import { CstMoDialog } from "@cst_kerama_shift/mo_builder/mo_dialog";
import { CstResultDialog } from "./result_dialog";
import { CstPresenceClock } from "./presence_clock";
import { cstShopfloor } from "./utils";
import { fmtNumber } from "@cst_kerama_shift/mo_builder/mo_dialog";

function isOperatorMode() {
    return !!(cstShopfloor.config && cstShopfloor.config.operator_mode);
}

function includesEmployee(field, employeeId) {
    if (!field || !employeeId) {
        return false;
    }
    const ids = field.resIds || field.currentIds || [];
    return ids.includes(employeeId);
}

// ---------------------------------------------------------------- action: config + fields
patch(MrpDisplayAction.prototype, {
    get fieldsStructure() {
        const structure = super.fieldsStructure;
        structure["mrp.production"].push("cst_sale_ref", "cst_second_qty", "cst_scrap_qty", "origin");
        structure["mrp.workorder"].push("cst_operator_ids", "cst_department_id", "cst_shift_id");
        return structure;
    },

    setup() {
        cstShopfloor.config = null;
        super.setup();
        onWillStart(async () => {
            cstShopfloor.config = await this.orm.call("cst.shopfloor", "get_config", []);
        });
    },
});

// ---------------------------------------------------------------- search model: operator domain
patch(MrpDisplaySearchModel.prototype, {
    async load(config) {
        const cfg = cstShopfloor.config;
        if (cfg && cfg.operator_mode && cfg.wo_domain && cfg.wo_domain.length) {
            config = { ...config, domain: [...(config.domain || []), ["workorder_ids", "any", cfg.wo_domain]] };
        }
        return super.load(config);
    },
});

// ---------------------------------------------------------------- the screen
Object.assign(MrpDisplay.components, { CstPresenceClock });

patch(MrpDisplay.prototype, {
    setup() {
        super.setup();
        const cfg = cstShopfloor.config || {};
        this.cst = useState({
            operatorMode: !!cfg.operator_mode,
            employee: cfg.employee || false,
            presence: cfg.presence || { online: false, employee_id: false },
        });
        this._cstPresenceFor = cfg.presence ? cfg.presence.employee_id : false;
        useSubEnv({ cstShopfloor: this.cst });

        if (this.cst.operatorMode) {
            const mine = cfg.workcenters || [];
            this.state.workcenters = [{ id: -1, display_name: _t("Mening ishlarim") }, ...mine];
            this.state.firstLoad = false;
            const stored = this.state.activeWorkcenter;
            const valid = this.state.workcenters.some((wc) => wc.id === stored);
            this.state.activeWorkcenter = valid ? stored : mine.length ? mine[0].id : -1;
            this.state.activeResModel = "mrp.workorder";
        }

        this._cstPresenceTimer = setInterval(() => this.cstRefreshPresence(), 60000);
        onWillUnmount(() => clearInterval(this._cstPresenceTimer));
        onWillRender(() => {
            const admin = this.useEmployee.employees.admin || {};
            const id = admin.id || (this.cst.employee && this.cst.employee.id) || false;
            if (id !== this._cstPresenceFor) {
                this._cstPresenceFor = id;
                this.cstRefreshPresence();
            }
        });
    },

    // ------------------------------------------------ operator mode
    get filteredWorkorders() {
        const workorders = super.filteredWorkorders;
        if (!this.cst || !this.cst.operatorMode) {
            return workorders;
        }
        const me = this.cst.employee ? this.cst.employee.id : false;
        return workorders.filter((wo) => includesEmployee(wo.data.cst_operator_ids, me));
    },

    toggleWorkcenterDialog(showWarning = true) {
        if (this.cst && this.cst.operatorMode) {
            return;
        }
        return super.toggleWorkcenterDialog(showWarning);
    },

    popupAddEmployee() {
        if (this.cst && this.cst.operatorMode) {
            return;
        }
        return super.popupAddEmployee();
    },

    // ------------------------------------------------ Face ID presence
    async cstRefreshPresence() {
        const id = this._cstPresenceFor;
        if (!id) {
            this.cst.presence = { online: false, employee_id: false };
            return;
        }
        try {
            this.cst.presence = await this.orm.call("cst.shopfloor", "presence", [id]);
        } catch (error) {
            console.warn("cst_kerama_shopfloor: presence", error);
        }
    },

    get cstOnline() {
        return !!(this.cst.presence && this.cst.presence.online);
    },

    get cstShowClock() {
        return !!(this.cst.presence && this.cst.presence.employee_id);
    },

    get cstShowOffline() {
        return this.cstShowClock && !this.cstOnline;
    },

    get cstPresenceName() {
        return (this.cst.presence && this.cst.presence.name) || "";
    },

    // ------------------------------------------------ new order
    openCstNewOrder() {
        this.dialogService.add(CstMoDialog, {
            title: _t("Yangi buyurtma"),
            optionsCall: { model: "cst.shopfloor", method: "new_order_options", args: [] },
            previewCall: { model: "cst.shopfloor", method: "bom_preview", args: [] },
            createCall: { model: "cst.shopfloor", method: "create_order", args: [] },
            onCreated: async () => {
                this.invalidateRecordIdsCache();
                await this.env.reload();
            },
        });
    },
});

// ---------------------------------------------------------------- the card
patch(MrpDisplayRecord.prototype, {
    get cstProductionData() {
        return (this.props.production && this.props.production.data) || {};
    },

    get cstSaleRef() {
        return this.cstProductionData.cst_sale_ref || "";
    },

    get cstSecond() {
        return fmtNumber(this.cstProductionData.cst_second_qty || 0);
    },

    get cstScrap() {
        return fmtNumber(this.cstProductionData.cst_scrap_qty || 0);
    },

    get cstHasSecond() {
        return Number(this.cstProductionData.cst_second_qty || 0) > 0;
    },

    get cstHasScrap() {
        return Number(this.cstProductionData.cst_scrap_qty || 0) > 0;
    },

    get cstCanEnterResult() {
        return (
            !this.props.demoRecord &&
            this.props.record.resModel === "mrp.workorder" &&
            !["done", "cancel"].includes(this.record.state)
        );
    },

    async openCstResults(kind) {
        if (this.props.demoRecord || !this.props.production) {
            return;
        }
        const action = await this.model.orm.call("cst.shopfloor", "result_action", [this.props.production.resId, kind]);
        await this.action.doAction(action, { onClose: () => this.env.reload(this.props.production) });
    },

    openCstResultEntry() {
        if (!this.cstCanEnterResult) {
            return;
        }
        this.dialog.add(CstResultDialog, {
            workorderId: this.props.record.resId,
            title: _t("%s — natija", this.record.production_id.display_name),
            productName: this.record.product_id.display_name,
            remaining: this.record.qty_remaining,
            onSaved: () => this.env.reload(this.props.production),
        });
    },
});

// ---------------------------------------------------------------- the ⋮ menu
patch(MrpMenuDialog.prototype, {
    openCstResult() {
        const record = this.props.record;
        if (record.resModel !== "mrp.workorder") {
            return;
        }
        this.dialogService.add(CstResultDialog, {
            workorderId: record.resId,
            title: _t("%s — natija", record.data.production_id.display_name),
            productName: record.data.product_id.display_name,
            remaining: record.data.qty_remaining,
            onSaved: () => this.props.reload(record),
        });
        this.props.close();
    },
});
