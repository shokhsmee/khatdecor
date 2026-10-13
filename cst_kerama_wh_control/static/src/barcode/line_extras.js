/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import LineComponent from "@stock_barcode/components/line";
import { LineNoteDialog } from "./line_note_dialog";

/**
 * Per-line photo and comment in the Barcode app.
 *
 * The photo is attached to the line it was taken on (so it never shows up on
 * another line) and is echoed to the transfer's chatter together with the
 * product it belongs to; a comment is posted the same way.
 */
patch(LineComponent.prototype, {
    get cstServices() {
        return this.env.services;
    },

    get cstPhotoCount() {
        return this.props.line.cst_photo_count || 0;
    },

    get cstCommentCount() {
        return this.props.line.cst_comment_count || 0;
    },

    get cstCanAnnotate() {
        // a line only gets an id once it has been saved to the server
        return Boolean(this.props.line.id) && !this.props.subline;
    },

    /** Ask the browser for a picture; on a phone this opens the camera. */
    cstTakePhoto() {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "image/*";
        input.capture = "environment";
        input.style.display = "none";
        input.addEventListener("change", async () => {
            const file = input.files && input.files[0];
            input.remove();
            if (file) {
                await this.cstUploadPhoto(file);
            }
        });
        document.body.appendChild(input);
        input.click();
    },

    async cstUploadPhoto(file) {
        const notification = this.cstServices.notification;
        const datas = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result.split(",")[1]);
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
        try {
            await this.env.model.save();
            const result = await this.cstServices.orm.call(
                "stock.move.line",
                "cst_barcode_add_photo",
                [[this.props.line.id], datas, file.name]
            );
            this.props.line.cst_photo_count = result.photo_count;
            this.render();
            notification.add(_t("Photo added to this line."), { type: "success" });
        } catch (error) {
            notification.add(error.data ? error.data.message : String(error), {
                type: "danger",
            });
        }
    },

    cstAddComment() {
        this.cstServices.dialog.add(LineNoteDialog, {
            lineLabel: this.props.line.product_id.display_name,
            onConfirm: async (body) => {
                await this.env.model.save();
                const result = await this.cstServices.orm.call(
                    "stock.move.line",
                    "cst_barcode_add_note",
                    [[this.props.line.id], body]
                );
                this.props.line.cst_comment_count = result.comment_count;
                this.render();
                this.cstServices.notification.add(
                    _t("Comment posted to the transfer."),
                    { type: "success" }
                );
            },
        });
    },
});
