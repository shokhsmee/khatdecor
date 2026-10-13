import re

from odoo import api, fields, models

# Uzbek subscriber numbers are nine digits; everything before that is the
# country code, and the database has the same person as "907570432" and as
# "+998907570432".  Comparing the last nine digits is what makes those match.
KEY_LENGTH = 9


def phone_key(number):
    """The comparable part of a phone number, or False."""
    digits = re.sub(r"\D", "", number or "")
    return digits[-KEY_LENGTH:] if len(digits) >= KEY_LENGTH else (digits or False)


class ResPartner(models.Model):
    _inherit = "res.partner"

    cst_phone_key = fields.Char(
        string="Phone Key", compute="_compute_cst_phone_key", store=True,
        index="btree_not_null",
        help="Телефон ракамининг охирги 9 та раками.  Бот шу буйича излайди, "
             "чунки базада бир хил ракам турлича ёзилган.")
    cst_telegram_chat_ids = fields.One2many(
        "cst.telegram.chat", "partner_id", string="Telegram")
    cst_telegram_count = fields.Integer(compute="_compute_cst_telegram_count")

    @api.depends("phone")
    def _compute_cst_phone_key(self):
        for partner in self:
            partner.cst_phone_key = phone_key(partner.phone)

    def _compute_cst_telegram_count(self):
        counts = dict(self.env["cst.telegram.chat"]._read_group(
            [("partner_id", "in", self.ids), ("state", "=", "linked")],
            groupby=["partner_id"], aggregates=["__count"]))
        for partner in self:
            partner.cst_telegram_count = counts.get(partner, 0)

    # ------------------------------------------------------------------
    # Who is this
    # ------------------------------------------------------------------
    @api.model
    def _cst_search_by_phone(self, number):
        """Partners whose phone ends the same way.  May legitimately be more
        than one — a shop and its owner share a number here."""
        key = phone_key(number)
        if not key:
            return self.browse()
        return self.search([("cst_phone_key", "=", key)])

    def _cst_roles(self):
        """('customer', 'vendor') as far as this partner is concerned."""
        self.ensure_one()
        commercial = self.commercial_partner_id
        roles = []
        if commercial.customer_rank or self.customer_rank:
            roles.append("customer")
        if commercial.supplier_rank or self.supplier_rank:
            roles.append("vendor")
        return roles

    # ------------------------------------------------------------------
    # The ledger, as the partner sees it
    # ------------------------------------------------------------------
    def _cst_account_types(self, role):
        return ("asset_receivable",) if role == "customer" else ("liability_payable",)

    def _cst_statement_domain(self, role, date_from=None, date_to=None):
        self.ensure_one()
        domain = [
            ("partner_id", "=", self.commercial_partner_id.id),
            ("parent_state", "=", "posted"),
            ("account_id.account_type", "in", self._cst_account_types(role)),
        ]
        if date_from:
            domain.append(("date", ">=", date_from))
        if date_to:
            domain.append(("date", "<=", date_to))
        # invoices made from an order: the order itself is counted instead
        domain.append(("move_id", "not in", self._cst_order_linked_moves()))
        return domain

    def _cst_order_linked_moves(self):
        self.env.cr.execute("""
            SELECT DISTINCT l.move_id
              FROM account_move_line l
              JOIN account_move m ON m.id = l.move_id
             WHERE m.move_type IN ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')
               AND (l.purchase_line_id IS NOT NULL
                    OR EXISTS (SELECT 1 FROM sale_order_line_invoice_rel r
                                WHERE r.invoice_line_id = l.id))
        """)
        return [r[0] for r in self.env.cr.fetchall()]

    def _cst_orders(self, role):
        """Confirmed orders of this partner: the debt is born with the order."""
        model = "sale.order" if role == "customer" else "purchase.order"
        if model not in self.env:
            return self.env["res.partner"].browse()
        states = ("sale",) if role == "customer" else ("purchase", "done")
        return self.env[model].sudo().search([
            ("partner_id.commercial_partner_id", "=", self.commercial_partner_id.id),
            ("state", "in", states)], order="date_order, id")

    def _cst_order_rows(self, role):
        """(date, name, label, company amount) for each order and each return."""
        rows = []
        engine = self.env.get("cst.partner.statement")
        for order in self._cst_orders(role):
            stamp = order.date_order if role == "customer" else (order.date_approve or order.date_order)
            rate = order.currency_rate or 1.0
            rows.append((fields.Datetime.context_timestamp(self, stamp).date(), order.name,
                         order.client_order_ref if role == "customer" else (order.partner_ref or ""),
                         order.amount_total / rate))
            if engine is not None:
                kind = ("out_invoice", "out_refund", 1) if role == "customer" else ("in_invoice", "in_refund", -1)
                for ret in engine._return_rows(order, order.order_line, kind[0], kind[1], kind[2], None):
                    # engine: + = they owe us; here + = owed in the role's own direction
                    amount = ret["amount"] if role == "customer" else -ret["amount"]
                    rows.append((ret["date"], "", ret["label"], amount / rate))
        return rows

    def _cst_statement(self, role, date_from=None, date_to=None, limit=40):
        """Акт сверка: opening balance, the movements, closing balance.

        Signed so that a positive figure always means "owed to the company"
        for a customer and "owed by the company" for a supplier — the reader
        should never have to think about debit and credit.
        """
        self.ensure_one()
        sign = 1 if role == "customer" else -1
        Line = self.env["account.move.line"].sudo()

        opening = 0.0
        order_rows = self._cst_order_rows(role)
        if date_from:
            groups = Line._read_group(
                self._cst_statement_domain(role, date_to=None) +
                [("date", "<", date_from)],
                aggregates=["balance:sum"])
            opening = sign * (groups[0][0] or 0.0)
            opening += sum(r[3] for r in order_rows if r[0] < date_from)

        lines = Line.search(
            self._cst_statement_domain(role, date_from, date_to),
            order="date, id")
        entries = [(line.date, line.move_id.name or "", line.name or line.move_id.ref or "",
                    sign * line.balance, line.id) for line in lines]
        entries += [(r[0], r[1], r[2], r[3], 0) for r in order_rows
                    if (not date_from or r[0] >= date_from) and (not date_to or r[0] <= date_to)]
        entries.sort(key=lambda e: (e[0], e[4]))
        movements = []
        debit = credit = 0.0
        for date, name, label, amount, _id in entries:
            if amount >= 0:
                debit += amount
            else:
                credit += -amount
            movements.append({
                "date": date,
                "name": name,
                "label": label or "",
                "amount": amount,
                "company": "",
            })
        return {
            "role": role,
            "currency": self.env.company.currency_id,
            "opening": opening,
            "movements": movements[-limit:],
            "truncated": max(0, len(movements) - limit),
            "charged": debit,
            "paid": credit,
            "closing": opening + debit - credit,
        }

    def _cst_open_documents(self, role):
        """What is still unpaid: orders (invoiced or not) and invoices / bills
        typed without an order. A list of dicts: name, due, residual, currency."""
        self.ensure_one()
        docs = []
        for order in self._cst_orders(role):
            if role == "customer":
                due_amount = order.payment_amount_due if "payment_amount_due" in order._fields \
                    else order.amount_total
            else:
                # a supplier order is open until its bills are made (bills are paid in Kassa)
                due_amount = 0.0 if order.invoice_status == "invoiced" else order.amount_total
            if order.currency_id.compare_amounts(due_amount, 0.0) > 0:
                docs.append({"name": order.name, "due": order.date_order.date(),
                             "residual": due_amount, "currency": order.currency_id})
        for move in self._cst_open_moves(role).filtered(
                lambda m: m.id not in self._cst_order_linked_moves()):
            docs.append({"name": move.name, "due": move.invoice_date_due,
                         "residual": move.amount_residual, "currency": move.currency_id})
        return docs

    def _cst_open_moves(self, role):
        self.ensure_one()
        move_types = ("out_invoice", "out_refund") if role == "customer" \
            else ("in_invoice", "in_refund")
        moves = self.env["account.move"].sudo().search([
            ("partner_id", "=", self.commercial_partner_id.id),
            ("move_type", "in", move_types),
            ("state", "=", "posted"),
            ("payment_state", "not in", ("paid", "reversed", "invoicing_legacy")),
        ], order="invoice_date_due, id")
        return moves
