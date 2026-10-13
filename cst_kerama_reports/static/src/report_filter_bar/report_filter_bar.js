import { Component, markRaw, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { View } from "@web/views/view";
import { ReportAction } from "@web/webclient/actions/reports/report_action";

/** The sheet's wizard form, flattened to one row, above the iframe. */
export class CstReportFilterBar extends Component {
    static template = "cst_kerama_reports.ReportFilterBar";
    static components = { View };
    static props = { info: Object, onApply: Function };

    setup() {
        const { model, arch, fields, relatedModels, resId } = this.props.info;
        this.viewProps = {
            type: "form",
            resModel: model,
            resId,
            arch,
            fields: markRaw(fields),
            relatedModels: markRaw(relatedModels),
            context: {},
            display: { controlPanel: false },
            className: "cst_rf_view",
            preventCreate: true,
            discardRecord: () => {},
            saveRecord: async (record) => {
                const saved = await record.save();
                if (saved) {
                    this.props.onApply();
                }
                return saved;
            },
        };
    }
}

ReportAction.components = { ...ReportAction.components, CstReportFilterBar };

patch(ReportAction.prototype, {
    setup() {
        super.setup(...arguments);
        this.cstFilter = useState({ info: null });
        const ids = this.props.context?.active_ids;
        if (this.props.report_name?.startsWith("cst_kerama_reports.") && ids?.length === 1) {
            const orm = useService("orm");
            onWillStart(async () => {
                try {
                    const info = await orm.call("cst.report.filter.bar", "get_filter_bar", [
                        this.props.report_name,
                        ids[0],
                    ]);
                    if (info) {
                        this.cstFilter.info = markRaw({ ...info, resId: ids[0] });
                    }
                } catch {
                    // no bar is better than no report
                }
            });
        }
    },

    cstReloadReport() {
        this.iframe.el?.contentWindow?.location.reload();
    },
});
