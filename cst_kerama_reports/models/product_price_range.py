from odoo import fields, models


class CstProductPriceRange(models.Model):
    """«Mijozlar / ta'minotchilar bilan mahsulot min-max hisoboti».

    The cheapest and the dearest a product ever left for a customer or came in
    from a supplier, per counterparty and per currency, with the quantity and
    the number of documents behind the two figures. Odoo's pivot can sum and
    average but not take a minimum, which is exactly the question here, so the
    aggregate is done in a view and the list groups it the usual way.

    Invoices only: a refund carries the same price as the invoice it corrects,
    so counting it again would widen nothing and would double the quantity.
    """

    _name = "cst.product.price.range"
    _description = "Mahsulot narx oralig'i"
    _auto = False
    _order = "kind, product_id, partner_id"

    kind = fields.Selection(
        [("sale", "Mijozlar bilan"), ("purchase", "Ta'minotchilar bilan")],
        string="Turi", readonly=True)
    product_id = fields.Many2one("product.product", string="Mahsulot", readonly=True)
    cst_characteristic = fields.Char(
        related="product_id.cst_characteristic", string="Xarakteristika", readonly=True,
        help="Har bir xarakteristika alohida sotib olinadi va alohida narxlanadi.")
    partner_id = fields.Many2one("res.partner", string="Kontragent", readonly=True)
    company_id = fields.Many2one("res.company", string="Kompaniya", readonly=True)
    currency_id = fields.Many2one("res.currency", string="Valyuta", readonly=True)
    uom_id = fields.Many2one("uom.uom", string="O'lchov", readonly=True)

    quantity = fields.Float(string="Miqdori", readonly=True)
    min_price = fields.Monetary(string="Eng past narx", currency_field="currency_id",
                                readonly=True)
    max_price = fields.Monetary(string="Eng yuqori narx", currency_field="currency_id",
                                readonly=True)
    avg_price = fields.Monetary(string="O'rtacha narx", currency_field="currency_id",
                                readonly=True)
    spread = fields.Monetary(string="Farqi", currency_field="currency_id", readonly=True)
    amount = fields.Monetary(string="Summasi", currency_field="currency_id",
                             readonly=True)
    doc_count = fields.Integer(string="Hujjatlar soni", readonly=True)
    first_date = fields.Date(string="Birinchi hujjat", readonly=True)
    last_date = fields.Date(string="Oxirgi hujjat", readonly=True)

    @property
    def _table_query(self):
        # Prices come from the documents themselves: confirmed sales and
        # purchase order lines, plus invoice / bill lines that were not made
        # from an order (a bill typed in directly is its own document).
        return """
            WITH linked AS (
                SELECT DISTINCT l.move_id
                  FROM account_move_line l
                 WHERE l.purchase_line_id IS NOT NULL
                    OR EXISTS (SELECT 1 FROM sale_order_line_invoice_rel r
                                WHERE r.invoice_line_id = l.id)
            ), docs AS (
                SELECT 'sale' AS kind, sol.product_id,
                       COALESCE(p.commercial_partner_id, p.id) AS partner_id,
                       so.company_id, so.currency_id, sol.product_uom_id AS uom_id,
                       sol.product_uom_qty AS quantity, sol.price_unit,
                       sol.price_subtotal AS amount, 'so' || so.id AS doc,
                       so.date_order::date AS date
                  FROM sale_order_line sol
                  JOIN sale_order so ON so.id = sol.order_id
                  JOIN res_partner p ON p.id = so.partner_id
                 WHERE so.state = 'sale' AND sol.display_type IS NULL
                   AND sol.product_id IS NOT NULL AND sol.product_uom_qty <> 0
                UNION ALL
                SELECT 'purchase', pol.product_id,
                       COALESCE(p.commercial_partner_id, p.id),
                       po.company_id, po.currency_id, pol.product_uom_id,
                       pol.product_qty, pol.price_unit,
                       pol.price_subtotal, 'po' || po.id,
                       COALESCE(po.date_approve, po.date_order)::date
                  FROM purchase_order_line pol
                  JOIN purchase_order po ON po.id = pol.order_id
                  JOIN res_partner p ON p.id = po.partner_id
                 WHERE po.state IN ('purchase', 'done') AND pol.display_type IS NULL
                   AND pol.product_id IS NOT NULL AND pol.product_qty <> 0
                UNION ALL
                SELECT CASE WHEN am.move_type = 'out_invoice' THEN 'sale' ELSE 'purchase' END,
                       aml.product_id, aml.partner_id, aml.company_id, aml.currency_id,
                       aml.product_uom_id, aml.quantity, aml.price_unit,
                       ABS(aml.amount_currency), 'am' || am.id, aml.date
                  FROM account_move_line aml
                  JOIN account_move am ON am.id = aml.move_id
                 WHERE aml.parent_state = 'posted'
                   AND aml.display_type = 'product'
                   AND aml.product_id IS NOT NULL
                   AND aml.partner_id IS NOT NULL
                   AND am.move_type IN ('out_invoice', 'in_invoice')
                   AND am.id NOT IN (SELECT move_id FROM linked)
            )
            SELECT ROW_NUMBER() OVER (ORDER BY kind, product_id, partner_id,
                                               currency_id, company_id)::int AS id,
                   *
              FROM (
                SELECT kind, product_id, partner_id, company_id, currency_id,
                       MIN(uom_id) AS uom_id,
                       SUM(quantity) AS quantity,
                       MIN(price_unit) AS min_price,
                       MAX(price_unit) AS max_price,
                       CASE WHEN SUM(quantity) <> 0
                            THEN SUM(price_unit * quantity) / SUM(quantity)
                            ELSE MIN(price_unit) END AS avg_price,
                       MAX(price_unit) - MIN(price_unit) AS spread,
                       SUM(amount) AS amount,
                       COUNT(DISTINCT doc)::int AS doc_count,
                       MIN(date) AS first_date,
                       MAX(date) AS last_date
                  FROM docs
                 GROUP BY kind, product_id, partner_id, company_id, currency_id
              ) grouped
        """
