from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleProductionWizard(models.TransientModel):
    """Step 1 of «Ishlab chiqarishga yuborish»: what the order needs against what
    the warehouse holds. Ticked lines go on to the «Yangi buyurtma» dialog."""

    _name = "cst.sale.production.wizard"
    _description = "Send Sales Order to Production"

    order_id = fields.Many2one("sale.order", required=True, readonly=True, ondelete="cascade")
    warehouse_id = fields.Many2one(related="order_id.warehouse_id")
    line_ids = fields.One2many("cst.sale.production.wizard.line", "wizard_id", string="Products")
    short_count = fields.Integer(compute="_compute_counts")
    selected_count = fields.Integer(compute="_compute_counts")

    @api.depends("line_ids.short_qty", "line_ids.selected")
    def _compute_counts(self):
        for wiz in self:
            wiz.short_count = len(wiz.line_ids.filtered(lambda l: l.short_qty > 0))
            wiz.selected_count = len(wiz.line_ids.filtered("selected"))

    def _cst_fill_lines(self):
        self.ensure_one()
        order = self.order_id
        warehouse = order.warehouse_id
        Production = self.env["mrp.production"].sudo()
        vals = []
        for line in order.order_line.filtered(lambda l: not l.display_type and l.product_id.is_storable):
            product = line.product_id
            uom = product.uom_id
            ordered = line.product_uom_id._compute_quantity(line.product_uom_qty, uom)
            delivered = line.product_uom_id._compute_quantity(line.qty_delivered, uom)
            # stock already reserved for this line's delivery belongs to it; the rest is free stock
            reserved = sum(
                m.product_uom._compute_quantity(m.quantity, uom)
                for m in line.move_ids
                if m.state not in ("done", "cancel") and m.location_dest_id.usage == "customer")
            free = product.with_context(warehouse_id=warehouse.id).free_qty if warehouse else product.free_qty
            productions = Production.search([("sale_line_id", "=", line.id), ("state", "not in", ("done", "cancel"))])
            in_production = sum(p.product_uom_id._compute_quantity(p.product_qty - p.qty_produced, uom)
                                for p in productions)
            bom = self.env["mrp.bom"].sudo()._bom_find(product, company_id=order.company_id.id).get(product)
            to_deliver = max(ordered - delivered, 0.0)
            short = max(to_deliver - reserved - free - in_production, 0.0)
            vals.append({
                "wizard_id": self.id,
                "sale_line_id": line.id,
                "product_id": product.id,
                "uom_id": uom.id,
                "ordered_qty": ordered,
                "delivered_qty": delivered,
                "stock_qty": reserved + free,
                "production_qty": in_production,
                "short_qty": short,
                "has_bom": bool(bom),
                "qty_to_produce": short,
                "selected": bool(bom) and uom.compare(short, 0.0) > 0,
            })
        self.env["cst.sale.production.wizard.line"].create(vals)

    def action_send(self):
        """Hand the ticked lines to the «Yangi buyurtma» dialog, one product at a time."""
        self.ensure_one()
        lines = self.line_ids.filtered("selected")
        if not lines:
            raise UserError(_("Tick at least one product to send to production."))
        rows, index = [], {}
        for line in lines:
            if not line.has_bom:
                raise UserError(_("%(product)s has no bill of materials, it cannot be manufactured.",
                                  product=line.product_id.display_name))
            if line.qty_to_produce <= 0:
                raise UserError(_("Enter the quantity to produce for %(product)s.",
                                  product=line.product_id.display_name))
            product = line.product_id
            if product.id in index:  # the dialog lists a product once
                rows[index[product.id]]["qty"] += line.qty_to_produce
                continue
            index[product.id] = len(rows)
            rows.append({
                "product_id": product.id,
                "name": product.cst_base_name(),
                "characteristic": product.cst_characteristic or "",
                "qty": line.qty_to_produce,
                "uom": line.uom_id.name,
            })
        return {
            "type": "ir.actions.client",
            "tag": "cst_sale_mo_dialog",
            "params": {"order_id": self.order_id.id, "order_name": self.order_id.name, "rows": rows},
        }


class SaleProductionWizardLine(models.TransientModel):
    _name = "cst.sale.production.wizard.line"
    _description = "Send to Production: Product Line"

    wizard_id = fields.Many2one("cst.sale.production.wizard", required=True, ondelete="cascade")
    sale_line_id = fields.Many2one("sale.order.line", readonly=True)
    product_id = fields.Many2one("product.product", string="Product", readonly=True)
    uom_id = fields.Many2one("uom.uom", string="Unit", readonly=True)
    ordered_qty = fields.Float(string="Ordered", digits="Product Unit of Measure", readonly=True)
    delivered_qty = fields.Float(string="Delivered", digits="Product Unit of Measure", readonly=True)
    stock_qty = fields.Float(string="In stock", digits="Product Unit of Measure", readonly=True,
                             help="Reserved for this order + free stock in the order's warehouse.")
    production_qty = fields.Float(string="In production", digits="Product Unit of Measure", readonly=True,
                                  help="Still to be made on manufacturing orders already sent for this line.")
    short_qty = fields.Float(string="Short", digits="Product Unit of Measure", readonly=True)
    has_bom = fields.Boolean(string="Bill of materials", readonly=True)
    status = fields.Selection(
        [("ok", "In stock"), ("production", "In production"), ("short", "Short"), ("no_bom", "No bill of materials")],
        compute="_compute_status")
    selected = fields.Boolean(string="Send")
    qty_to_produce = fields.Float(string="To produce", digits="Product Unit of Measure")

    @api.depends("short_qty", "production_qty", "has_bom")
    def _compute_status(self):
        for line in self:
            if line.short_qty > 0:
                line.status = "short" if line.has_bom else "no_bom"
            elif line.production_qty > 0:
                line.status = "production"
            else:
                line.status = "ok"
