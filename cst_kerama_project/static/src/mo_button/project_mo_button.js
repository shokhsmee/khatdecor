import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { CstMoDialog } from "@cst_kerama_shift/mo_builder/mo_dialog";

/**
 * Open the shared «Yangi buyurtma» dialog for one project.
 *
 * It is the same component the Shop Floor uses; only the three server calls
 * differ, so the order comes out stamped with the project and its request
 * line, and stock is read against the project's own warehouse.
 */
export function openProjectMoDialog(dialogService, projectId, { projectName, onCreated } = {}) {
    dialogService.add(CstMoDialog, {
        title: _t("Ishlab chiqarish yaratish"),
        subtitle: projectName || "",
        planTitle: _t("Bu loyiha bo'yicha ishlab chiqarish kerak"),
        optionsCall: { model: "project.project", method: "cst_mo_options", args: [[projectId]] },
        previewCall: { model: "project.project", method: "cst_mo_preview", args: [[projectId]] },
        createCall: { model: "project.project", method: "cst_mo_create", args: [[projectId]] },
        searchCall: { model: "project.project", method: "cst_mo_search_products", args: [[projectId]] },
        onCreated: onCreated || (() => {}),
    });
}

/** The «Ishlab chiqarish yaratish» button in the project form header. */
export class ProjectNewMoButton extends Component {
    static template = "cst_kerama_project.NewMoButton";
    static props = {
        record: Object,
        readonly: { type: Boolean, optional: true },
    };

    setup() {
        this.dialog = useService("dialog");
    }

    get ready() {
        return !!this.props.record.data.cst_manufacture_ready;
    }

    get missing() {
        return this.props.record.data.cst_manufacture_missing || "";
    }

    get title() {
        return this.ready
            ? _t("Every component is in the warehouse: choose the product, the quantity, the materials and the operations.")
            : _t("Some components are still missing (free/needed): %s", this.missing);
    }

    open() {
        const record = this.props.record;
        if (!record.resId) {
            return;
        }
        openProjectMoDialog(this.dialog, record.resId, {
            projectName: record.data.display_name || record.data.name || "",
            onCreated: () => record.load(),
        });
    }
}

export const projectNewMoButton = {
    component: ProjectNewMoButton,
    fieldDependencies: [
        { name: "cst_manufacture_ready", type: "boolean", readonly: true },
        { name: "cst_manufacture_missing", type: "char", readonly: true },
    ],
};

registry.category("view_widgets").add("cst_project_new_mo", projectNewMoButton);
