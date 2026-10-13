from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CstMaterialRequest(models.Model):
    _name = "cst.material.request"
    _description = "Material Request (MRF)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(
        string="Reference", required=True, copy=False, readonly=True, default=lambda self: _("New"))
    project_id = fields.Many2one(
        "project.project", string="Project", required=True, index=True, tracking=True,
        domain="[('is_template', '=', False)]")
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company)
    warehouse_id = fields.Many2one(
        "stock.warehouse", string="Warehouse", required=True, tracking=True,
        default=lambda self: self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1))
    requested_by = fields.Many2one(
        "res.users", string="Requested By", default=lambda self: self.env.user, readonly=True)
    approver_id = fields.Many2one("res.users", string="Approved By", readonly=True, copy=False)
    date_request = fields.Date(default=fields.Date.context_today, string="Request Date")
    note = fields.Text(string="Notes")
    state = fields.Selection([
        ("draft", "Draft"),
        ("to_approve", "To Approve"),
        ("approved", "Approved"),
        ("assigned", "Assigned"),
        ("purchased", "RFQs Created"),
        ("done", "Done"),
        ("cancel", "Cancelled"),
    ], default="draft", tracking=True, copy=False)
    line_ids = fields.One2many("cst.material.request.line", "request_id", copy=True)
    purchase_order_ids = fields.Many2many(
        "purchase.order", compute="_compute_purchase_orders", string="Purchase Orders")
    purchase_count = fields.Integer(compute="_compute_purchase_orders")
    production_ids = fields.One2many(
        "mrp.production", "cst_mrf_id", string="Manufacturing Orders", readonly=True)
    production_count = fields.Integer(compute="_compute_production_count")
    buy_line_count = fields.Integer(compute="_compute_line_counts")
    manufacture_line_count = fields.Integer(compute="_compute_line_counts")
    cst_ready_to_manufacture = fields.Boolean(
        string="Ready to Manufacture", compute="_compute_cst_ready_to_manufacture",
        help="Every component of the products still to produce is free in the warehouse.")
    company_currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", readonly=True,
        string="Company Currency")
    currency_id = fields.Many2one(
        "res.currency", string="Currency", required=True,
        compute="_compute_currency_id", store=True, readonly=False, precompute=True,
        domain="[('active', '=', True)]",
        help="Currency the prices of this request are written in. Material "
             "bought in dollars can be estimated in dollars; the figure is "
             "converted to the company currency wherever it is totalled.")
    amount_estimated = fields.Monetary(
        string="Estimated Cost", compute="_compute_amount_estimated",
        currency_field="currency_id",
        help="Indicative value of this request: vendor price (or cost price) "
             "times the quantity still to buy or produce.")
    amount_estimated_company = fields.Monetary(
        string="Estimated Cost (Company)", compute="_compute_amount_estimated",
        currency_field="company_currency_id",
        help="The same estimate read in the company currency.")

    @api.depends("company_id")
    def _compute_currency_id(self):
        for request in self:
            if not request.currency_id:
                request.currency_id = (
                    request.company_id or self.env.company).currency_id

    @api.depends("line_ids.price_subtotal", "currency_id", "date_request")
    def _compute_amount_estimated(self):
        for request in self:
            total = sum(request.line_ids.mapped("price_subtotal"))
            request.amount_estimated = total
            company = request.company_id or self.env.company
            comp_ccy = company.currency_id
            currency = request.currency_id or comp_ccy
            request.amount_estimated_company = total if currency == comp_ccy else \
                currency._convert(total, comp_ccy, company,
                                  request.date_request or fields.Date.context_today(request))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("cst.material.request") or _("New")
        return super().create(vals_list)

    @api.depends("line_ids.purchase_line_id")
    def _compute_purchase_orders(self):
        for request in self:
            orders = request.line_ids.purchase_line_id.order_id
            request.purchase_order_ids = orders
            request.purchase_count = len(orders)

    @api.depends("production_ids")
    def _compute_production_count(self):
        for request in self:
            request.production_count = len(request.production_ids)

    @api.depends("line_ids.kind", "line_ids.qty_to_produce", "line_ids.production_id",
                 "line_ids.cst_components_available", "state")
    def _compute_cst_ready_to_manufacture(self):
        for request in self:
            request.cst_ready_to_manufacture = bool(
                request.state not in ("draft", "cancel", "done")
                and request._cst_manufacture_lines().filtered("cst_components_available"))

    def _cst_manufacture_lines(self):
        """Lines still waiting for a manufacturing order."""
        return self.line_ids.filtered(
            lambda l: l.kind == "manufacture" and l.qty_to_produce > 0 and not l.production_id)

    def action_cst_start_manufacturing(self):
        """Open the wizard that configures the operations, work centers and crews."""
        self.ensure_one()
        return self.env["cst.manufacture.wizard"].cst_open(self._cst_manufacture_lines())

    @api.depends("line_ids.kind")
    def _compute_line_counts(self):
        for request in self:
            request.buy_line_count = len(request.line_ids.filtered(lambda l: l.kind == "buy"))
            request.manufacture_line_count = len(
                request.line_ids.filtered(lambda l: l.kind == "manufacture"))

    # ------------------------------------------------------------------
    #  State machine
    # ------------------------------------------------------------------
    def action_submit(self):
        for request in self:
            if not request.line_ids:
                raise UserError(_("Add at least one line before submitting."))
            request.state = "to_approve"

    def action_approve(self):
        for request in self:
            request.write({"state": "approved", "approver_id": self.env.user.id})

    def action_assign(self):
        """Distribute to purchasers: every line still to buy needs a purchaser."""
        for request in self:
            missing = request.line_ids.filtered(
                lambda l: l.kind == "buy" and l.qty_to_buy > 0 and not l.purchaser_id)
            if missing:
                raise UserError(_(
                    "Assign a purchaser on every line that still needs buying:\n%s",
                    "\n".join(missing.mapped("product_id.display_name"))))
            request.state = "assigned"

    def action_create_rfq(self):
        """Create draft POs from the lines, grouped by (purchaser, vendor)."""
        for request in self:
            lines = request.line_ids.filtered(
                lambda l: l.kind == "buy" and l.qty_to_buy > 0 and not l.purchase_line_id)
            if not lines:
                raise UserError(_("Nothing left to buy on this request."))
            missing_vendor = lines.filtered(lambda l: not l.vendor_id)
            if missing_vendor:
                raise UserError(_(
                    "Set a vendor on these lines first:\n%s",
                    "\n".join(missing_vendor.mapped("product_id.display_name"))))

            groups = defaultdict(lambda: self.env["cst.material.request.line"])
            for line in lines:
                groups[(line.purchaser_id.id, line.vendor_id.id)] |= line

            for (purchaser_id, vendor_id), grp_lines in groups.items():
                po_values = {
                    "partner_id": vendor_id,
                    "user_id": purchaser_id or self.env.user.id,
                    "company_id": request.company_id.id,
                    "origin": f"{request.name} / {request.project_id.name}",
                    "project_id": request.project_id.id,
                    "picking_type_id": request.warehouse_id.in_type_id.id,
                    "order_line": [(0, 0, {
                        "product_id": line.product_id.id,
                        "product_qty": line.qty_to_buy,
                        "product_uom_id": line.product_uom_id.id,
                    }) for line in grp_lines],
                }
                # a request priced in dollars raises a dollar RFQ
                if request.currency_id and request.currency_id != request.company_id.currency_id:
                    po_values["currency_id"] = request.currency_id.id
                po = self.env["purchase.order"].create(po_values)
                for line, po_line in zip(grp_lines, po.order_line):
                    line.purchase_line_id = po_line.id
            request.state = "purchased"

    def action_create_mo(self):
        """Raise a draft manufacturing order for every line to be produced."""
        for request in self:
            lines = request.line_ids.filtered(
                lambda l: l.kind == "manufacture" and l.qty_to_produce > 0 and not l.production_id)
            if not lines:
                raise UserError(_("Nothing left to manufacture on this request."))

            picking_type = self.env["stock.picking.type"].search([
                ("code", "=", "mrp_operation"),
                ("company_id", "=", request.company_id.id),
                ("warehouse_id", "in", (request.warehouse_id.id, False)),
            ], limit=1) or self.env["stock.picking.type"].search([
                ("code", "=", "mrp_operation"),
                ("company_id", "=", request.company_id.id),
            ], limit=1)
            if not picking_type:
                raise UserError(_(
                    "No manufacturing operation type found for company %s.",
                    request.company_id.display_name))

            Production = self.env["mrp.production"].with_company(request.company_id).with_context(
                # keep our project: project_mrp would otherwise reset it from the BoM
                from_project_action=True,
                default_project_id=request.project_id.id,
            )
            for line in lines:
                bom = line.bom_id or self.env["mrp.bom"]._bom_find(
                    line.product_id, company_id=request.company_id.id).get(line.product_id)
                if not bom:
                    raise UserError(_(
                        "No bill of materials found for %s.", line.product_id.display_name))
                mo = Production.create({
                    "product_id": line.product_id.id,
                    "product_qty": line.qty_to_produce,
                    "product_uom_id": line.product_uom_id.id,
                    "bom_id": bom.id,
                    "picking_type_id": picking_type.id,
                    "company_id": request.company_id.id,
                    "project_id": request.project_id.id,
                    "origin": f"{request.name} / {request.project_id.name}",
                    "cst_mrf_line_id": line.id,
                })
                line.production_id = mo.id
            if request.state in ("approved", "assigned"):
                request.state = "purchased"

        return self.action_view_productions()

    def action_view_productions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Manufacturing Orders"),
            "res_model": "mrp.production",
            "view_mode": "list,form",
            "domain": [("id", "in", self.production_ids.ids)],
            "context": {"default_project_id": self.project_id.id, "from_project_action": True},
        }

    def action_done(self):
        self.write({"state": "done"})

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_reset_draft(self):
        self.write({"state": "draft", "approver_id": False})

    def action_view_purchase_orders(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Purchase Orders"),
            "res_model": "purchase.order",
            "view_mode": "list,form",
            "domain": [("id", "in", self.purchase_order_ids.ids)],
        }


class CstMaterialRequestLine(models.Model):
    _name = "cst.material.request.line"
    _description = "Material Request Line"

    request_id = fields.Many2one(
        "cst.material.request", required=True, ondelete="cascade", index=True)
    project_id = fields.Many2one(
        related="request_id.project_id", store=True, index=True)
    state = fields.Selection(related="request_id.state", store=True)
    company_id = fields.Many2one(related="request_id.company_id")
    warehouse_id = fields.Many2one(related="request_id.warehouse_id")

    kind = fields.Selection([
        ("buy", "Buy"),
        ("manufacture", "Manufacture"),
    ], default="buy", required=True, string="Supply",
        help="Buy: purchase the shortage from a vendor.\n"
             "Manufacture: produce it in-house from its bill of materials.")
    product_id = fields.Many2one("product.product", required=True)
    cst_characteristic = fields.Char(
        related="product_id.cst_characteristic", string="Xarakteristika",
        help="Variant characteristic of the product asked for. Each characteristic "
             "is bought, produced and counted on its own.")
    product_uom_id = fields.Many2one(
        "uom.uom", string="Unit", compute="_compute_product_uom", store=True, readonly=False)
    product_qty = fields.Float(string="Required Qty", required=True, default=1.0)
    qty_available = fields.Float(
        string="In Stock", compute="_compute_qty_available", compute_sudo=True,
        help="Free-to-use quantity in the request's warehouse.")
    qty_to_buy = fields.Float(
        string="To Buy", compute="_compute_quantities", store=True, readonly=False,
        help="Shortage to purchase. Computed as required minus free stock; adjustable.")
    vendor_id = fields.Many2one(
        "res.partner", string="Vendor",
        compute="_compute_vendor", store=True, readonly=False,
        domain=[("supplier_rank", ">", 0)])
    purchaser_id = fields.Many2one(
        "res.users", string="Purchaser",
        help="Buyer this line is distributed to.")
    purchase_line_id = fields.Many2one(
        "purchase.order.line", string="PO Line", readonly=True, copy=False)
    purchase_order_id = fields.Many2one(
        related="purchase_line_id.order_id", string="Purchase Order", store=True)
    purchase_state = fields.Selection(
        related="purchase_line_id.order_id.state", string="PO Status")
    stock_by_location = fields.Char(
        compute="_compute_stock_by_location", string="Where Is It",
        help="On-hand quantity of this product per internal location.")

    # -- indicative cost ----------------------------------------------------
    currency_id = fields.Many2one(
        related="request_id.currency_id", readonly=True)
    price_unit = fields.Monetary(
        string="Unit Price", compute="_compute_price_unit", store=True, readonly=False,
        currency_field="currency_id",
        help="Vendor price when known, otherwise the product's cost price. Adjustable.")
    price_subtotal = fields.Monetary(
        string="Estimated Cost", compute="_compute_price_subtotal",
        currency_field="currency_id",
        help="Unit price times the quantity still to buy or produce.")
    qty_to_supply = fields.Float(
        string="To Supply", compute="_compute_price_subtotal",
        help="What this line still needs: to buy, or to produce.")

    @api.depends("product_id", "vendor_id", "product_qty", "company_id", "currency_id")
    def _compute_price_unit(self):
        for line in self:
            product = line.product_id
            if not product:
                line.price_unit = 0.0
                continue
            company = line.company_id or self.env.company
            target = line.currency_id or company.currency_id
            today = fields.Date.context_today(line)

            def convert(amount, currency):
                if not amount or not currency or currency == target:
                    return amount
                return currency._convert(amount, target, company, today)

            price = 0.0
            seller = product._select_seller(
                partner_id=line.vendor_id, quantity=line.product_qty or 0.0)
            if seller and seller.price:
                price = convert(seller.price, seller.currency_id or company.currency_id)
            line.price_unit = price or convert(
                product.with_company(company).standard_price or 0.0, company.currency_id)

    @api.depends("price_unit", "qty_to_buy", "qty_to_produce", "kind")
    def _compute_price_subtotal(self):
        for line in self:
            qty = line.qty_to_buy if line.kind == "buy" else line.qty_to_produce
            line.qty_to_supply = qty
            line.price_subtotal = qty * (line.price_unit or 0.0)

    # -- manufacturing side ------------------------------------------------
    bom_id = fields.Many2one(
        "mrp.bom", string="Bill of Materials",
        compute="_compute_bom_id", store=True, readonly=False,
        help="Bill of materials used when this line is manufactured.")
    qty_to_produce = fields.Float(
        string="To Produce", compute="_compute_quantities", store=True, readonly=False,
        help="Quantity to manufacture. Computed as required minus free stock; adjustable.")
    cst_components_available = fields.Boolean(
        string="Components Ready", compute="_compute_cst_components",
        help="The warehouse holds every component this line needs to be produced.")
    cst_missing_components = fields.Char(
        string="Missing Components", compute="_compute_cst_components")
    production_id = fields.Many2one(
        "mrp.production", string="Manufacturing Order", readonly=True, copy=False)
    production_state = fields.Selection(
        related="production_id.state", string="MO Status")
    qty_produced = fields.Float(
        related="production_id.qty_produced", string="Produced")

    @api.depends("product_id")
    def _compute_product_uom(self):
        for line in self:
            line.product_uom_id = line.product_id.uom_id

    def _cst_free_qty(self):
        """Free-to-use stock of this line's product in the request's warehouse."""
        self.ensure_one()
        if not self.product_id:
            return 0.0
        # Odoo 19 stock context key is `warehouse_id`, not `warehouse`.
        return self.product_id.with_context(warehouse_id=self.warehouse_id.id).free_qty

    @api.depends("product_id", "warehouse_id")
    def _compute_qty_available(self):
        for line in self:
            line.qty_available = line._cst_free_qty()

    @api.depends("product_id", "product_qty", "warehouse_id", "kind")
    def _compute_quantities(self):
        for line in self:
            if not line.product_id:
                line.qty_to_buy = line.qty_to_produce = 0.0
                continue
            shortage = max(line.product_qty - line._cst_free_qty(), 0.0)
            line.qty_to_buy = shortage if line.kind == "buy" else 0.0
            line.qty_to_produce = shortage if line.kind == "manufacture" else 0.0

    @api.depends("kind", "product_id", "bom_id", "qty_to_produce", "warehouse_id")
    def _compute_cst_components(self):
        for line in self:
            missing = []
            if line.kind == "manufacture" and line.bom_id and line.qty_to_produce > 0:
                for component, needed in line._cst_component_needs().items():
                    free = component.with_context(
                        warehouse_id=line.warehouse_id.id).free_qty
                    if component.uom_id.compare(free, needed) < 0:
                        missing.append("%s (%s/%s)" % (
                            component.display_name, free, needed))
            line.cst_missing_components = ", ".join(missing)
            line.cst_components_available = bool(
                line.kind == "manufacture" and line.bom_id
                and line.qty_to_produce > 0 and not missing)

    def _cst_component_needs(self):
        """{component: quantity in its own UoM} for this line's quantity to produce."""
        self.ensure_one()
        needs = defaultdict(float)
        if not self.bom_id:
            return needs
        factor = self.product_uom_id._compute_quantity(
            self.qty_to_produce, self.bom_id.product_uom_id) / self.bom_id.product_qty
        for bom_line, data in self.bom_id.explode(self.product_id, factor)[1]:
            component = bom_line.product_id
            needs[component] += bom_line.product_uom_id._compute_quantity(
                data["qty"], component.uom_id)
        return needs

    @api.depends("product_id", "kind", "company_id")
    def _compute_bom_id(self):
        for line in self:
            if line.kind != "manufacture" or not line.product_id:
                line.bom_id = False
                continue
            boms = self.env["mrp.bom"]._bom_find(
                line.product_id, company_id=line.company_id.id or self.env.company.id)
            line.bom_id = boms.get(line.product_id)

    @api.depends("product_id")
    def _compute_vendor(self):
        for line in self:
            seller = line.product_id._select_seller(quantity=line.product_qty or 0.0)
            line.vendor_id = seller.partner_id if seller else (
                line.product_id.seller_ids[:1].partner_id)

    def _compute_stock_by_location(self):
        groups = self.env["stock.quant"]._read_group(
            [("product_id", "in", self.product_id.ids),
             ("location_id.usage", "=", "internal"),
             ("quantity", "!=", 0)],
            groupby=["product_id", "location_id"],
            aggregates=["quantity:sum"])
        per_product = defaultdict(list)
        for product, location, qty in groups:
            per_product[product.id].append("%s: %g" % (location.display_name, qty))
        for line in self:
            line.stock_by_location = " | ".join(per_product.get(line.product_id.id, [])) or _("Nowhere in stock")
