from collections import defaultdict

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class CstManufactureWizard(models.TransientModel):
    """Configure the manufacturing of a project's material request.

    The request says *what* has to be produced; here the shop decides *how*:
    which operations of the bill of materials are actually needed, on which
    work centre each of them runs, how the quantity is split between them, who
    is responsible for the work, and which materials each operation eats.

    Nothing here touches the bill of materials: the operations and the raw
    material moves are tailored on the manufacturing order alone.
    """

    _name = "cst.manufacture.wizard"
    _description = "Start Manufacturing"

    project_id = fields.Many2one("project.project", string="Project", required=True, readonly=True)
    request_id = fields.Many2one("cst.material.request", string="Material Request", readonly=True)
    company_id = fields.Many2one("res.company", required=True, readonly=True)
    warehouse_id = fields.Many2one("stock.warehouse", string="Warehouse", readonly=True)
    line_ids = fields.One2many("cst.manufacture.wizard.line", "wizard_id", string="Products")
    operation_ids = fields.One2many(
        "cst.manufacture.wizard.operation", "wizard_id", string="Operations")
    component_ids = fields.One2many(
        "cst.manufacture.wizard.component", "wizard_id", string="Materials")

    # ------------------------------------------------------------------
    #  Building the wizard
    # ------------------------------------------------------------------
    @api.model
    def _cst_prepare(self, mrf_lines):
        """Wizard values for the given material request lines."""
        mrf_lines = mrf_lines.filtered(
            lambda l: l.kind == "manufacture" and l.qty_to_produce > 0 and not l.production_id)
        if not mrf_lines:
            raise UserError(_("Nothing left to manufacture on this project."))
        entries = [{
            "product": line.product_id,
            "qty": line.qty_to_produce,
            "uom": line.product_uom_id or line.product_id.uom_id,
            "bom": line.bom_id or self.env["mrp.bom"]._bom_find(
                line.product_id, company_id=line.company_id.id).get(line.product_id),
            "mrf_line": line,
        } for line in mrf_lines]
        return self._cst_prepare_entries(mrf_lines[0].project_id, entries)

    @api.model
    def _cst_prepare_entries(self, project, entries):
        """Wizard values for a project's production plan.

        An entry is ``{product, qty, uom, bom, mrf_line}``. The request line is
        optional: a project whose materials were in stock from the start never
        raised a request, and still has to be able to produce.
        """
        if not entries:
            raise UserError(_("Nothing left to manufacture on this project."))
        requests = self.env["cst.material.request"]
        for entry in entries:
            requests |= entry["mrf_line"].request_id
        warehouse = requests[:1].warehouse_id or project._cst_warehouse()
        lines, operations, components = [], [], []
        for index, entry in enumerate(entries):
            product, bom, qty = entry["product"], entry["bom"], entry["qty"]
            uom = entry["uom"] or product.uom_id
            if not bom:
                raise UserError(_(
                    "No bill of materials found for %s.", product.display_name))
            lines.append(Command.create({
                "sequence": index,
                "mrf_line_id": entry["mrf_line"].id or False,
                "product_id": product.id,
                "product_uom_id": uom.id,
                "product_qty": qty,
                "bom_id": bom.id,
            }))
            for values in self._cst_operation_values(bom, qty):
                operations.append(Command.create(dict(values, line_index=index)))
            for values in self._cst_component_values(bom, product, uom, qty, warehouse):
                components.append(Command.create(dict(values, line_index=index)))

        return {
            "project_id": project.id,
            "request_id": requests[0].id if len(requests) == 1 else False,
            "company_id": (project.company_id or self.env.company).id,
            "warehouse_id": warehouse.id,
            "line_ids": lines,
            "operation_ids": operations,
            "component_ids": components,
        }

    @api.model
    def _cst_operation_values(self, bom, qty):
        """One row per operation of *bom*, ticked and covering the whole qty."""
        return [{
            "selected": True,
            "sequence": operation.sequence,
            "operation_id": operation.id,
            "workcenter_id": operation.workcenter_id.id,
            "product_qty": qty,
        } for operation in bom.operation_ids]

    @api.model
    def _cst_component_values(self, bom, product, product_uom, qty, warehouse):
        """One row per material the bill of materials explodes into."""
        factor = product_uom._compute_quantity(qty, bom.product_uom_id) / bom.product_qty
        values = []
        for bom_line, data in bom.explode(product, factor)[1]:
            component = bom_line.product_id
            available = component.with_context(
                warehouse_id=warehouse.id).free_qty if warehouse else component.free_qty
            values.append({
                "bom_line_id": bom_line.id,
                "product_id": component.id,
                "product_uom_id": bom_line.product_uom_id.id,
                "product_qty": data["qty"],
                "qty_available": available,
                # empty means "consumed whatever the operations are"; the bill of
                # materials rarely says, so the shop assigns the stage here
                "operation_id": bom_line.operation_id.id,
            })
        return values

    @api.model
    def cst_open_plan(self, project, entries):
        """Create the wizard for a project's production plan."""
        return self._cst_open_values(self._cst_prepare_entries(project, entries))

    @api.model
    def cst_open(self, mrf_lines):
        """Create the wizard for these request lines and return its action."""
        return self._cst_open_values(self._cst_prepare(mrf_lines))

    @api.model
    def _cst_open_values(self, values):
        wizard = self.create(values)
        # the operation and material rows are attached to their product line by position
        by_index = {line.sequence: line for line in wizard.line_ids}
        for child in (wizard.operation_ids, wizard.component_ids):
            for record in child:
                record.line_id = by_index[record.line_index].id
        return wizard._cst_action()

    def _cst_action(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Start Manufacturing"),
            "res_model": "cst.manufacture.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    # ------------------------------------------------------------------
    #  Keeping the tabs in step with the products
    # ------------------------------------------------------------------
    def _cst_sync_children(self):
        """Give every product line the operation and material rows it lacks.

        A product added by hand arrives without them, and a line whose bill of
        materials was changed keeps rows belonging to the old one. Rows that
        are already there are left alone, so splits configured earlier survive.

        This runs on saved records only -- an ``onchange`` cannot do it, because
        the operation and material rows live in one2many fields of their own and
        cannot be attached to a product line that has no database id yet.
        """
        Operation = self.env["cst.manufacture.wizard.operation"]
        Component = self.env["cst.manufacture.wizard.component"]
        for wizard in self:
            lines = wizard.line_ids
            stale_operations = wizard.operation_ids.filtered(
                lambda o: o.line_id not in lines
                or (o.operation_id and o.operation_id.bom_id != o.line_id.bom_id))
            stale_components = wizard.component_ids.filtered(
                lambda c: c.line_id not in lines
                or (c.bom_line_id and c.bom_line_id.bom_id != c.line_id.bom_id))
            stale_operations.unlink()
            stale_components.unlink()

            operations, components = [], []
            for line in lines:
                if not line.product_id or not line.bom_id:
                    continue
                if not line.operation_ids:
                    operations += [
                        dict(values, wizard_id=wizard.id, line_id=line.id)
                        for values in wizard._cst_operation_values(line.bom_id, line.product_qty)
                    ]
                if not line.component_ids:
                    components += [
                        dict(values, wizard_id=wizard.id, line_id=line.id)
                        for values in wizard._cst_component_values(
                            line.bom_id, line.product_id, line.product_uom_id,
                            line.product_qty, wizard.warehouse_id)
                    ]
            if operations:
                Operation.create(operations)
            if components:
                Component.create(components)
            wizard.invalidate_recordset(["operation_ids", "component_ids"])

    def action_load_lines(self):
        """Load the operations and materials of the products added by hand."""
        self.ensure_one()
        self._cst_sync_children()
        return self._cst_action()

    def action_reset_lines(self):
        """Throw the configuration away and rebuild it from the bills of materials."""
        self.ensure_one()
        self.operation_ids.unlink()
        self.component_ids.unlink()
        self._cst_sync_children()
        return self._cst_action()

    # ------------------------------------------------------------------
    #  Creating the manufacturing orders
    # ------------------------------------------------------------------
    def _cst_picking_type(self):
        self.ensure_one()
        domain = [("code", "=", "mrp_operation"), ("company_id", "=", self.company_id.id)]
        picking_type = self.env["stock.picking.type"].search(
            domain + [("warehouse_id", "in", (self.warehouse_id.id, False))], limit=1)
        picking_type = picking_type or self.env["stock.picking.type"].search(domain, limit=1)
        if not picking_type:
            raise UserError(_(
                "No manufacturing operation type found for company %s.",
                self.company_id.display_name))
        return picking_type

    def _cst_check(self):
        """Every ticked operation must cover the whole quantity of its product."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Add at least one product to manufacture."))
        for line in self.line_ids:
            if not line.bom_id:
                raise UserError(_(
                    "No bill of materials found for %s.", line.product_id.display_name))
            if line.product_qty <= 0:
                raise UserError(_(
                    "Set a quantity to produce for %s.", line.product_id.display_name))
            splits = line.operation_ids.filtered("selected")
            if not splits:
                raise UserError(_(
                    "Tick at least one operation for %s.", line.product_id.display_name))
            per_operation = defaultdict(float)
            for split in splits:
                if not split.workcenter_id:
                    raise UserError(_(
                        "Choose a work center for operation %(operation)s of %(product)s.",
                        operation=split.display_name, product=line.product_id.display_name))
                per_operation[split.operation_id] += split.product_qty
            rounding = line.product_uom_id or line.product_id.uom_id
            for operation, qty in per_operation.items():
                if rounding.compare(qty, line.product_qty) != 0:
                    raise UserError(_(
                        "Operation %(operation)s of %(product)s is split over "
                        "%(split)s pcs, but %(total)s must be produced.",
                        operation=operation.name, product=line.product_id.display_name,
                        split=qty, total=line.product_qty))

    @api.model
    def _cst_chain_workorders(self, production):
        """Let the splits of one operation run side by side.

        Odoo confirms work orders in a single file: each one waits for the
        previous. Two work centers sharing an operation should instead start
        together, and only wait for the operation before them.
        """
        previous = self.env["mrp.workorder"]
        by_operation = defaultdict(lambda: self.env["mrp.workorder"])
        for workorder in production.workorder_ids.sorted(lambda w: (w.sequence, w.id)):
            by_operation[workorder.operation_id] |= workorder
        for workorders in by_operation.values():
            workorders.blocked_by_workorder_ids = [Command.set(previous.ids)]
            previous = workorders

    def _cst_trim_components(self, production, line):
        """Drop the raw material of the operations this order does not run.

        The bill of materials stays as it is -- only this order's moves are
        rewritten, so an order that just cuts does not eat the film the press
        would have used.
        """
        self.ensure_one()
        skipped = line.component_ids.filtered(lambda c: not c.will_consume)
        if not skipped:
            return
        bom_lines = skipped.bom_line_id
        moves = production.move_raw_ids.filtered(lambda m: m.bom_line_id in bom_lines)
        if moves:
            moves.unlink()

    def action_confirm(self):
        """Raise one manufacturing order per product, with the chosen work orders."""
        self.ensure_one()
        # a product added by hand may still be missing its rows
        self._cst_sync_children()
        self._cst_check()
        picking_type = self._cst_picking_type()
        Production = self.env["mrp.production"].with_company(self.company_id).with_context(
            # keep our project: project_mrp would otherwise reset it from the BoM
            from_project_action=True,
            default_project_id=self.project_id.id,
        )
        productions = self.env["mrp.production"]
        for line in self.line_ids:
            request = line.mrf_line_id.request_id
            production = Production.create({
                "product_id": line.product_id.id,
                "product_qty": line.product_qty,
                "product_uom_id": line.product_uom_id.id,
                "bom_id": line.bom_id.id,
                "picking_type_id": picking_type.id,
                "company_id": self.company_id.id,
                "project_id": self.project_id.id,
                "origin": " / ".join(n for n in (request.name, self.project_id.name) if n),
                "cst_mrf_line_id": line.mrf_line_id.id,
            })
            # The bill of materials has just filled move_raw_ids. From here on the
            # moves are ours to shape, so stop the compute putting back what we drop.
            production = production.with_context(skip_compute_move_raw_ids=True)
            self._cst_trim_components(production, line)
            # replace the work orders the BoM generated with the ones configured here
            production.workorder_ids.unlink()
            production.write({"workorder_ids": [
                Command.create(split._cst_workorder_values())
                for split in line.operation_ids.filtered("selected")
            ]})
            for workorder in production.workorder_ids:
                # the split only does its share of the quantity, so does its duration
                ratio = (workorder.cst_split_qty / line.product_qty) if line.product_qty else 1.0
                workorder.duration_expected = workorder._get_duration_expected() * ratio
            if line.mrf_line_id:
                line.mrf_line_id.production_id = production.id
            production.action_confirm()
            self._cst_chain_workorders(production)
            productions |= production
            if request.state in ("approved", "assigned"):
                request.state = "purchased"

        return {
            "type": "ir.actions.act_window",
            "name": _("Manufacturing Orders"),
            "res_model": "mrp.production",
            "view_mode": "list,form",
            "domain": [("id", "in", productions.ids)],
            "context": {"default_project_id": self.project_id.id, "from_project_action": True},
        }


class CstManufactureWizardLine(models.TransientModel):
    _name = "cst.manufacture.wizard.line"
    _description = "Start Manufacturing: Product"
    _order = "sequence, id"

    wizard_id = fields.Many2one("cst.manufacture.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer(default=0)
    mrf_line_id = fields.Many2one("cst.material.request.line", readonly=True)
    request_id = fields.Many2one(related="mrf_line_id.request_id", string="Request")
    product_id = fields.Many2one(
        "product.product", string="Product", required=True,
        domain="[('is_storable', '=', True)]")
    cst_characteristic = fields.Char(
        related="product_id.cst_characteristic", string="Xarakteristika")
    product_uom_id = fields.Many2one(
        "uom.uom", string="Unit", compute="_compute_product_uom_id", store=True,
        precompute=True, readonly=False, required=True)
    product_qty = fields.Float(string="Quantity", required=True, default=1.0)
    bom_id = fields.Many2one(
        "mrp.bom", string="Bill of Materials", compute="_compute_bom_id", store=True,
        precompute=True, readonly=False, required=True)
    operation_ids = fields.One2many("cst.manufacture.wizard.operation", "line_id")
    component_ids = fields.One2many("cst.manufacture.wizard.component", "line_id")
    operation_count = fields.Integer(compute="_compute_operation_count", string="Operations")

    @api.depends("product_id")
    def _compute_product_uom_id(self):
        for line in self:
            line.product_uom_id = line.product_id.uom_id

    @api.depends("product_id")
    def _compute_bom_id(self):
        for line in self:
            if not line.product_id:
                line.bom_id = False
                continue
            company = line.wizard_id.company_id or line.env.company
            line.bom_id = self.env["mrp.bom"]._bom_find(
                line.product_id, company_id=company.id).get(line.product_id)

    @api.depends("operation_ids.selected")
    def _compute_operation_count(self):
        for line in self:
            line.operation_count = len(line.operation_ids.filtered("selected"))


class CstManufactureWizardOperation(models.TransientModel):
    """One slice of work: an operation, on a work center, for part of the quantity."""

    _name = "cst.manufacture.wizard.operation"
    _description = "Start Manufacturing: Operation"
    _order = "sequence, id"

    wizard_id = fields.Many2one("cst.manufacture.wizard", required=True, ondelete="cascade")
    line_id = fields.Many2one("cst.manufacture.wizard.line", string="Product", ondelete="cascade")
    line_index = fields.Integer(help="Technical: position of the product line while building.")
    sequence = fields.Integer(default=10)
    selected = fields.Boolean(
        string="Do it", default=True,
        help="Untick an operation this order does not run. Only ticked "
             "operations become work orders, and only their materials are used.")
    product_id = fields.Many2one(related="line_id.product_id", string="Product")
    operation_id = fields.Many2one(
        "mrp.routing.workcenter", string="Operation", required=True,
        domain="[('bom_id', '=', bom_id)]")
    bom_id = fields.Many2one(related="line_id.bom_id")
    name = fields.Char(string="Work Order", compute="_compute_name", store=True, readonly=False)
    workcenter_id = fields.Many2one("mrp.workcenter", string="Work Center")
    product_qty = fields.Float(string="Quantity", required=True, default=1.0)
    user_id = fields.Many2one(
        "res.users", string="Responsible", domain=[("share", "=", False)],
        help="Manager answering for this operation on this work center.")
    employee_ids = fields.Many2many(
        "hr.employee", string="Workers",
        help="Who does the work on the shop floor.")

    @api.depends("operation_id")
    def _compute_name(self):
        for split in self:
            split.name = split.operation_id.name

    @api.onchange("operation_id")
    def _onchange_operation_id(self):
        for split in self:
            if split.operation_id and not split.workcenter_id:
                split.workcenter_id = split.operation_id.workcenter_id

    @api.depends("operation_id", "workcenter_id")
    def _compute_display_name(self):
        for split in self:
            names = [split.name or split.operation_id.name or ""]
            if split.workcenter_id:
                names.append(split.workcenter_id.display_name)
            split.display_name = " / ".join(n for n in names if n)

    def _cst_workorder_values(self):
        self.ensure_one()
        return {
            "name": self.name or self.operation_id.name,
            "workcenter_id": self.workcenter_id.id,
            "operation_id": self.operation_id.id,
            "product_uom_id": self.line_id.product_uom_id.id,
            "cst_manager_id": self.user_id.id,
            "employee_assigned_ids": [Command.set(self.employee_ids.ids)],
            "cst_split_qty": self.product_qty,
        }


class CstManufactureWizardComponent(models.TransientModel):
    """A material of the run, and the operation that eats it."""

    _name = "cst.manufacture.wizard.component"
    _description = "Start Manufacturing: Material"
    _order = "id"

    wizard_id = fields.Many2one("cst.manufacture.wizard", required=True, ondelete="cascade")
    line_id = fields.Many2one("cst.manufacture.wizard.line", string="Product", ondelete="cascade")
    line_index = fields.Integer(help="Technical: position of the product line while building.")
    bom_line_id = fields.Many2one("mrp.bom.line", string="Bill of Materials Line", readonly=True)
    bom_id = fields.Many2one(related="line_id.bom_id")
    product_id = fields.Many2one("product.product", string="Material", readonly=True)
    cst_characteristic = fields.Char(
        related="product_id.cst_characteristic", string="Xarakteristika")
    product_uom_id = fields.Many2one("uom.uom", string="Unit", readonly=True)
    product_qty = fields.Float(string="Needed", readonly=True)
    qty_available = fields.Float(string="In Stock", readonly=True)
    operation_id = fields.Many2one(
        "mrp.routing.workcenter", string="Used By", domain="[('bom_id', '=', bom_id)]",
        help="Operation that consumes this material. Leave it empty for a "
             "material the order always needs; set it and the material is only "
             "taken when that operation is part of the order.")
    will_consume = fields.Boolean(
        string="Used", compute="_compute_will_consume",
        help="Whether this order will actually take the material.")
    is_short = fields.Boolean(compute="_compute_is_short", string="Missing")

    @api.depends("operation_id", "line_id.operation_ids.selected",
                 "line_id.operation_ids.operation_id")
    def _compute_will_consume(self):
        for component in self:
            if not component.operation_id:
                component.will_consume = True
                continue
            selected = component.line_id.operation_ids.filtered("selected").operation_id
            component.will_consume = component.operation_id in selected

    @api.depends("product_qty", "qty_available", "will_consume")
    def _compute_is_short(self):
        for component in self:
            component.is_short = component.will_consume \
                and component.qty_available < component.product_qty
