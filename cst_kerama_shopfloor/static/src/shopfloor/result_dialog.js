import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { fmtNumber } from "@cst_kerama_shift/mo_builder/mo_dialog";

/** 1-sort / 2-sort / brak typed on the Shop Floor for one work order. */
export class CstResultDialog extends Component {
    static template = "cst_kerama_shopfloor.ResultDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        workorderId: Number,
        title: String,
        productName: { type: String, optional: true },
        remaining: { type: Number, optional: true },
        onSaved: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({ good: "", second: "", scrap: "", note: "", busy: false });
    }

    set(field, ev) {
        this.state[field] = ev.target.value;
    }

    get remainingLabel() {
        return this.props.remaining === undefined ? "" : fmtNumber(this.props.remaining);
    }

    get total() {
        return Number(this.state.good || 0) + Number(this.state.second || 0) + Number(this.state.scrap || 0);
    }

    get canConfirm() {
        const s = this.state;
        const values = [s.good, s.second, s.scrap].map((v) => Number(v || 0));
        return !s.busy && values.every((v) => v >= 0) && values.some((v) => v > 0);
    }

    async confirm() {
        if (!this.canConfirm) {
            return;
        }
        const s = this.state;
        s.busy = true;
        try {
            const res = await this.orm.call("cst.shopfloor", "record_result", [
                this.props.workorderId, Number(s.good || 0), Number(s.second || 0), Number(s.scrap || 0), s.note || null,
            ]);
            this.notification.add(_t("Natija yozildi (%s)", res.shift), { type: "success" });
            await this.props.onSaved(res);
            this.props.close();
        } catch (error) {
            s.busy = false;
            throw error;
        }
    }
}
