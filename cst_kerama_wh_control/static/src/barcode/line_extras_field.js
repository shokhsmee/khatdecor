/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";

const AUTOSAVE_DELAY = 1200;

/**
 * Photos and comment for one transfer line, shown inside the line screen.
 *
 * The comment saves itself: shortly after typing stops, and when the box
 * loses focus. The widget keeps its own copy of the data and refreshes it
 * from the value every server call returns, so it never depends on the form
 * reloading.
 */
export class CstLineExtrasField extends Component {
    static template = "cst_kerama_wh_control.LineExtrasField";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.timer = null;
        this.state = useState({
            photos: [],
            comments: [],
            note: "",
            saved: "",       // "saving" | "saved" | ""
            busy: false,
        });
        onWillStart(() => this.load());
        onWillUnmount(() => this.clearTimer());
    }

    get resId() {
        return this.props.record.resId;
    }

    clearTimer() {
        if (this.timer) {
            clearTimeout(this.timer);
            this.timer = null;
        }
    }

    apply(result) {
        this.state.photos = result.photos || [];
        this.state.comments = result.comments || [];
        if (typeof result.note === "string") {
            this.state.note = result.note;
        }
    }

    async load() {
        if (!this.resId) {
            return;
        }
        this.apply(
            await this.orm.call("stock.move.line", "cst_line_extras", [[this.resId]])
        );
    }

    thumbUrl(photo) {
        return `/web/image/${photo.id}/128x128`;
    }

    fullUrl(photo) {
        return `/web/image/${photo.id}`;
    }

    // ------------------------------------------------------------------
    //  Photos
    // ------------------------------------------------------------------
    /** Opens the camera on a phone, the file picker on a computer. */
    pickPhoto() {
        if (!this.resId || this.state.busy) {
            return;
        }
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "image/*";
        input.capture = "environment";
        input.style.display = "none";
        input.addEventListener("change", async () => {
            const file = input.files && input.files[0];
            input.remove();
            if (file) {
                await this.uploadPhoto(file);
            }
        });
        document.body.appendChild(input);
        input.click();
    }

    async uploadPhoto(file) {
        this.state.busy = true;
        try {
            const datas = await new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(reader.result.split(",")[1]);
                reader.onerror = reject;
                reader.readAsDataURL(file);
            });
            this.apply(
                await this.orm.call("stock.move.line", "cst_barcode_add_photo", [
                    [this.resId],
                    datas,
                    file.name,
                ])
            );
            this.notification.add(_t("Photo added to this line."), { type: "success" });
        } catch (error) {
            this.showError(error);
        } finally {
            this.state.busy = false;
        }
    }

    // ------------------------------------------------------------------
    //  Comment — saves itself
    // ------------------------------------------------------------------
    onNoteInput(ev) {
        this.state.note = ev.target.value;
        this.state.saved = "";
        this.clearTimer();
        this.timer = setTimeout(() => this.saveNote(), AUTOSAVE_DELAY);
    }

    onNoteBlur() {
        this.clearTimer();
        this.saveNote();
    }

    async saveNote() {
        this.clearTimer();
        if (!this.resId || this.state.busy) {
            return;
        }
        this.state.busy = true;
        this.state.saved = "saving";
        try {
            this.apply(
                await this.orm.call("stock.move.line", "cst_barcode_set_note", [
                    [this.resId],
                    this.state.note,
                ])
            );
            this.state.saved = "saved";
        } catch (error) {
            this.state.saved = "";
            this.showError(error);
        } finally {
            this.state.busy = false;
        }
    }

    showError(error) {
        this.notification.add(error.data ? error.data.message : String(error), {
            type: "danger",
        });
    }
}

export const cstLineExtrasField = {
    component: CstLineExtrasField,
    displayName: _t("Line Photos & Comments"),
    supportedTypes: ["integer"],
};

registry.category("fields").add("cst_line_extras", cstLineExtrasField);
