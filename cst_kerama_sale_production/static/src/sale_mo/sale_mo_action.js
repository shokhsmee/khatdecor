import { registry } from "@web/core/registry";
import { CstMoDialog } from "@cst_kerama_shift/mo_builder/mo_dialog";

/**
 * «Ishlab chiqarishga yuborish», step 2: the shared «Yangi buyurtma» dialog,
 * once per product the wizard ticked. After an order is raised the dialog
 * reopens with what is left, until every product has been sent.
 */
function openNext(env, orderId, orderName, rows) {
    if (!rows.length) {
        env.services.action.doAction({ type: "ir.actions.client", tag: "soft_reload" });
        return;
    }
    const spec = (method) => ({ model: "sale.order", method, args: [[orderId]] });
    env.services.dialog.add(CstMoDialog, {
        title: "Ishlab chiqarishga yuborish",
        subtitle: `${orderName} · qolgan: ${rows.length} ta mahsulot`,
        planTitle: "Buyurtma bo'yicha ishlab chiqarish kerak",
        plan: rows,
        defaults: { product_id: rows[0].product_id, qty: rows[0].qty },
        optionsCall: spec("cst_sp_options"),
        previewCall: spec("cst_sp_preview"),
        createCall: spec("cst_sp_create"),
        searchCall: spec("cst_sp_search_products"),
        onCreated: (res) => {
            const done = rows.findIndex((row) => row.product_id === res.product_id);
            const rest = rows.filter((row, i) => i !== (done >= 0 ? done : 0));
            // the dialog closes itself right after this callback
            setTimeout(() => openNext(env, orderId, orderName, rest), 0);
        },
    });
}

async function cstSaleMoDialog(env, action) {
    const { order_id: orderId, order_name: orderName, rows } = action.params || {};
    await env.services.action.doAction({ type: "ir.actions.act_window_close" });
    openNext(env, orderId, orderName || "", rows || []);
}

registry.category("actions").add("cst_sale_mo_dialog", cstSaleMoDialog);
