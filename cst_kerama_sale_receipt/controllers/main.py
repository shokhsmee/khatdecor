from odoo import fields, http
from odoo.http import request

from ..tools import receipt_logo, receipt_money


class KeramaSaleReceipt(http.Controller):

    @http.route(
        "/kerama/sale/receipt/<int:order_id>",
        type="http",
        auth="user",
        website=False,
    )
    def sale_receipt(self, order_id, **kw):
        # Browse in the user's environment so record rules / access rights apply.
        order = request.env["sale.order"].browse(order_id).exists()
        if not order:
            return request.not_found()
        order.check_access("read")

        return request.render(
            "cst_kerama_sale_receipt.sale_receipt_document",
            sale_receipt_values(request.env, order),
        )


def _characteristic(product):
    """Variant attributes («70 гр», «Глянцевый»): the product name no longer carries them."""
    if not product:
        return ""
    if "cst_characteristic" in product._fields:
        return product.cst_characteristic or ""
    return ", ".join(product.product_template_attribute_value_ids.mapped("name"))


def sale_receipt_values(env, order):
    """Everything the sales check template needs (also used to preview it from a shell)."""
    lines = order.order_line.filtered(lambda l: not l.display_type)
    receipt_lines = [{
        "no": index,
        "name": line.product_id.display_name or line.name,
        "char": _characteristic(line.product_id),
        "qty": "%g" % line.product_uom_qty,
        "price": receipt_money(env, line.price_unit),
        "subtotal": receipt_money(env, line.price_subtotal),
    } for index, line in enumerate(lines, start=1)]

    # payment_amount_due comes from cst_kerama_payment_summary; the receipt
    # must still print when that module is not installed.
    due = order.payment_amount_due if "payment_amount_due" in order._fields else None

    # The receipt wording is fixed Uzbek, so the date is formatted the same
    # way whatever language the printing user happens to be working in.
    order_date = fields.Datetime.context_timestamp(order, order.date_order) \
        if order.date_order else None

    return {
        "order": order,
        "company": order.company_id,
        "logo": receipt_logo(order.company_id),
        "receipt_title": order.name,
        "order_date": order_date and order_date.strftime("%d.%m.%Y") or "",
        "currency_label": order.currency_id.symbol or order.currency_id.name,
        "receipt_lines": receipt_lines,
        "total_qty": "%g" % sum(lines.mapped("product_uom_qty")),
        "amount_tax": receipt_money(env, order.amount_tax),
        "amount_total": receipt_money(env, order.amount_total),
        "amount_due": None if due is None else receipt_money(env, -due),
    }
