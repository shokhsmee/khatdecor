from odoo import _, fields, http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.cst_kerama_sale_receipt.tools import receipt_logo, receipt_money

from ..models.dispatch import GROUP_GATE, GROUP_WH


class KeramaDispatchWaybill(http.Controller):

    @http.route("/kerama/dispatch/waybill/<int:dispatch_id>", type="http", auth="user")
    def dispatch_waybill(self, dispatch_id, size="80", **kw):
        user = request.env.user
        if not (user.has_group(GROUP_WH) or user.has_group(GROUP_GATE)):
            raise AccessError(_("Bu amal uchun huquqingiz yo'q."))
        dispatch = request.env["cst.dispatch"]._cst_get(dispatch_id)
        template = "cst_kerama_dispatch.waybill_a4" if size == "a4" \
            else "cst_kerama_dispatch.waybill_80"
        return request.render(template, waybill_values(request.env, dispatch))


def _qty(value):
    return ("%.3f" % (value or 0.0)).rstrip("0").rstrip(".")


def waybill_values(env, dispatch):
    """Lines that leave (or are about to leave) the warehouse, with prices."""
    final = "checked_qty" if dispatch.state == "done" else "qty"
    order = dispatch.sale_order_id
    rows, total_qty, total_sum = [], 0.0, 0.0
    for line in dispatch.line_ids.sorted(lambda l: (l.sequence, l.id)):
        qty = line[final]
        if not qty:
            continue
        price = dispatch._cst_price(line)
        rows.append({
            "no": len(rows) + 1,
            "name": line.product_id.display_name,
            "char": line.product_id.cst_characteristic or "",
            "code": line.product_id.default_code or "",
            "barcode": line.product_id.barcode or "",
            "qty": _qty(qty),
            "uom": line.uom_id.name or "",
            "price": receipt_money(env, price),
            "subtotal": receipt_money(env, price * qty),
            "extra": line.is_extra,
        })
        total_qty += qty
        total_sum += price * qty
    now = fields.Datetime.context_timestamp(dispatch, fields.Datetime.now())
    stamp = dispatch.checked_at or dispatch.prepared_at
    stamp = fields.Datetime.context_timestamp(dispatch, stamp) if stamp else now
    partner = dispatch.partner_id
    return {
        "dispatch": dispatch,
        "order": order,
        "company": dispatch.company_id,
        "partner": partner,
        "partner_phone": partner.phone or getattr(partner, "mobile", "") or "",
        "partner_address": partner.contact_address and partner.contact_address.strip() or "",
        "logo": receipt_logo(dispatch.company_id),
        "receipt_title": _("Yuk xati %s", dispatch.name),
        "date": stamp.strftime("%d.%m.%Y %H:%M"),
        "printed_at": now.strftime("%d.%m.%Y %H:%M"),
        "rows": rows,
        "total_qty": _qty(total_qty),
        "total_sum": receipt_money(env, total_sum),
        "currency_label": order.currency_id.symbol or order.currency_id.name,
        "state_label": dict(dispatch._fields["state"].selection)[dispatch.state],
        "draft": dispatch.state != "done",
    }
