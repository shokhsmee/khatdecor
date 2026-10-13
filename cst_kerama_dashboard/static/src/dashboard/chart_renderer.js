/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useEffect, useRef } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";

/**
 * Thin OWL wrapper around a Chart.js canvas.
 * Pass a complete Chart.js config object via the `config` prop; the chart is
 * (re)built whenever that object changes and destroyed on unmount.
 */
export class ChartRenderer extends Component {
    static template = "cst_kerama_dashboard.ChartRenderer";
    static props = {
        config: { type: Object },
        height: { type: Number, optional: true },
    };

    setup() {
        this.canvasRef = useRef("canvas");
        this.chart = null;
        onWillStart(() => loadBundle("web.chartjs_lib"));
        useEffect(
            () => {
                this._render();
                return () => this._destroy();
            },
            () => [this.props.config]
        );
        onWillUnmount(() => this._destroy());
    }

    get style() {
        return `position:relative;height:${this.props.height || 260}px;`;
    }

    _destroy() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
    }

    _render() {
        this._destroy();
        if (!this.canvasRef.el || !this.props.config) {
            return;
        }
        // `Chart` is exposed globally by the web.chartjs_lib bundle.
        // eslint-disable-next-line no-undef
        this.chart = new Chart(this.canvasRef.el, this.props.config);
    }
}
