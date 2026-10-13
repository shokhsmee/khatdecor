/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";

patch(PosStore.prototype, {
    redirectToBackend() {
        window.location = (this.session.user_id && this.session.user_id.pos_config_id)
            ? '/web/session/logout'
            : "/odoo/action-point_of_sale.action_client_pos_menu";
    },
});
