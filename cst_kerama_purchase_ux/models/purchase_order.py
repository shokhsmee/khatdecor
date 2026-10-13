"""What the purchasing desk wants on one screen.

The order is opened before the prices are known — a photo of the supplier's
list or of the loaded truck comes first — and the receipt later adds its own
photos, expenses and the vehicle's plate.  Those are shown back on the order
so nobody has to walk from one document to the other.
"""
from odoo import api, fields, models
from odoo.tools import format_amount


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    cst_car_number = fields.Char(
        string="Transport vositasi raqami", copy=False, tracking=True,
        help="Yuk ortilgan mashina/vagon raqami.  Qabul hujjatiga o'zi o'tadi.")
    cst_photo_ids = fields.Many2many(
        "ir.attachment", "cst_purchase_photo_rel", "order_id", "attachment_id",
        string="Rasmlar", copy=False,
        help="Buyurtma ochilganda yuklanadigan rasmlar — narxlar kiritilishidan "
             "oldin ham.")
    cst_receipt_photo_ids = fields.Many2many(
        "ir.attachment", string="Qabuldagi rasmlar",
        compute="_compute_cst_receipt_data")
    cst_receipt_expense_ids = fields.Many2many(
        "cst.picking.expense", string="Qabul xarajatlari",
        compute="_compute_cst_receipt_data")
    cst_receipt_expense_total = fields.Monetary(
        string="Xarajatlar jami", compute="_compute_cst_receipt_data",
        currency_field="company_currency_id")
    company_currency_id = fields.Many2one(
        related="company_id.currency_id", string="Kompaniya valyutasi")
    cst_photo_count = fields.Integer(compute="_compute_cst_receipt_data")
    # native is_shipped is compute-only; give it a search so it can filter the lists
    is_shipped = fields.Boolean(search="_search_is_shipped")

    def _search_is_shipped(self, operator, value):
        if operator not in ("=", "!="):
            return NotImplemented
        # shipped = has receipts and every one of them is done or cancelled
        self.env.cr.execute("""
            SELECT pol.order_id
              FROM purchase_order_line pol
              JOIN stock_move sm ON sm.purchase_line_id = pol.id
              JOIN stock_picking sp ON sp.id = sm.picking_id
          GROUP BY pol.order_id
            HAVING bool_and(sp.state IN ('done', 'cancel'))
        """)
        shipped_ids = [row[0] for row in self.env.cr.fetchall()]
        positive = (operator == "=") == bool(value)
        return [("id", "in" if positive else "not in", shipped_ids)]

    def cst_get_lines_info(self):
        """Lines of one order for the list view's info popover."""
        self.ensure_one()
        lines = []
        for line in self.order_line:
            if line.display_type:
                lines.append({"section": True, "name": line.name})
                continue
            lines.append({
                "section": False,
                "name": line.product_id.display_name or line.name,
                "qty": "%g" % line.product_qty,
                "uom": line.product_uom_id.name or "",
                "price": format_amount(self.env, line.price_unit, self.currency_id),
                "subtotal": format_amount(self.env, line.price_subtotal, self.currency_id),
            })
        return {
            "lines": lines,
            "total": format_amount(self.env, self.amount_total, self.currency_id),
        }

    @api.depends("picking_ids.cst_photo_ids", "picking_ids.move_line_ids.cst_photo_ids",
                 "picking_ids.cst_expense_ids", "picking_ids.cst_expense_ids.amount_company",
                 "cst_photo_ids")
    def _compute_cst_receipt_data(self):
        for order in self:
            receipts = order.picking_ids.filtered(lambda p: p.picking_type_code == "incoming")
            photos = receipts.cst_photo_ids | receipts.move_line_ids.cst_photo_ids
            expenses = receipts.cst_expense_ids
            order.cst_receipt_photo_ids = photos
            order.cst_receipt_expense_ids = expenses
            order.cst_receipt_expense_total = sum(expenses.mapped("amount_company"))
            order.cst_photo_count = len(order.cst_photo_ids) + len(photos)

    def _prepare_picking(self):
        values = super()._prepare_picking()
        if self.cst_car_number:
            values["cst_car_number"] = self.cst_car_number
        return values

    def write(self, vals):
        result = super().write(vals)
        if "cst_car_number" in vals:
            # a plate typed after confirming still reaches the open receipts
            open_receipts = self.picking_ids.filtered(
                lambda p: p.picking_type_code == "incoming"
                and p.state not in ("done", "cancel"))
            open_receipts.write({"cst_car_number": vals["cst_car_number"]})
        return result


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    # The supplier's invoice often gives only the line total.  Typing it here
    # works the unit price out; Odoo's own subtotal stays a computed field so
    # taxes and the order total recompute the usual way.
    cst_line_total = fields.Monetary(
        string="Summa", compute="_compute_cst_line_total", inverse="_inverse_cst_line_total",
        currency_field="currency_id",
        help="Qator summasi (soliqsiz). Yozilsa birlik narxi = summa / miqdor bo'lib hisoblanadi.")

    @api.depends("price_subtotal")
    def _compute_cst_line_total(self):
        for line in self:
            line.cst_line_total = line.price_subtotal

    def _cst_price_from_total(self, total):
        self.ensure_one()
        qty = self.product_qty
        if not qty:
            return self.price_unit
        discount = (self.discount or 0.0) / 100.0
        gross = qty * (1.0 - discount)
        return total / gross if gross else self.price_unit

    @api.onchange("cst_line_total")
    def _onchange_cst_line_total(self):
        for line in self:
            if line.display_type or not line.product_qty:
                continue
            if line.currency_id.compare_amounts(line.cst_line_total, line.price_subtotal) != 0:
                line.price_unit = line._cst_price_from_total(line.cst_line_total)

    def _inverse_cst_line_total(self):
        # the onchange already set the unit price on screen; this covers imports
        # and API writes, and leaves an unchanged total alone
        for line in self:
            if line.display_type or not line.product_qty:
                continue
            if line.currency_id.compare_amounts(line.cst_line_total, line.price_subtotal) != 0:
                line.price_unit = line._cst_price_from_total(line.cst_line_total)
