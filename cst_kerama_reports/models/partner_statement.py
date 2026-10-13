from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

# Both directions live on the same card: a supplier we prepaid owes us, a
# customer we over-invoiced is owed by us. Reading only one account type would
# hide exactly the cases the accountants go looking for.
COUNTERPARTY_ACCOUNTS = ("liability_payable", "asset_receivable")


class CstPartnerStatement(models.AbstractModel):
    """Running account of a counterparty, per company and per currency.

    Two reports are built on this: *harakati* (one line per counterparty, the
    opening balance, the turnover of the period and the closing balance) and
    *akt sverkasi* (one line per document, with the balance before and after
    it). They are the same arithmetic looked at from two distances, so they
    share the engine.

    Sign convention, once, so nothing downstream has to think about debit and
    credit: an amount is the ``amount_currency`` of the journal item, and a
    balance above zero means **haqqimiz** — the counterparty owes us — while a
    balance below zero means **qarzimiz**. A debit movement is money leaving
    us (*chiqim*), a credit movement is value arriving (*kirim*).
    """

    _name = "cst.partner.statement"
    _description = "Counterparty Running Account"

    # ------------------------------------------------------------------
    # Who counts as what
    # ------------------------------------------------------------------
    @api.model
    def partner_domain(self, kind):
        """Ta'minotchi, 3-shaxs or mijoz, decided from Odoo's own ranks.

        The ranks are maintained by Odoo itself as documents are confirmed, so
        no one has to tag a counterparty by hand. A *3-shaxs* is what is left:
        someone the company owes or is owed by without ever having sold to or
        bought from them — founders, staff advances, loans.
        """
        if kind == "supplier":
            return [("supplier_rank", ">", 0)]
        if kind == "third_party":
            return [("supplier_rank", "=", 0), ("customer_rank", "=", 0)]
        if kind == "customer":
            return [("customer_rank", ">", 0)]
        return []

    @api.model
    def kind_label(self, kind):
        return {
            "supplier": _("Ta'minotchilar"),
            "third_party": _("3-shaxslar"),
            "customer": _("Mijozlar"),
        }.get(kind, _("Kontragentlar"))

    # ------------------------------------------------------------------
    # Reading the journal
    # ------------------------------------------------------------------
    @api.model
    def _base_domain(self, partners, company_ids):
        return [
            ("parent_state", "=", "posted"),
            ("partner_id", "in", partners.ids),
            ("account_id.account_type", "in", COUNTERPARTY_ACCOUNTS),
            ("company_id", "in", company_ids),
            # an order counts from its own document (see _doc_rows); its
            # invoices and credit notes would count it a second time
            ("move_id", "not in", self._order_linked_moves(company_ids)),
        ]

    @api.model
    def _order_linked_moves(self, company_ids):
        """Invoices, bills and credit notes made from a sales or purchase order."""
        self.env.cr.execute("""
            SELECT DISTINCT l.move_id
              FROM account_move_line l
              JOIN account_move m ON m.id = l.move_id
             WHERE m.company_id = ANY(%s)
               AND m.move_type IN ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')
               AND (l.purchase_line_id IS NOT NULL
                    OR EXISTS (SELECT 1 FROM sale_order_line_invoice_rel r
                                WHERE r.invoice_line_id = l.id))
        """, [list(company_ids)])
        return [r[0] for r in self.env.cr.fetchall()]

    @api.model
    def _companies(self, company_ids=None):
        allowed = self.env.companies
        if company_ids:
            wanted = allowed.filtered(lambda c: c.id in company_ids)
            if wanted:
                return wanted
        return allowed

    @api.model
    def _resolve_partners(self, kind, partner_ids=None):
        Partner = self.env["res.partner"]
        if partner_ids:
            return Partner.browse(partner_ids).exists()
        return Partner.search(self.partner_domain(kind), order="complete_name")

    # ------------------------------------------------------------------
    # «Ta'minotchilar / 3-shaxslar harakati»
    # ------------------------------------------------------------------
    @api.model
    def movement_rows(self, kind, date_from, date_to, partner_ids=None,
                      company_ids=None, hide_empty=True):
        """One row per counterparty per currency, grouped by company."""
        partners = self._resolve_partners(kind, partner_ids)
        companies = self._companies(company_ids)
        if not partners or not companies:
            return []

        Line = self.env["account.move.line"].sudo()
        base = self._base_domain(partners, companies.ids)

        opening = self._sum_by(Line, base + [("date", "<", date_from)])
        period = self._sum_by(
            Line, base + [("date", ">=", date_from), ("date", "<=", date_to)],
            split_direction=True)
        # sales and purchase orders, invoiced or not
        pending_total = {}
        pending_due = {}
        for row in self._doc_rows(partners, companies.ids, date_to):
            key = (row["company_id"], row["partner_id"], row["currency_id"])
            if row["date"] < date_from:
                bucket = opening.setdefault(key, {"amount": 0.0, "debit": 0.0, "credit": 0.0})
            else:
                bucket = period.setdefault(key, {"amount": 0.0, "debit": 0.0, "credit": 0.0})
                if row["amount"] < 0:
                    bucket["credit"] += -row["amount"]
                else:
                    bucket["debit"] += row["amount"]
            bucket["amount"] += row["amount"]
            if row.get("uninvoiced"):
                if row["amount"] < 0:
                    pending_total[key] = pending_total.get(key, 0.0) + row["uninvoiced"]
                else:
                    pending_due[key] = pending_due.get(key, 0.0) + row["uninvoiced"]

        keys = set(opening) | set(period)
        result = []
        for company in companies:
            company_rows = []
            for partner in partners:
                currency_rows = []
                for currency in self._currencies_of(keys, company, partner):
                    key = (company.id, partner.id, currency.id)
                    opened = opening.get(key, {}).get("amount", 0.0)
                    moved = period.get(key, {})
                    inflow = moved.get("credit", 0.0)
                    outflow = moved.get("debit", 0.0)
                    closed = opened - inflow + outflow
                    if hide_empty and not any((opened, inflow, outflow, closed)):
                        continue
                    currency_rows.append({
                        "currency": currency,
                        "currency_name": currency.currency_unit_label or currency.name,
                        "open_we_owe": -opened if opened < 0 else 0.0,
                        "open_they_owe": opened if opened > 0 else 0.0,
                        "inflow": inflow,
                        "outflow": outflow,
                        "close_we_owe": -closed if closed < 0 else 0.0,
                        "close_they_owe": closed if closed > 0 else 0.0,
                        "pending": pending_total.get(key, 0.0),
                        "pending_due": pending_due.get(key, 0.0),
                    })
                if currency_rows:
                    company_rows.append({"partner": partner, "currencies": currency_rows})
            if company_rows:
                result.append({"company": company, "partners": company_rows})
        return result

    @api.model
    def _sum_by(self, Line, domain, split_direction=False):
        """``{(company, partner, currency): {...}}`` from one read.

        Aggregating in Python rather than asking the database once per
        direction: the journal items of a counterparty are counted in
        thousands here, and a single read keeps the query count flat however
        many counterparties the report covers.
        """
        out = {}
        for row in Line.search_read(
                domain, ["company_id", "partner_id", "currency_id", "amount_currency"]):
            key = (row["company_id"][0], row["partner_id"][0], row["currency_id"][0])
            entry = out.setdefault(key, {"amount": 0.0, "debit": 0.0, "credit": 0.0})
            amount = row["amount_currency"] or 0.0
            entry["amount"] += amount
            if split_direction:
                if amount >= 0:
                    entry["debit"] += amount
                else:
                    entry["credit"] += -amount
        return out

    @api.model
    def _currencies_of(self, keys, company, partner):
        ids = [k[2] for k in keys if k[0] == company.id and k[1] == partner.id]
        return self.env["res.currency"].browse(sorted(set(ids)))

    # ------------------------------------------------------------------
    # «Akt sverka» — the counterparty card
    # ------------------------------------------------------------------
    @api.model
    def statement_rows(self, partner, date_from, date_to, company_ids=None):
        """Document by document, with the balance before and after each."""
        companies = self._companies(company_ids)
        if not companies:
            return []
        Line = self.env["account.move.line"].sudo()
        base = self._base_domain(partner, companies.ids)

        result = []
        for company in companies:
            in_company = [("company_id", "=", company.id)]
            lines = Line.search(
                base + in_company + [("date", ">=", date_from), ("date", "<=", date_to)],
                order="currency_id, date, id")
            opening = self._sum_by(Line, base + in_company + [("date", "<", date_from)])
            entries = [{"date": line.date, "currency_id": line.currency_id.id,
                        "amount": line.amount_currency or 0.0, "label": self._line_label(line),
                        "move_id": line.move_id.id, "pending": False, "order": (0, line.id)}
                       for line in lines]
            for row in self._doc_rows(partner, [company.id], date_to):
                if row["date"] < date_from:
                    key = (company.id, partner.id, row["currency_id"])
                    bucket = opening.setdefault(key, {"amount": 0.0, "debit": 0.0, "credit": 0.0})
                    bucket["amount"] += row["amount"]
                else:
                    entries.append(dict(row, move_id=False, pending=False, order=(1, row["move"])))
            entries.sort(key=lambda e: (e["date"], e["order"]))
            currency_ids = sorted({e["currency_id"] for e in entries}
                                  | {k[2] for k in opening})
            currency_blocks = []
            for currency in self.env["res.currency"].browse(currency_ids):
                key = (company.id, partner.id, currency.id)
                balance = opening.get(key, {}).get("amount", 0.0)
                block_lines = []
                inflow = outflow = 0.0
                opened = balance
                for line in (e for e in entries if e["currency_id"] == currency.id):
                    amount = line["amount"]
                    before = balance
                    balance += amount
                    if amount >= 0:
                        outflow += amount
                    else:
                        inflow += -amount
                    block_lines.append({
                        "date": line["date"],
                        "label": line["label"],
                        "move_id": line["move_id"],
                        "pending": line["pending"],
                        "before_we_owe": -before if before < 0 else 0.0,
                        "before_they_owe": before if before > 0 else 0.0,
                        "inflow": -amount if amount < 0 else 0.0,
                        "outflow": amount if amount > 0 else 0.0,
                        "after_we_owe": -balance if balance < 0 else 0.0,
                        "after_they_owe": balance if balance > 0 else 0.0,
                    })
                if not block_lines and not opened:
                    continue
                currency_blocks.append({
                    "currency": currency,
                    "currency_name": currency.currency_unit_label or currency.name,
                    "open_we_owe": -opened if opened < 0 else 0.0,
                    "open_they_owe": opened if opened > 0 else 0.0,
                    "inflow": inflow,
                    "outflow": outflow,
                    "close_we_owe": -balance if balance < 0 else 0.0,
                    "close_they_owe": balance if balance > 0 else 0.0,
                    "lines": block_lines,
                })
            if currency_blocks:
                result.append({"company": company, "currencies": currency_blocks})
        return result

    # ------------------------------------------------------------------
    # The orders themselves
    # ------------------------------------------------------------------
    @api.model
    def _doc_rows(self, partners, company_ids, date_to=None):
        """Confirmed sales and purchase orders, valued from the order itself.

        A client owes the order total from the day the order is confirmed and
        we owe a supplier from the day the purchase order is confirmed --
        whether or not anyone has made the invoice or the bill yet. The
        invoices of an order are left out of the journal part of the report
        (:meth:`_base_domain`), so nothing is counted twice. A credit note
        that is a real return (more than a quantity correction of the order)
        comes back as its own line, on its own date.
        """
        rows = []
        limit = date_to and fields.Date.to_date(date_to)
        Sale = self.env["sale.order"].sudo()
        for order in Sale.search([
                ("state", "=", "sale"), ("company_id", "in", list(company_ids)),
                ("partner_id.commercial_partner_id", "in", partners.ids)], order="date_order, id"):
            day = fields.Datetime.context_timestamp(self, order.date_order).date()
            if limit and day > limit:
                continue
            uninvoiced = 0.0
            for line in order.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty):
                unit = line.price_total / line.product_uom_qty
                # a credit note without an invoice makes qty_invoiced negative
                uninvoiced += min(max(line.product_uom_qty - line.qty_invoiced, 0.0),
                                  line.product_uom_qty) * unit
            rows.append(self._doc_row(
                order, day, order.amount_total,
                _("№ %(name)s : Mahsulot sotildi (buyurtma)%(ref)s",
                  name=order.name, ref=(": %s" % order.client_order_ref) if order.client_order_ref else ""),
                uninvoiced=order.currency_id.round(uninvoiced)))
            rows += self._return_rows(order, order.order_line, "out_invoice", "out_refund", 1, limit)
        Purchase = self.env["purchase.order"].sudo()
        for order in Purchase.search([
                ("state", "in", ("purchase", "done")), ("company_id", "in", list(company_ids)),
                ("partner_id.commercial_partner_id", "in", partners.ids)], order="date_order, id"):
            stamp = order.date_approve or order.date_order
            day = fields.Datetime.context_timestamp(self, stamp).date()
            if limit and day > limit:
                continue
            unbilled = 0.0
            for line in order.order_line.filtered(lambda l: not l.display_type and l.product_qty):
                unit = line.price_total / line.product_qty
                unbilled += min(max(line.product_qty - line.qty_invoiced, 0.0),
                                line.product_qty) * unit
            rows.append(self._doc_row(
                order, day, -order.amount_total,
                _("№ %(name)s : Mahsulot olindi (xarid buyurtmasi)%(ref)s",
                  name=order.name, ref=(": %s" % order.partner_ref) if order.partner_ref else ""),
                uninvoiced=order.currency_id.round(unbilled)))
            rows += self._return_rows(order, order.order_line, "in_invoice", "in_refund", -1, limit)
        return rows

    @api.model
    def _doc_row(self, order, day, amount, label, uninvoiced=0.0, key=None):
        return {
            "company_id": order.company_id.id,
            "partner_id": order.partner_id.commercial_partner_id.id,
            "currency_id": order.currency_id.id,
            "date": day,
            "amount": order.currency_id.round(amount),
            "label": label,
            "move": key or order.id,
            "uninvoiced": uninvoiced,
        }

    @api.model
    def _return_rows(self, order, lines, invoice_type, refund_type, sign, limit):
        """Credit notes of an order that give goods (and money) back.

        A credit note that only follows a reduced order quantity (the order
        was invoiced for more than it now holds) is already in the order
        total; only what goes beyond that is a return.
        """
        rows = []
        is_sale = invoice_type == "out_invoice"
        for line in lines.filtered(lambda l: not l.display_type):
            ordered = line.product_uom_qty if is_sale else line.product_qty
            if not ordered:
                continue
            uom = line.product_uom_id
            gross = refunded = 0.0
            refunds = self.env["account.move"]
            for inv_line in line.invoice_lines.filtered(lambda l: l.move_id.state == "posted"):
                qty = inv_line.product_uom_id._compute_quantity(inv_line.quantity, uom)
                if inv_line.move_id.move_type == refund_type:
                    refunded += qty
                    refunds |= inv_line.move_id
                elif inv_line.move_id.move_type == invoice_type:
                    gross += qty
            returned = refunded - max(gross - ordered, 0.0)
            if uom.compare(returned, 0.0) <= 0:
                continue
            last = max(refunds, key=lambda m: (m.invoice_date or m.date, m.id))
            day = last.invoice_date or last.date
            if limit and day > limit:
                continue
            unit = line.price_total / ordered
            rows.append(self._doc_row(
                order, day, -sign * returned * unit,
                _("№ %(refund)s : %(what)s: %(order)s, %(product)s %(qty)s %(uom)s",
                  refund=", ".join(refunds.mapped("name")),
                  what=_("Mahsulot qaytarildi") if is_sale else _("Mahsulot qaytarib berildi"),
                  order=order.name, product=line.product_id.display_name,
                  qty=("%g" % returned), uom=uom.name),
                key=last.id))
        return rows

    # ------------------------------------------------------------------
    # Received / delivered, not yet billed (no longer used by the reports:
    # the orders themselves are counted, see _doc_rows)
    # ------------------------------------------------------------------
    @api.model
    def _pending_rows(self, partners, company_ids, date_to=None):
        return (self._pending_receipts(partners, company_ids, date_to)
                + self._pending_deliveries(partners, company_ids, date_to))

    @api.model
    def _pending_deliveries(self, partners, company_ids, date_to=None):
        """Deliveries from sales orders that no posted client invoice covers yet.

        The mirror of :meth:`_pending_receipts`: the shop ships first and
        invoices when the money comes in (the kassa invoices the order at
        settlement), yet the client owes from the day the goods leave. Per
        order line the posted invoices (less credit notes) cover the earliest
        deliveries; the rest is valued at the order's price with tax, in the
        order's currency, on the delivery's date. Positive: the client owes us.
        """
        Move = self.env["stock.move"].sudo()
        domain = [("state", "=", "done"), ("sale_line_id", "!=", False),
                  ("sale_line_id.order_id.partner_id.commercial_partner_id", "in", partners.ids),
                  ("company_id", "in", list(company_ids)),
                  "|", ("location_dest_id.usage", "=", "customer"),
                  ("location_id.usage", "=", "customer")]
        if date_to:
            domain.append(("date", "<", fields.Datetime.to_datetime(date_to) + relativedelta(days=1)))
        moves = Move.search(domain, order="date, id")
        rows = []
        for so_line in moves.sale_line_id:
            if not so_line.product_uom_qty:
                continue
            uom = so_line.product_uom_id
            invoiced = 0.0
            for inv_line in so_line.invoice_lines.filtered(lambda l: l.move_id.state == "posted"):
                qty = inv_line.product_uom_id._compute_quantity(inv_line.quantity, uom)
                invoiced += -qty if inv_line.move_id.move_type == "out_refund" else qty
            delivered = []
            net = 0.0
            for move in moves.filtered(lambda m: m.sale_line_id == so_line):
                qty = move.product_uom._compute_quantity(move.quantity, uom)
                if move.location_id.usage == "customer":
                    qty = -qty  # returned by the client
                net += qty
                if qty > 0:
                    delivered.append((move, qty))
            left = net - invoiced
            if uom.compare(left, 0.0) <= 0:
                continue
            unit = so_line.price_total / so_line.product_uom_qty
            order = so_line.order_id
            for move, qty in reversed(delivered):
                if uom.compare(left, 0.0) <= 0:
                    break
                take = min(qty, left)
                left -= take
                rows.append({
                    "company_id": so_line.company_id.id,
                    "partner_id": order.partner_id.commercial_partner_id.id,
                    "currency_id": order.currency_id.id,
                    "date": fields.Datetime.context_timestamp(self, move.date).date(),
                    "amount": order.currency_id.round(take * unit),
                    "label": _("№ %(picking)s : Mahsulot sotildi (yuk chiqarildi): %(order)s, "
                               "%(product)s %(qty)s %(uom)s",
                               picking=move.picking_id.name or move.reference or "",
                               order=order.name, product=so_line.product_id.display_name,
                               qty=("%g" % take), uom=uom.name),
                    "move": move.id,
                })
        return rows

    @api.model
    def _pending_receipts(self, partners, company_ids, date_to=None):
        """Receipts from purchase orders that no posted vendor bill covers yet.

        The books only learn of a supplier debt when the bill is posted; the
        shop wants to see it from the day the goods arrive. Per order line the
        posted bills (less refunds) cover the earliest receipts first, so what
        is left unbilled are the latest ones. Each is valued at the order's
        price with tax -- what the bill will ask -- in the order's currency, and
        carries the receipt's date. A bill posted later takes its place.
        """
        Move = self.env["stock.move"].sudo()
        domain = [("state", "=", "done"), ("purchase_line_id", "!=", False),
                  ("purchase_line_id.order_id.partner_id.commercial_partner_id", "in", partners.ids),
                  ("company_id", "in", list(company_ids))]
        if date_to:
            domain.append(("date", "<", fields.Datetime.to_datetime(date_to) + relativedelta(days=1)))
        moves = Move.search(domain, order="date, id")
        rows = []
        for po_line in moves.purchase_line_id:
            if not po_line.product_qty:
                continue
            uom = po_line.product_uom_id
            billed = 0.0
            for inv_line in po_line.invoice_lines.filtered(lambda l: l.move_id.state == "posted"):
                qty = inv_line.product_uom_id._compute_quantity(inv_line.quantity, uom)
                billed += -qty if inv_line.move_id.move_type == "in_refund" else qty
            received = []
            net = 0.0
            for move in moves.filtered(lambda m: m.purchase_line_id == po_line):
                qty = move.product_uom._compute_quantity(move.quantity, uom)
                if move.location_dest_id.usage == "supplier":
                    qty = -qty  # sent back to the supplier
                net += qty
                if qty > 0:
                    received.append((move, qty))
            left = net - billed
            if uom.compare(left, 0.0) <= 0:
                continue
            unit = po_line.price_total / po_line.product_qty
            order = po_line.order_id
            # the unbilled part sits on the latest receipts
            for move, qty in reversed(received):
                if uom.compare(left, 0.0) <= 0:
                    break
                take = min(qty, left)
                left -= take
                rows.append({
                    "company_id": po_line.company_id.id,
                    "partner_id": order.partner_id.commercial_partner_id.id,
                    "currency_id": order.currency_id.id,
                    "date": fields.Datetime.context_timestamp(self, move.date).date(),
                    "amount": -order.currency_id.round(take * unit),
                    "label": _("№ %(receipt)s : Mahsulot olindi — hisob-faktura kutilmoqda: %(order)s, "
                               "%(product)s %(qty)s %(uom)s",
                               receipt=move.picking_id.name or move.reference or "",
                               order=order.name, product=po_line.product_id.display_name,
                               qty=("%g" % take), uom=uom.name),
                    "move": move.id,
                })
        return rows

    # ------------------------------------------------------------------
    @api.model
    def _line_label(self, line):
        """«№ BNK1/2026/00012 : Pul berildi: PAYMENT FOR PAPER…»"""
        move = line.move_id
        parts = []
        if move.name and move.name != "/":
            parts.append("№ %s" % move.name)
        phrase = self.move_phrase(move)
        detail = line.name or move.ref or ""
        head = " : ".join(parts + ([phrase] if phrase else []))
        if detail and detail != phrase:
            return "%s: %s" % (head, detail) if head else detail
        return head or detail

    @api.model
    def move_phrase(self, move):
        """What happened, in the words the company uses on paper."""
        if move.origin_payment_id or move.matched_payment_ids:
            inbound = (move.origin_payment_id.payment_type == "inbound"
                       if move.origin_payment_id else None)
            if inbound is True:
                return _("Pul olindi")
            if inbound is False:
                return _("Pul berildi")
        return {
            "out_invoice": _("Mahsulot sotildi"),
            "out_refund": _("Mahsulot qaytarildi"),
            "in_invoice": _("Mahsulot olindi"),
            "in_refund": _("Mahsulot qaytarib berildi"),
            "entry": _("Buxgalteriya yozuvi"),
        }.get(move.move_type, move.move_type or "")
