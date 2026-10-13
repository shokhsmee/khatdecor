/** @odoo-module **/

import { Component, useRef, useState, onMounted } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

/** Small text box used to comment on one barcode line. */
export class LineNoteDialog extends Component {
    static template = "cst_kerama_wh_control.LineNoteDialog";
    static components = { Dialog };
    static props = {
        lineLabel: { type: String },
        onConfirm: { type: Function },
        close: { type: Function },
    };

    setup() {
        this.inputRef = useRef("note");
        this.state = useState({ value: "", sending: false });
        onMounted(() => this.inputRef.el && this.inputRef.el.focus());
    }

    get title() {
        return _t("Comment");
    }

    onInput(ev) {
        this.state.value = ev.target.value;
    }

    async confirm() {
        const body = this.state.value.trim();
        if (!body || this.state.sending) {
            return;
        }
        this.state.sending = true;
        try {
            await this.props.onConfirm(body);
            this.props.close();
        } finally {
            this.state.sending = false;
        }
    }
}
