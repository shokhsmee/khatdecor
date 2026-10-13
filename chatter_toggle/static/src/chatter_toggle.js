/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useState, onWillDestroy, useEffect } from "@odoo/owl";
import { Thread } from "@mail/core/common/thread";

const STORAGE_KEY = "chatter_toggle_visible";

// Singleton floating button that lives on <body> — always visible,
// even when the chatter panel itself is hidden.
const floatingToggle = {
    el: null,
    refCount: 0,

    mount(onToggle) {
        this.refCount++;
        if (!this.el) {
            const btn = document.createElement("button");
            btn.className = "o_chatter_float_toggle";
            document.body.appendChild(btn);
            this.el = btn;
        }
        // Always bind to the current Thread instance's handler
        this.el.onclick = onToggle;
    },

    update(visible) {
        if (!this.el) return;
        this.el.innerHTML = visible
            ? '<i class="fa fa-chevron-right" aria-hidden="true"></i>'
            : '<i class="fa fa-chevron-left" aria-hidden="true"></i>';
        this.el.title = visible ? "Hide Chatter" : "Show Chatter";
        this.el.setAttribute("aria-label", visible ? "Hide Chatter" : "Show Chatter");
    },

    unmount() {
        this.refCount = Math.max(0, this.refCount - 1);
        if (this.refCount === 0 && this.el) {
            this.el.remove();
            this.el = null;
        }
    },
};

patch(Thread.prototype, {
    setup() {
        super.setup(...arguments);

        const stored = localStorage.getItem(STORAGE_KEY);
        const initialVisible = stored === null ? true : stored === "true";

        this.toggleState = useState({ visible: initialVisible });
        this._syncBodyClass(initialVisible);

        floatingToggle.mount(() => this.toggleChatter());
        floatingToggle.update(initialVisible);

        // Keep floating button in sync whenever reactive state changes
        useEffect(
            () => { floatingToggle.update(this.toggleState.visible); },
            () => [this.toggleState.visible]
        );

        onWillDestroy(() => {
            floatingToggle.unmount();
            if (floatingToggle.refCount === 0) {
                document.body.classList.remove("o_chatter_panel_hidden");
            }
        });
    },

    toggleChatter() {
        this.toggleState.visible = !this.toggleState.visible;
        localStorage.setItem(STORAGE_KEY, String(this.toggleState.visible));
        this._syncBodyClass(this.toggleState.visible);
    },

    _syncBodyClass(visible) {
        document.body.classList.toggle("o_chatter_panel_hidden", !visible);
    },
});
