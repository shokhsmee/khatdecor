/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Xisobotlar — the app's landing page: every section the user may open,
 * with its reports as links. Opening the app used to start the first report
 * of the list, so a role whose first report is a wizard (Tovar harakati) got
 * a dialog over an empty home screen.
 */
export class ReportsHome extends Component {
    static template = "cst_kerama_reports.ReportsHome";
    static props = ["*"];

    setup() {
        this.menu = useService("menu");
    }

    get app() {
        return this.menu.getCurrentApp() || this.menu.getAll().find((m) => m.xmlid === "cst_kerama_reports.menu_reports_root");
    }

    /** Leaves under a menu, with the path of sub-groups in front of their name. */
    _leaves(node, prefix) {
        const out = [];
        for (const child of node.childrenTree || []) {
            if (child.childrenTree && child.childrenTree.length) {
                out.push(...this._leaves(child, prefix.concat([child.name])));
            } else if (child.actionID) {
                out.push({ id: child.id, name: child.name, group: prefix.join(" › "), menu: child });
            }
        }
        return out;
    }

    get sections() {
        const app = this.app;
        if (!app) {
            return [];
        }
        const tree = this.menu.getMenuAsTree(app.id);
        const sections = [];
        const loose = [];
        for (const child of tree.childrenTree || []) {
            if (child.childrenTree && child.childrenTree.length) {
                const items = this._leaves(child, []);
                if (items.length) {
                    sections.push({ id: child.id, name: child.name, items });
                }
            } else if (child.actionID && child.xmlid !== "cst_kerama_reports.menu_reports_home") {
                loose.push({ id: child.id, name: child.name, group: "", menu: child });
            }
        }
        if (loose.length) {
            sections.unshift({ id: 0, name: "Asosiy", items: loose });
        }
        return sections;
    }

    open(item) {
        this.menu.selectMenu(item.menu);
    }
}

registry.category("actions").add("cst_reports_home", ReportsHome);
