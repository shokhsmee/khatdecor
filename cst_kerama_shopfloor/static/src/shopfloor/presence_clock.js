import { Component, onWillUnmount, useState } from "@odoo/owl";
import { deserializeDateTime } from "@web/core/l10n/dates";

/** Face ID presence of the session owner: a live clock since check-in, or «Offline». */
export class CstPresenceClock extends Component {
    static template = "cst_kerama_shopfloor.PresenceClock";
    static props = {
        presence: { type: Object, optional: true },
    };

    setup() {
        this.state = useState({ now: Date.now() });
        this._tick = setInterval(() => {
            this.state.now = Date.now();
        }, 1000);
        onWillUnmount(() => clearInterval(this._tick));
    }

    get presence() {
        return this.props.presence || {};
    }

    get show() {
        return !!this.presence.employee_id;
    }

    get online() {
        return !!this.presence.online;
    }

    get name() {
        return this.presence.name || "";
    }

    get worked() {
        if (!this.online || !this.presence.check_in) {
            return "";
        }
        const start = deserializeDateTime(this.presence.check_in).ts;
        let seconds = Math.max(0, Math.floor((this.state.now - start) / 1000));
        const hours = Math.floor(seconds / 3600);
        seconds -= hours * 3600;
        const minutes = Math.floor(seconds / 60);
        seconds -= minutes * 60;
        const pad = (n) => String(n).padStart(2, "0");
        return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
    }

    get checkIn() {
        if (!this.presence.check_in) {
            return "";
        }
        return deserializeDateTime(this.presence.check_in).toFormat("HH:mm");
    }
}
