from odoo import api, fields, models, tools


class CstPartnerLastOperation(models.Model):
    """«Mijozning oxirgi operatsiyasi kun farqi bilan».

    One row per customer per company: what the last movement on their
    receivable account was, how many days ago that was, and what is still
    outstanding. A database view rather than a stored table, so the figures can
    never drift from the journal, and ``days_idle`` is a real column so the
    list sorts on it the way the paper sheet is read — quietest customer first.
    """

    _name = "cst.partner.last.operation"
    _description = "Mijozning oxirgi operatsiyasi"
    _auto = False
    _order = "days_idle desc"
    _rec_name = "partner_id"

    partner_id = fields.Many2one("res.partner", string="Mijoz nomi", readonly=True)
    company_id = fields.Many2one("res.company", string="Kompaniya", readonly=True)
    currency_id = fields.Many2one("res.currency", string="Valyuta", readonly=True)
    last_date = fields.Date(string="Oxirgi harakat sanasi", readonly=True)
    days_idle = fields.Integer(string="Harakatsiz kun", readonly=True)
    balance = fields.Monetary(string="Qarzdorligi", currency_field="currency_id",
                              readonly=True)
    last_move_id = fields.Many2one("account.move", string="Oxirgi hujjat", readonly=True)
    last_order_id = fields.Many2one("sale.order", string="Oxirgi buyurtma", readonly=True)

    days_display = fields.Char(string="Harakatsiz kun farqi",
                               compute="_compute_days_display")
    last_operation = fields.Char(string="Oxirgi harakat mazmuni",
                                 compute="_compute_last_operation")

    @api.depends("days_idle")
    def _compute_days_display(self):
        """«1 yil 158 kun» — the way the sheet spells out a long silence."""
        for row in self:
            days = row.days_idle or 0
            years, rest = divmod(days, 365)
            if years and rest:
                row.days_display = "%s yil %s kun" % (years, rest)
            elif years:
                row.days_display = "%s yil" % years
            else:
                row.days_display = "%s kun" % rest

    @api.depends("last_move_id", "last_order_id")
    def _compute_last_operation(self):
        """«05.07.2026 Mijozdan pul olindi 1 785 Dollar»"""
        engine = self.env["cst.partner.statement"]
        for row in self:
            order = row.last_order_id.sudo()
            if order:
                date = fields.Datetime.context_timestamp(row, order.date_order).date()
                row.last_operation = "%s %s %s %s %s" % (
                    date.strftime("%d.%m.%Y"), "Mahsulot sotildi", order.name,
                    tools.formatLang(self.env, order.amount_total,
                                     digits=order.currency_id.decimal_places or 2),
                    order.currency_id.currency_unit_label or order.currency_id.name,
                )
                continue
            # sudo: a sales manager may read this sheet without holding
            # accounting rights, and the label is all they get from the move
            move = row.last_move_id.sudo()
            if not move:
                row.last_operation = ""
                continue
            date = fields.Date.to_date(move.date)
            amount = move.currency_id.round(abs(move.amount_total or 0.0))
            row.last_operation = "%s %s %s %s" % (
                date.strftime("%d.%m.%Y") if date else "",
                engine.move_phrase(move),
                tools.formatLang(self.env, amount,
                                 digits=move.currency_id.decimal_places or 2),
                move.currency_id.currency_unit_label or move.currency_id.name,
            )

    # ------------------------------------------------------------------
    # Row actions. The list opens the customer's akt sverka on the name and
    # the document behind the movement on the movement — the two things the
    # accountants do with this sheet all day.
    # ------------------------------------------------------------------
    def action_open_akt_sverka(self):
        self.ensure_one()
        return self.partner_id.action_cst_akt_sverka()

    def action_open_last_document(self):
        self.ensure_one()
        if self.last_order_id:
            return {
                "type": "ir.actions.act_window",
                "res_model": "sale.order",
                "res_id": self.last_order_id.id,
                "view_mode": "form",
                "views": [(False, "form")],
            }
        if not self.last_move_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": self.last_move_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
        }

    @property
    def _table_query(self):
        # Events of a customer: confirmed sales orders (the debt is born with
        # the order, invoiced or not) and every receivable journal item except
        # the invoices / credit notes made from an order, which would count the
        # order a second time. Order totals go to company currency through the
        # rate stored on the order, like the journal's own balance column.
        return """
            WITH linked AS (
                SELECT DISTINCT l.move_id
                  FROM account_move_line l
                  JOIN account_move m ON m.id = l.move_id
                 WHERE m.move_type IN ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')
                   AND (l.purchase_line_id IS NOT NULL
                        OR EXISTS (SELECT 1 FROM sale_order_line_invoice_rel r
                                    WHERE r.invoice_line_id = l.id))
            ), lines AS (
                SELECT aml.id AS seq,
                       aml.partner_id,
                       aml.company_id,
                       aml.date,
                       aml.move_id,
                       NULL::int AS order_id,
                       aml.balance
                  FROM account_move_line aml
                  JOIN account_account acc ON acc.id = aml.account_id
                 WHERE aml.parent_state = 'posted'
                   AND aml.partner_id IS NOT NULL
                   AND acc.account_type = 'asset_receivable'
                   AND aml.move_id NOT IN (SELECT move_id FROM linked)
                UNION ALL
                SELECT so.id AS seq,
                       COALESCE(p.commercial_partner_id, p.id) AS partner_id,
                       so.company_id,
                       so.date_order::date AS date,
                       NULL::int AS move_id,
                       so.id AS order_id,
                       so.amount_total / COALESCE(NULLIF(so.currency_rate, 0), 1) AS balance
                  FROM sale_order so
                  JOIN res_partner p ON p.id = so.partner_id
                 WHERE so.state = 'sale'
            ), totals AS (
                SELECT partner_id, company_id,
                       SUM(balance) AS balance,
                       MAX(date) AS last_date
                  FROM lines
                 GROUP BY partner_id, company_id
            ), newest AS (
                SELECT DISTINCT ON (partner_id, company_id)
                       partner_id, company_id, move_id, order_id
                  FROM lines
                 ORDER BY partner_id, company_id, date DESC, (order_id IS NULL), seq DESC
            )
            SELECT ROW_NUMBER() OVER (ORDER BY t.company_id, t.partner_id)::int AS id,
                   t.partner_id,
                   t.company_id,
                   comp.currency_id,
                   t.last_date,
                   (CURRENT_DATE - t.last_date)::int AS days_idle,
                   t.balance,
                   n.move_id AS last_move_id,
                   n.order_id AS last_order_id
              FROM totals t
              JOIN newest n
                ON n.partner_id = t.partner_id AND n.company_id = t.company_id
              JOIN res_company comp ON comp.id = t.company_id
        """
