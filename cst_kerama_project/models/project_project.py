from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import formatLang

# Sale orders considered "income": confirmed orders.
_SALE_STATES = ("sale",)
# Purchase orders considered committed spend.
_PURCHASE_STATES = ("purchase",)
# Expenses considered committed spend (approved and beyond).
_EXPENSE_STATES = ("approved", "posted", "in_payment", "paid")


class ProjectProject(models.Model):
    _inherit = "project.project"

    cst_currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", readonly=True,
        string="Company Currency",
    )
    cst_display_currency_id = fields.Many2one(
        "res.currency", string="Show Amounts In",
        compute="_compute_cst_display_currency", store=True, readonly=False,
        precompute=True, domain="[('active', '=', True)]",
        help="Currency this project's figures are read in. Every sale order, "
             "purchase and expense is converted into it at the rate of its own "
             "date, so a project sold in dollars and bought in so'm can be read "
             "in either. The accounting itself stays in the company currency.")

    @api.depends("company_id")
    def _compute_cst_display_currency(self):
        for project in self:
            if not project.cst_display_currency_id:
                project.cst_display_currency_id = (
                    project.company_id or self.env.company).currency_id
    cst_income_total = fields.Monetary(
        string="Income", compute="_compute_cst_money", currency_field="cst_display_currency_id",
        help="Total of the project's confirmed sale orders, in the currency chosen under Show Amounts In.",
    )
    cst_amount_paid = fields.Monetary(
        string="Paid", compute="_compute_cst_money", currency_field="cst_display_currency_id",
        help="Amount already received on the project's sale orders.",
    )
    cst_amount_due = fields.Monetary(
        string="Amount Due", compute="_compute_cst_money", currency_field="cst_display_currency_id",
        help="Amount still owed on the project's sale orders.",
    )
    cst_purchase_total = fields.Monetary(
        string="Purchases", compute="_compute_cst_money", currency_field="cst_display_currency_id",
        help="Total of the purchase orders linked to this project, in the currency chosen under Show Amounts In.",
    )
    cst_expense_total = fields.Monetary(
        string="Expenses", compute="_compute_cst_money", currency_field="cst_display_currency_id",
        help="Total of the expenses linked to this project, in the currency chosen under Show Amounts In.",
    )
    cst_margin = fields.Monetary(
        string="Margin", compute="_compute_cst_money", currency_field="cst_display_currency_id",
        help="Income minus purchases minus expenses.",
    )
    cst_income_by_currency = fields.Char(
        string="Income as Invoiced", compute="_compute_cst_money",
        help="What the sale orders themselves say, currency by currency, before "
             "any conversion.")
    cst_cost_by_currency = fields.Char(
        string="Costs as Ordered", compute="_compute_cst_money",
        help="What the purchase orders and expenses themselves say, currency by "
             "currency, before any conversion.")
    cst_sale_count = fields.Integer(compute="_compute_cst_money")
    cst_purchase_count = fields.Integer(compute="_compute_cst_money")
    cst_expense_count = fields.Integer(compute="_compute_cst_money")

    # Rounded, locale-formatted figures for the kanban card, where the full
    # monetary rendering ("125,000,000.00 UZS") is too wide to be readable.
    cst_income_label = fields.Char(compute="_compute_cst_labels", string="Income")
    cst_cost_label = fields.Char(compute="_compute_cst_labels", string="Cost")
    cst_margin_label = fields.Char(compute="_compute_cst_labels", string="Margin")

    @api.depends("cst_income_total", "cst_purchase_total", "cst_expense_total", "cst_margin",
                 "cst_display_currency_id")
    def _compute_cst_labels(self):
        for project in self:
            # a project may have no company (shared across all of them)
            currency = (project.cst_display_currency_id or project.cst_currency_id
                        or self.env.company.currency_id)

            def show(amount):
                # rounding_unit='units' keeps the currency symbol but drops the
                # decimals, which would make the kanban card too wide.
                return formatLang(self.env, amount or 0.0, currency_obj=currency,
                                  rounding_unit="units")

            project.cst_income_label = show(project.cst_income_total)
            project.cst_cost_label = show(project.cst_purchase_total + project.cst_expense_total)
            project.cst_margin_label = show(project.cst_margin)

    cst_mrf_ids = fields.One2many("cst.material.request", "project_id", string="Material Requests")
    cst_mrf_count = fields.Integer(compute="_compute_cst_mrf_count")

    # -- manufacturing ------------------------------------------------------
    cst_production_ids = fields.One2many(
        "mrp.production", "project_id", string="Manufacturing Orders")
    cst_mo_count = fields.Integer(compute="_compute_cst_manufacturing")
    cst_mo_open_count = fields.Integer(
        compute="_compute_cst_manufacturing", string="MOs in Progress")
    cst_qty_planned = fields.Float(
        string="Planned Qty", compute="_compute_cst_manufacturing",
        help="Total quantity the project's manufacturing orders are meant to produce.")
    cst_qty_produced = fields.Float(
        string="Ready Products", compute="_compute_cst_manufacturing",
        help="Quantity already produced by this project's manufacturing orders.")
    cst_qty_consumed = fields.Float(
        string="Used Materials", compute="_compute_cst_manufacturing",
        help="Quantity of components consumed by this project's manufacturing orders.")
    cst_qty_second = fields.Float(
        string="2-sort", compute="_compute_cst_manufacturing",
        help="Ikkinchi toifada chiqqan mahsulot soni: smenalarda kiritilgan 2-sort "
             "va shu buyurtmalarda 2-sort sababi bilan yozilgan hisobdan chiqarishlar.")
    cst_qty_scrap = fields.Float(
        string="Brak", compute="_compute_cst_manufacturing",
        help="Brakka chiqqan mahsulot soni shu loyihaning ishlab chiqarish buyurtmalarida.")
    cst_quality_pct = fields.Float(
        string="1-sort ulushi", compute="_compute_cst_manufacturing",
        help="Chiqarilgan mahsulotning necha foizi birinchi toifa: (jami − 2-sort − brak) / jami.")
    cst_material_cost = fields.Monetary(
        string="Material Cost", compute="_compute_cst_manufacturing",
        currency_field="cst_display_currency_id",
        help="Cost-price value of the components consumed by this project's "
             "manufacturing orders. Shown for information: the money itself is "
             "already counted under Purchases when the material was bought.")

    @api.depends("cst_production_ids.state", "cst_production_ids.qty_produced",
                 "cst_production_ids.move_raw_ids.quantity", "cst_display_currency_id",
                 "cst_production_ids.cst_second_qty", "cst_production_ids.cst_scrap_qty")
    def _compute_cst_manufacturing(self):
        for project in self:
            productions = project.cst_production_ids.filtered(lambda p: p.state != "cancel")
            consumed = 0.0
            for move in productions.move_raw_ids:
                if move.state == "done":
                    consumed += move.quantity
            project.cst_mo_count = len(productions)
            project.cst_mo_open_count = len(
                productions.filtered(lambda p: p.state in ("confirmed", "progress", "to_close")))
            project.cst_qty_planned = sum(productions.mapped("product_qty"))
            project.cst_qty_produced = sum(productions.mapped("qty_produced"))
            project.cst_qty_consumed = consumed
            # what the shifts counted on these orders: second grade and scrap
            second = sum(productions.mapped("cst_second_qty"))
            scrap = sum(productions.mapped("cst_scrap_qty"))
            produced = project.cst_qty_produced
            project.cst_qty_second = second
            project.cst_qty_scrap = scrap
            project.cst_quality_pct = (
                (produced - second - scrap) / produced * 100.0) if produced else 0.0
            # the components are valued in the company currency; the project may
            # be read in another one
            project.cst_material_cost = project._cst_to_display(
                sum(productions.mapped("cst_material_cost")))
    cst_manufacture_ready = fields.Boolean(
        string="Ready to Manufacture", compute="_compute_cst_manufacture_ready",
        help="Everything this project still has to produce can be started right "
             "now: every component is either already in the warehouse or has "
             "been bought and received.")
    cst_manufacture_ready_count = fields.Integer(
        string="Products to Produce", compute="_compute_cst_manufacture_ready")
    cst_manufacture_missing = fields.Char(
        string="Missing Components", compute="_compute_cst_manufacture_ready",
        help="Components the warehouse cannot cover yet, with what is free and "
             "what is needed.")

    cst_mrf_line_ids = fields.One2many(
        "cst.material.request.line", "project_id", string="Materials",
        help="All material lines requested for this project, with stock location and purchase status.")

    @api.depends("cst_mrf_ids")
    def _compute_cst_mrf_count(self):
        for project in self:
            project.cst_mrf_count = len(project.cst_mrf_ids)

    # ------------------------------------------------------------------
    #  Currency
    # ------------------------------------------------------------------
    def _cst_convert(self, amount, currency, target, company=None, date=None):
        """``amount`` read in ``target``, at the rate of ``date``."""
        if not amount or not currency or not target or currency == target:
            return amount
        company = company or self.company_id or self.env.company
        return currency._convert(
            amount, target, company, date or fields.Date.context_today(self))

    def _cst_to_display(self, amount, currency=None, date=None):
        """A company-currency figure read in the project's display currency."""
        self.ensure_one()
        company = self.company_id or self.env.company
        return self._cst_convert(
            amount, currency or company.currency_id,
            self.cst_display_currency_id or company.currency_id, company, date)

    def _cst_currency_label(self, amounts):
        """"1 200 $ + 25 800 000 so'm" -- what the documents themselves say."""
        parts = []
        for currency, amount in sorted(
                amounts.items(), key=lambda kv: -abs(kv[1])):
            if not currency or currency.is_zero(amount):
                continue
            parts.append(formatLang(
                self.env, amount, currency_obj=currency, rounding_unit="units"))
        return " + ".join(parts)

    @api.depends("company_id", "cst_display_currency_id")
    def _compute_cst_money(self):
        SaleOrder = self.env["sale.order"]
        Purchase = self.env["purchase.order"]
        Expense = self.env["hr.expense"]
        for project in self:
            company = project.company_id or self.env.company
            comp_ccy = company.currency_id
            target = project.cst_display_currency_id or comp_ccy
            today = fields.Date.context_today(project)
            # what each document says in its own currency, kept beside the
            # converted totals so nothing is hidden by a rate
            income_raw = defaultdict(float)
            cost_raw = defaultdict(float)

            orders = SaleOrder.search([
                ("project_id", "=", project.id),
                ("state", "in", _SALE_STATES),
            ])
            income = paid = due = 0.0
            for order in orders:
                rate_date = order.date_order and order.date_order.date() or today
                order_ccy = order.currency_id or comp_ccy
                income_raw[order_ccy] += order.amount_total
                income += project._cst_convert(
                    order.amount_total, order_ccy, target, company, rate_date)
                due += project._cst_convert(
                    order.payment_amount_due, order_ccy, target, company, rate_date)
                paid += project._cst_convert(
                    order.amount_total - order.payment_amount_due,
                    order_ccy, target, company, rate_date)

            pos = Purchase.search([
                ("project_id", "=", project.id),
                ("state", "in", _PURCHASE_STATES),
            ])
            purchase_total = 0.0
            for po in pos:
                rate_date = po.date_order and po.date_order.date() or today
                po_ccy = po.currency_id or comp_ccy
                cost_raw[po_ccy] += po.amount_total
                purchase_total += project._cst_convert(
                    po.amount_total, po_ccy, target, company, rate_date)

            expenses = Expense.search([
                ("project_id", "=", project.id),
                ("state", "in", _EXPENSE_STATES),
            ])
            # hr.expense.total_amount is in the currency of the expense's own
            # company, which is not this project's when the project is shared
            # across companies.
            expense_total = 0.0
            for expense in expenses:
                exp_ccy = expense.company_currency_id or comp_ccy
                cost_raw[exp_ccy] += expense.total_amount
                expense_total += project._cst_convert(
                    expense.total_amount, exp_ccy, target, company,
                    expense.date or today)

            project.cst_income_by_currency = project._cst_currency_label(income_raw)
            project.cst_cost_by_currency = project._cst_currency_label(cost_raw)
            project.cst_income_total = income
            project.cst_amount_paid = paid
            project.cst_amount_due = due
            project.cst_purchase_total = purchase_total
            project.cst_expense_total = expense_total
            project.cst_margin = income - purchase_total - expense_total
            project.cst_sale_count = len(orders)
            project.cst_purchase_count = len(pos)
            project.cst_expense_count = len(expenses)

    # ------------------------------------------------------------------
    #  Smart buttons
    # ------------------------------------------------------------------
    def action_cst_view_sales(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Sales"),
            "res_model": "sale.order",
            "view_mode": "list,form",
            "domain": [("project_id", "=", self.id)],
            "context": {"default_project_id": self.id},
        }

    def action_cst_view_purchases(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Purchases"),
            "res_model": "purchase.order",
            "view_mode": "list,form",
            "domain": [("project_id", "=", self.id)],
            "context": {"default_project_id": self.id},
        }

    def action_cst_view_expenses(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Expenses"),
            "res_model": "hr.expense",
            "view_mode": "list,form",
            "domain": [("project_id", "=", self.id)],
            "context": {"default_project_id": self.id},
        }

    @api.depends("cst_mrf_ids.state", "cst_mrf_ids.line_ids.qty_to_produce",
                 "cst_mrf_ids.line_ids.production_id", "cst_production_ids.state")
    def _compute_cst_manufacture_ready(self):
        for project in self:
            entries = project._cst_manufacture_plan()
            missing = project._cst_manufacture_missing_list(entries)
            project.cst_manufacture_ready_count = len(entries)
            project.cst_manufacture_missing = ", ".join(missing)
            project.cst_manufacture_ready = bool(entries) and not missing

    def _cst_manufacture_lines(self):
        """Request lines of this project that can go to production right now."""
        self.ensure_one()
        requests = self.cst_mrf_ids.filtered(
            lambda r: r.state not in ("cancel", "done"))
        return requests._cst_manufacture_lines().filtered("cst_components_available")

    # ------------------------------------------------------------------
    #  What is still to be produced
    # ------------------------------------------------------------------
    def _cst_warehouse(self):
        """The warehouse this project's stock questions are answered against."""
        self.ensure_one()
        warehouse = self.cst_mrf_ids.filtered(
            lambda r: r.state != "cancel")[:1].warehouse_id
        if warehouse:
            return warehouse
        company = self.company_id or self.env.company
        return self.env["stock.warehouse"].search(
            [("company_id", "=", company.id)], limit=1)

    def _cst_manufacture_plan(self):
        """What this project still has to produce, and how much of it.

        Two sources, the first one winning for any given product:

        * the *Manufacture* lines of its material requests that have no order
          yet -- the shortage a request already worked out;
        * the products of its confirmed sale orders that have a bill of
          materials and are covered neither by such a line, nor by an order
          already raised, nor by what is lying in the warehouse.

        The second source is what lets a project whose materials were all in
        stock from the start -- so no request was ever raised -- still go to
        production. Returns ``[{product, qty, uom, bom, mrf_line}]``.
        """
        self.ensure_one()
        company = self.company_id or self.env.company
        warehouse = self._cst_warehouse()
        entries = []
        seen = self.env["product.product"]

        requests = self.cst_mrf_ids.filtered(lambda r: r.state not in ("cancel", "done"))
        for line in requests._cst_manufacture_lines():
            bom = line.bom_id or self.env["mrp.bom"]._bom_find(
                line.product_id, company_id=company.id).get(line.product_id)
            if not bom:
                continue
            entries.append({
                "product": line.product_id,
                "qty": line.qty_to_produce,
                "uom": line.product_uom_id or line.product_id.uom_id,
                "bom": bom,
                "mrf_line": line,
            })
            seen |= line.product_id

        # what the sale orders ask for and nobody has taken care of yet.
        # Only orders still running count as "coming": what a finished order
        # made is already in the warehouse, and counting it twice would hide a
        # genuine shortage — the pieces that came out as 2-sort or brak never
        # reached the shelf, so they have to be made again.
        ordered = defaultdict(float)
        for production in self.cst_production_ids.filtered(
                lambda p: p.state in ("draft", "confirmed", "progress", "to_close")):
            pending = production.product_qty - production.qty_produced
            if production.product_uom_id.compare(pending, 0.0) > 0:
                ordered[production.product_id] += pending
        to_manufacture = self._cst_material_plan(strict=False)[0]
        for product, qty in to_manufacture.items():
            if product in seen:
                continue
            free = product.with_context(
                warehouse_id=warehouse.id).free_qty if warehouse else product.free_qty
            remaining = qty - ordered.get(product, 0.0) - free
            if product.uom_id.compare(remaining, 0.0) <= 0:
                continue
            bom = self.env["mrp.bom"]._bom_find(
                product, company_id=company.id).get(product)
            if not bom:
                continue
            entries.append({
                "product": product,
                "qty": remaining,
                "uom": product.uom_id,
                "bom": bom,
                "mrf_line": self.env["cst.material.request.line"],
            })
        return entries

    def _cst_manufacture_needs(self, entries):
        """``{component: quantity}`` the whole plan eats, in each own unit."""
        self.ensure_one()
        needs = defaultdict(float)
        for entry in entries:
            bom, product = entry["bom"], entry["product"]
            factor = entry["uom"]._compute_quantity(
                entry["qty"], bom.product_uom_id) / bom.product_qty
            for bom_line, data in bom.explode(product, factor)[1]:
                component = bom_line.product_id
                needs[component] += bom_line.product_uom_id._compute_quantity(
                    data["qty"], component.uom_id)
        return needs

    def _cst_manufacture_missing_list(self, entries=None):
        """Components the warehouse cannot cover for the whole plan.

        Asked of the plan as a whole, not line by line, because two products
        often eat the same board and the stock has to stretch over both.
        """
        self.ensure_one()
        if entries is None:
            entries = self._cst_manufacture_plan()
        if not entries:
            return []
        warehouse = self._cst_warehouse()
        missing = []
        for component, needed in self._cst_manufacture_needs(entries).items():
            free = component.with_context(
                warehouse_id=warehouse.id).free_qty if warehouse else component.free_qty
            if component.uom_id.compare(free, needed) < 0:
                missing.append("%s (%g/%g)" % (component.display_name, free, needed))
        return missing

    def _cst_manufacture_guard(self):
        """Refuse to start while a component is still missing."""
        self.ensure_one()
        entries = self._cst_manufacture_plan()
        if not entries:
            raise UserError(_(
                "This project has nothing left to manufacture: either its sold "
                "products have no bill of materials, or every one of them is "
                "already in stock or covered by a manufacturing order."))
        missing = self._cst_manufacture_missing_list(entries)
        if missing:
            raise UserError(_(
                "These components are not in the warehouse yet (free/needed):\n%s",
                "\n".join(missing)))
        return entries

    def action_cst_start_manufacturing(self):
        """Configure operations, work centers and crews, then raise the orders."""
        self.ensure_one()
        return self.env["cst.manufacture.wizard"].cst_open_plan(
            self, self._cst_manufacture_guard())

    def action_cst_new_production(self):
        """Open a manufacturing order form, already filled in from the project.

        Deliberately Odoo's own manufacturing form, so the shop sees the screen
        it knows -- the project, the product, the quantity and the bill of
        materials simply arrive already set.
        """
        self.ensure_one()
        entries = self._cst_manufacture_guard()
        entry = entries[0]
        company = self.company_id or self.env.company
        warehouse = self._cst_warehouse()
        domain = [("code", "=", "mrp_operation"), ("company_id", "=", company.id)]
        picking_type = self.env["stock.picking.type"].search(
            domain + [("warehouse_id", "in", (warehouse.id, False))], limit=1)
        picking_type = picking_type or self.env["stock.picking.type"].search(domain, limit=1)
        context = {
            # project_mrp would otherwise reset project_id from the bill of materials
            "from_project_action": True,
            "default_project_id": self.id,
            "default_company_id": company.id,
            "default_product_id": entry["product"].id,
            "default_product_qty": entry["qty"],
            "default_product_uom_id": entry["uom"].id,
            "default_bom_id": entry["bom"].id,
            "default_origin": self.name or "",
        }
        if picking_type:
            context["default_picking_type_id"] = picking_type.id
        return {
            "type": "ir.actions.act_window",
            "name": _("New Manufacturing Order"),
            "res_model": "mrp.production",
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
            "context": context,
        }

    # ------------------------------------------------------------------
    #  «Ishlab chiqarish yaratish» dialog (same one as the Shop Floor)
    # ------------------------------------------------------------------
    def cst_mo_options(self):
        """What the dialog offers: every product with a bill of materials, the
        lines of the shop, and this project's own plan on top as ready-made
        rows to click."""
        self.ensure_one()
        company = self.company_id or self.env.company
        Builder = self.env["cst.mo.builder"]
        plan = []
        for entry in self._cst_manufacture_plan():
            product = entry["product"]
            plan.append({
                "product_id": product.id,
                "name": product.cst_base_name(),
                "characteristic": product.cst_characteristic or "",
                "qty": entry["qty"],
                "uom": entry["uom"].name,
                "mrf_line_id": entry["mrf_line"].id if entry["mrf_line"] else False,
            })
        return {
            "products": Builder.mo_products(company),
            "workcenters": Builder.mo_workcenters(),
            "plan": plan,
            "missing": self._cst_manufacture_missing_list(),
            "warehouse": self._cst_warehouse().display_name,
        }

    def cst_mo_preview(self, product_id, qty):
        """Components and operations for the dialog, against this project's
        own warehouse."""
        self.ensure_one()
        return self.env["cst.mo.builder"].mo_preview(
            product_id, qty, warehouse_id=self._cst_warehouse().id)

    def cst_mo_search_products(self, query, limit=20):
        self.ensure_one()
        return self.env["cst.mo.builder"].mo_search_products(
            query, limit, warehouse_id=self._cst_warehouse().id)

    def cst_mo_create(self, product_id, qty, materials=None, operations=None):
        """Raise the order the dialog described, stamped with this project.

        A request line that was waiting for exactly this product is marked as
        served, so the project stops asking for it twice.
        """
        self.ensure_one()
        product = self.env["product.product"].browse(int(product_id)).exists()
        if not product:
            raise UserError(_("Mahsulot topilmadi."))
        company = self.company_id or self.env.company
        warehouse = self._cst_warehouse()
        values = {"project_id": self.id, "origin": self.name or ""}
        mrf_line = self._cst_manufacture_plan_line(product)
        if mrf_line:
            values["cst_mrf_line_id"] = mrf_line.id
        production = self.env["cst.mo.builder"]._mo_create(
            product, qty, materials=materials, operations=operations,
            values=values, company=company, warehouse=warehouse)
        if mrf_line and not mrf_line.production_id:
            mrf_line.production_id = production.id
        return {"id": production.id, "name": production.name,
                "ready": self.cst_manufacture_ready}

    def _cst_manufacture_plan_line(self, product):
        """The material-request line this project has waiting for ``product``."""
        self.ensure_one()
        requests = self.cst_mrf_ids.filtered(lambda r: r.state not in ("cancel", "done"))
        return requests._cst_manufacture_lines().filtered(
            lambda l: l.product_id == product)[:1]

    def action_cst_view_productions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Manufacturing Orders"),
            "res_model": "mrp.production",
            "view_mode": "list,form",
            "domain": [("project_id", "=", self.id)],
            "context": {
                "default_project_id": self.id,
                "from_project_action": True,
            },
        }

    def action_cst_open_hub(self):
        """Open this project's own analytics dashboard."""
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "kerama_project_hub",
            "name": self.display_name,
            "params": {"project_id": self.id},
            "context": {"active_id": self.id, "active_model": "project.project"},
        }

    def action_cst_view_mrfs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Material Requests"),
            "res_model": "cst.material.request",
            "view_mode": "list,form",
            "domain": [("project_id", "=", self.id)],
            "context": {"default_project_id": self.id},
        }

    # ------------------------------------------------------------------
    #  Material needs -> MRF
    # ------------------------------------------------------------------
    def _cst_material_plan(self, strict=True):
        """Supply plan for this project, derived from its confirmed sale orders.

        BoM-aware. A sold product that has a bill of materials is *manufactured*,
        and its components (xomashyo) are what needs to be in stock — so they go
        on the buy side. A sold product without a BoM is bought as-is.

        Returns (to_manufacture, to_buy), each {product.product: qty in its UoM}.
        """
        self.ensure_one()
        to_manufacture = defaultdict(float)
        to_buy = defaultdict(float)
        orders = self.env["sale.order"].search([
            ("project_id", "=", self.id), ("state", "in", _SALE_STATES)])
        lines = orders.order_line.filtered(
            lambda l: l.product_id and l.product_id.type != "service" and not l.display_type)
        if not lines:
            if strict:
                raise UserError(_("No confirmed sale order lines found for this project."))
            return to_manufacture, to_buy

        boms = self.env["mrp.bom"]._bom_find(
            lines.product_id, company_id=self.company_id.id)
        for line in lines:
            product = line.product_id
            qty = line.product_uom_id._compute_quantity(line.product_uom_qty, product.uom_id)
            bom = boms.get(product)
            if bom:
                to_manufacture[product] += qty
                # quantity for explode() = number of BoMs needed
                factor = product.uom_id._compute_quantity(qty, bom.product_uom_id) / bom.product_qty
                _boms_done, bom_lines = bom.explode(product, factor)
                for bom_line, data in bom_lines:
                    comp = bom_line.product_id
                    comp_qty = bom_line.product_uom_id._compute_quantity(data["qty"], comp.uom_id)
                    to_buy[comp] += comp_qty
            else:
                to_buy[product] += qty
        return to_manufacture, to_buy

    def _cst_material_demand(self):
        """Kept for compatibility: the buy side of :meth:`_cst_material_plan`."""
        return self._cst_material_plan()[1]

    def action_cst_check_materials(self):
        """Create a Material Request holding this project's shortages.

        Products with a bill of materials become *Manufacture* lines; the
        components they need — and any product without a BoM — become *Buy*
        lines when the warehouse cannot cover them.
        """
        self.ensure_one()
        company = self.company_id or self.env.company
        # a project may be shared across companies and have none of its own
        warehouse = self._cst_warehouse()
        if not warehouse:
            raise UserError(_("No warehouse found for company %s.", company.display_name))

        to_manufacture, to_buy = self._cst_material_plan()
        line_vals = []
        for product, qty in to_manufacture.items():
            free = product.with_context(warehouse_id=warehouse.id).free_qty
            if qty - free > 0:
                line_vals.append((0, 0, {
                    "kind": "manufacture",
                    "product_id": product.id,
                    "product_qty": qty,
                }))
        for product, qty in to_buy.items():
            free = product.with_context(warehouse_id=warehouse.id).free_qty
            if qty - free > 0:
                line_vals.append((0, 0, {
                    "kind": "buy",
                    "product_id": product.id,
                    "product_qty": qty,
                }))
        if not line_vals:
            raise UserError(_(
                "Everything needed is available in warehouse %s — nothing to buy "
                "or manufacture.", warehouse.display_name))

        # checking twice should refresh the request that is still being
        # prepared, not leave a pile of half-identical drafts behind
        mrf = self.env["cst.material.request"].search(
            [("project_id", "=", self.id), ("state", "=", "draft")], order="id desc", limit=1)
        if mrf:
            mrf.line_ids.unlink()
            mrf.write({"warehouse_id": warehouse.id, "line_ids": line_vals})
        else:
            mrf = self.env["cst.material.request"].create({
                "project_id": self.id,
                "company_id": company.id,
                "warehouse_id": warehouse.id,
                "line_ids": line_vals,
            })
        return {
            "type": "ir.actions.act_window",
            "name": mrf.name,
            "res_model": "cst.material.request",
            "res_id": mrf.id,
            "view_mode": "form",
        }
