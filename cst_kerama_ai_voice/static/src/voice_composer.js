/** @odoo-module **/

import { useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { ChatComposer } from "@muk_ai/chat/composer/chat_composer";

// Whatever the browser will actually record; OpenAI accepts all of these.
const FORMATS = [
    ["audio/webm;codecs=opus", "webm"],
    ["audio/webm", "webm"],
    ["audio/ogg;codecs=opus", "ogg"],
    ["audio/mp4", "m4a"],
];

// Long enough for a real question, short enough that a forgotten recording
// cannot quietly turn into a large bill.
const MAX_SECONDS = 120;

patch(ChatComposer.prototype, {
    setup() {
        super.setup(...arguments);
        this.notification = useService("notification");
        this.voice = useState({ recording: false, busy: false });
        this._recorder = null;
        this._chunks = [];
        this._stopTimer = null;
    },

    get voiceTitle() {
        if (this.voice.busy) {
            return _t("Matnga o'girilmoqda...");
        }
        return this.voice.recording ? _t("To'xtatish") : _t("Ovoz bilan yozish");
    },

    get voiceIcon() {
        if (this.voice.busy) {
            return "fa-spinner fa-spin";
        }
        return this.voice.recording ? "fa-stop" : "fa-microphone";
    },

    onVoiceClick() {
        if (this.voice.busy) {
            return;
        }
        if (this.voice.recording) {
            this._stopRecording();
        } else {
            this._startRecording();
        }
    },

    async _startRecording() {
        if (!navigator.mediaDevices || !window.MediaRecorder) {
            this.notification.add(
                _t("Бу браузер овоз ёзишни куллаб-кувватламайди."), { type: "warning" });
            return;
        }
        let stream;
        try {
            stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch {
            // Denied, or no microphone: either way there is nothing to record.
            this.notification.add(
                _t("Микрофонга рухсат берилмади."), { type: "warning" });
            return;
        }

        const [mimeType, extension] =
            FORMATS.find(([type]) => MediaRecorder.isTypeSupported(type)) || [undefined, "webm"];
        const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
        this._recorder = recorder;
        this._chunks = [];
        this._extension = extension;

        recorder.ondataavailable = (event) => {
            if (event.data && event.data.size) {
                this._chunks.push(event.data);
            }
        };
        recorder.onstop = async () => {
            stream.getTracks().forEach((track) => track.stop());
            const blob = new Blob(this._chunks, { type: recorder.mimeType || "audio/webm" });
            this._chunks = [];
            await this._transcribe(blob);
        };
        recorder.start();
        this.voice.recording = true;
        // A recording nobody stopped would otherwise run until the tab closes.
        this._stopTimer = setTimeout(() => this._stopRecording(), MAX_SECONDS * 1000);
    },

    _stopRecording() {
        clearTimeout(this._stopTimer);
        this._stopTimer = null;
        this.voice.recording = false;
        if (this._recorder && this._recorder.state !== "inactive") {
            this._recorder.stop();
        }
        this._recorder = null;
    },

    async _transcribe(blob) {
        if (!blob.size) {
            return;
        }
        this.voice.busy = true;
        try {
            const form = new FormData();
            form.append("audio", blob, `voice.${this._extension || "webm"}`);
            form.append("csrf_token", odoo.csrf_token);
            const response = await fetch("/cst_ai_voice/transcribe", {
                method: "POST",
                body: form,
            });
            const result = await response.json();
            if (result.error) {
                this.notification.add(result.error, { type: "warning" });
                return;
            }
            if (result.text) {
                this._insertText(result.text);
            }
        } catch {
            this.notification.add(
                _t("Матнга угариб булмади."), { type: "danger" });
        } finally {
            this.voice.busy = false;
        }
    },

    /** Put the words in the box, not in the conversation: the person who
        spoke should read them before the assistant acts on them. */
    _insertText(text) {
        const input = this.inputRef.el;
        if (!input) {
            return;
        }
        const existing = input.value.trim();
        input.value = existing ? `${existing} ${text}` : text;
        this.props.onInput(input.value);
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
    },
});
