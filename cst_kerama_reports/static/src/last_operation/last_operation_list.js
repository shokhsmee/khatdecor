/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useService } from "@web/core/utils/hooks";
import { useEffect } from "@odoo/owl";

const MODEL = "cst.partner.last.operation";

// Двойной клик, the way the sheet has always been used: on the customer to
// get their akt sverka, on the movement to get the document behind it. The
// row also carries two buttons for whoever would rather see what they click.
const ON_DOUBLE_CLICK = {
    partner_id: "action_open_akt_sverka",
    last_operation: "action_open_last_document",
    days_display: "action_open_akt_sverka",
    balance: "action_open_akt_sverka",
};

patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        this.cstActionService = useService("action");
        this.cstOrmService = useService("orm");
        useEffect(
            (table) => {
                if (!table || this.props.list.resModel !== MODEL) {
                    return;
                }
                const handler = (ev) => this.cstOnLastOperationDblClick(ev);
                table.addEventListener("dblclick", handler);
                return () => table.removeEventListener("dblclick", handler);
            },
            () => [this.tableRef.el]
        );
    },

    async cstOnLastOperationDblClick(ev) {
        const cell = ev.target.closest("td.o_data_cell");
        const row = ev.target.closest("tr.o_data_row");
        if (!cell || !row) {
            return;
        }
        const method = ON_DOUBLE_CLICK[cell.getAttribute("name")];
        if (!method) {
            return;
        }
        const record = this.props.list.records.find((r) => r.id === row.dataset.id);
        if (!record || !record.resId) {
            return;
        }
        const action = await this.cstOrmService.call(MODEL, method, [[record.resId]]);
        if (action) {
            await this.cstActionService.doAction(action);
        }
    },
});
