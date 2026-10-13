/** @odoo-module **/

import { ProductCard } from "@point_of_sale/app/components/product_card/product_card";
import { patch } from "@web/core/utils/patch";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";


patch(ProductCard.prototype, {
    get formattedPrice() {
        const product = this.props.product;
        if (product) {
            return this.env?.utils?.formatCurrency(product?.list_price);
        }
        return '';
    },

    setup() {
        this._super?.(...arguments);
        this.pos = usePos();
    },
});