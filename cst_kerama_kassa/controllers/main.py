from odoo import fields, http
from odoo.http import request

from odoo.addons.cst_kerama_sale_receipt.tools import receipt_logo, receipt_money

# The check is customer-facing and fixed Uzbek, like the sales check.
_TYPE_LABELS = {
    "customer_in": "Mijozdan to'lov",
    "supplier_in": "Ta'minotchidan qaytim",
    "other_in": "Boshqa kirim",
    "customer_out": "Mijozga qaytarish",
    "supplier_out": "Ta'minotchiga to'lov",
    "expense": "Xarajat",
    "employee_advance": "Xodimga avans",
    "transfer_in": "Boshqa kassadan kirim",
    "transfer_out": "Boshqa kassaga o'tkazma",
}


class KassaReceipt(http.Controller):

    @http.route("/kerama/kassa/receipt/<int:op_id>", type="http", auth="user", website=False)
    def kassa_receipt(self, op_id, **kw):
        op = request.env["cst.kassa.operation"].browse(op_id).exists()
        if not op:
            return request.not_found()
        op.check_access("read")

        return request.render("cst_kerama_kassa.kassa_receipt_document",
                              kassa_receipt_values(request.env, op))


def kassa_receipt_values(env, op):
    """Everything the kassa check template needs (also used to preview it from a shell)."""
    company = op.company_id
    company_ccy = company.currency_id.symbol or company.currency_id.name
    posted = fields.Datetime.context_timestamp(op, op.posted_at or op.create_date)
    now = fields.Datetime.context_timestamp(op, fields.Datetime.now())

    allocations = [{
        "name": a.order_id.name or a.invoice_id.name,
        "amount": receipt_money(env, a.amount),
    } for a in op.sudo().allocation_ids.filtered(lambda a: a.state == "done")]

    advance_left = None
    if op.operation_type == "customer_in" and op.state == "done" and op.unallocated_amount > 0:
        advance_left = receipt_money(env, op.unallocated_amount)

    figures = None
    if op.partner_id and op.operation_type in ("customer_in", "customer_out"):
        fig = env["cst.kassa.partner.balance"]._cst_figures(op.partner_id.commercial_partner_id, company)
        figures = {"debt": receipt_money(env, fig["total_debt"]),
                   "advance": receipt_money(env, fig["advance"])}

    return {
        "op": op,
        "company": company,
        "logo": receipt_logo(company),
        "receipt_title": op.name,
        "thanks": "To'lovingiz uchun rahmat!" if op.operation_type == "customer_in" else False,
        "title": "KIRIM CHEKI" if op.direction == "in" else "CHIQIM CHEKI",
        "posted": posted.strftime("%d.%m.%Y %H:%M"),
        "now": now.strftime("%d.%m.%Y %H:%M"),
        "type_label": _TYPE_LABELS.get(op.operation_type, ""),
        "amount": receipt_money(env, op.amount),
        "currency_label": op.currency_id.symbol or op.currency_id.name,
        "amount_words": op._cst_amount_words("uz_UZ"),
        "rate": f"{op.rate:,.2f}".replace(",", " ") if op.is_foreign and op.rate else False,
        "amount_company": receipt_money(env, op.amount_company) if op.is_foreign else False,
        "company_ccy": company_ccy,
        "allocations": allocations,
        "advance_left": advance_left,
        "figures": figures,
    }
