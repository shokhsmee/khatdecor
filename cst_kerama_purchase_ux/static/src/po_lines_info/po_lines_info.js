import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { usePopover } from "@web/core/popover/popover_hook";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

class PoLinesInfoPopover extends Component {
    static template = "cst_kerama_purchase_ux.PoLinesInfoPopover";
    static props = { data: Object, close: { type: Function, optional: true } };
}

/** List-column ⓘ icon: click shows the order's products with prices. */
export class PoLinesInfo extends Component {
    static template = "cst_kerama_purchase_ux.PoLinesInfo";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.popover = usePopover(PoLinesInfoPopover, { position: "right" });
        this.state = useState({ loading: false });
    }

    async onClick(ev) {
        const target = ev.currentTarget;
        if (this.popover.isOpen) {
            this.popover.close();
            return;
        }
        const resId = this.props.record.resId;
        if (!resId) {
            return;
        }
        this.state.loading = true;
        try {
            const data = await this.orm.call("purchase.order", "cst_get_lines_info", [[resId]]);
            this.popover.open(target, { data });
        } finally {
            this.state.loading = false;
        }
    }
}

registry.category("view_widgets").add("cst_po_lines_info", {
    component: PoLinesInfo,
});
