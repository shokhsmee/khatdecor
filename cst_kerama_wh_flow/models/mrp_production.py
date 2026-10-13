import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    cst_flow_department_id = fields.Many2one(
        "cst.production.department", string="Bo'lim (ombor bo'yicha)", copy=False, readonly=True,
        help="Buyurtma shu bo'limning omborida ochilgan.")
    cst_flow_picking_ids = fields.One2many(
        "stock.picking", "cst_production_id", string="Ombor ko'chirishlari")
    cst_flow_picking_count = fields.Integer(compute="_compute_cst_flow_picking_count")

    def _compute_cst_flow_picking_count(self):
        for production in self:
            production.cst_flow_picking_count = len(production.cst_flow_picking_ids)

    # ------------------------------------------------------------------ department
    def _cst_flow_department(self):
        """Which department's warehouse this order belongs to.

        The screen that raised the order says so through the context; failing
        that, the department of the order's last work order (where the
        finished product comes out), then of the bill's last operation.
        """
        self.ensure_one()
        Department = self.env["cst.production.department"]
        forced = self.env.context.get("cst_flow_department_id")
        if forced:
            return Department.browse(int(forced)).exists()
        if self.cst_flow_department_id:
            return self.cst_flow_department_id
        workorders = self.workorder_ids.sorted(lambda w: (w.sequence, w.id))
        if workorders:
            return workorders[-1].workcenter_id.cst_department_id
        operations = self.bom_id.operation_ids.sorted(lambda o: (o.sequence, o.id))
        return operations[-1:].workcenter_id.cst_department_id if operations else Department

    def _cst_align_warehouse(self, department):
        """Open this order in ``department``'s warehouse.

        Only while nothing of it has moved yet: a draft order, or a confirmed
        one with no done move. Reservations are released first and taken again
        in the new warehouse; raw-material requests raised for the old one are
        cancelled and asked again.
        """
        self.ensure_one()
        warehouse = department.warehouse_id
        if not warehouse:
            return False
        picking_type = warehouse.manu_type_id or self.env["stock.picking.type"].search(
            [("code", "=", "mrp_operation"), ("warehouse_id", "=", warehouse.id)], limit=1)
        if not picking_type:
            return False
        if self.cst_flow_department_id != department:
            self.cst_flow_department_id = department
        if self.picking_type_id == picking_type:
            return False
        moves = self.move_raw_ids | self.move_finished_ids
        if self.state in ("done", "cancel") or moves.filtered(lambda m: m.state == "done"):
            _logger.info("cst_kerama_wh_flow: %s already moved stock, left in %s", self.name,
                         self.picking_type_id.warehouse_id.code)
            return False
        confirmed = self.state != "draft"
        consumed = {}
        if confirmed:
            # consumption already typed (an order waiting to close) is taken
            # again from the new warehouse, same quantities
            for move in self.move_raw_ids.filtered(lambda m: m.state not in ("done", "cancel") and m.picked):
                consumed[move] = move.quantity
            self.do_unreserve()
            leftover = self.move_raw_ids.move_line_ids.filtered(lambda l: l.state not in ("done", "cancel"))
            if leftover:
                leftover.unlink()
            self.move_raw_ids.filtered(lambda m: m.state not in ("done", "cancel")).picked = False
        src = picking_type.default_location_src_id or warehouse.lot_stock_id
        dest = picking_type.default_location_dest_id or warehouse.lot_stock_id
        # keep the raw material the screen shaped: a draft order rebuilds its
        # raw moves from the bill when its source location changes
        old_name = self.name
        self.with_context(skip_compute_move_raw_ids=True, ignore_mo_ids=self.ids).write({
            "picking_type_id": picking_type.id, "location_src_id": src.id, "location_dest_id": dest.id,
        })
        if confirmed and self.name != old_name:
            # Odoo renames an order whose operation type changes; people already
            # know a confirmed one by its number, so it keeps it
            new_name = self.name
            self.name = old_name
            self.move_raw_ids.reference_ids.filtered(lambda r: r.name == new_name).name = old_name
        live = lambda m: m.state not in ("done", "cancel")  # noqa: E731
        self.move_raw_ids.filtered(live).write({
            "location_id": src.id, "warehouse_id": warehouse.id, "picking_type_id": picking_type.id})
        self.move_finished_ids.filtered(live).write({
            "location_dest_id": dest.id, "warehouse_id": warehouse.id, "picking_type_id": picking_type.id})
        pending = self.cst_flow_picking_ids.filtered(
            lambda p: p.cst_flow_kind == "supply" and p.state not in ("done", "cancel"))
        if pending:
            pending.action_cancel()
        if confirmed:
            self.action_assign()
            for move, qty in consumed.items():
                move.quantity = qty
                move.picked = True
            self._cst_request_supply()
        self.message_post(body=_("Buyurtma «%(dept)s» bo'limining omboriga o'tkazildi: %(wh)s.",
                                 dept=department.name, wh=warehouse.display_name))
        return True

    # ------------------------------------------------------------------ confirm
    def action_confirm(self):
        for production in self.filtered(lambda p: p.state == "draft"):
            department = production._cst_flow_department()
            if department:
                production._cst_align_warehouse(department)
        result = super().action_confirm()
        self._cst_request_supply()
        return result

    # ------------------------------------------------------------------ supply
    def _cst_supply_pending(self, product):
        self.ensure_one()
        moves = self.env["stock.move"].search([
            ("cst_supply_production_id", "=", self.id), ("product_id", "=", product.id),
            ("state", "not in", ("done", "cancel"))])
        return sum(m.product_uom._compute_quantity(m.product_uom_qty, product.uom_id) for m in moves)

    def _cst_request_supply(self, manual=False):
        """Ask the department's raw-material warehouses for what is short.

        Short = still to consume − reserved − free in the order's warehouse −
        already on its way for this order. Each source gives what it has free,
        in the order the warehouses are listed; a remainder nobody has goes to
        the first source that holds the product at all (or the first source),
        so the request exists and the storekeeper sees it.
        """
        created = self.env["stock.picking"]
        for production in self.filtered(lambda p: p.state in ("confirmed", "progress")):
            department = production._cst_flow_department()
            if not department or not (department.cst_auto_supply or manual):
                continue
            warehouse = production.location_src_id.warehouse_id
            sources = (department.supply_warehouse_ids - warehouse).sorted(lambda w: (w.sequence, w.id))
            if not warehouse or not sources:
                continue
            needs = {}
            for move in production.move_raw_ids.filtered(lambda m: m.state not in ("done", "cancel")):
                product = move.product_id
                if not product.is_storable:
                    continue
                left = move.product_uom._compute_quantity(max(move.product_uom_qty - move.quantity, 0.0), product.uom_id)
                needs[product] = needs.get(product, 0.0) + left
            plan = {}
            for product, need in needs.items():
                free = product.with_context(warehouse_id=warehouse.id).free_qty
                short = need - max(free, 0.0) - production._cst_supply_pending(product)
                if product.uom_id.compare(short, 0.0) <= 0:
                    continue
                left = short
                for source in sources:
                    have = product.with_context(warehouse_id=source.id).free_qty
                    take = min(have, left) if have > 0 else 0.0
                    if product.uom_id.compare(take, 0.0) > 0:
                        plan.setdefault(source, []).append((product, take))
                        left -= take
                    if product.uom_id.compare(left, 0.0) <= 0:
                        break
                if product.uom_id.compare(left, 0.0) > 0:
                    holder = sources.filtered(
                        lambda s: product.with_context(warehouse_id=s.id).qty_available > 0)[:1] or sources[:1]
                    plan.setdefault(holder, []).append((product, left))
            for source, rows in plan.items():
                created |= production._cst_make_transfer(
                    source, source.lot_stock_id, production.location_src_id, rows, "supply")
        return created

    def _cst_make_transfer(self, source_warehouse, location, location_dest, rows, kind):
        """One internal transfer for this order: ``rows`` = [(product, qty in product UoM)]."""
        self.ensure_one()
        picking_type = source_warehouse.int_type_id
        if not picking_type:
            raise UserError(_("«%s» omborida ichki ko'chirish turi yo'q.", source_warehouse.display_name))
        link = "cst_supply_production_id" if kind == "supply" else "cst_forward_production_id"
        merged = {}
        for product, qty in rows:
            merged[product] = merged.get(product, 0.0) + qty
        picking = self.env["stock.picking"].sudo().create({
            "picking_type_id": picking_type.id,
            "location_id": location.id,
            "location_dest_id": location_dest.id,
            "origin": self.name,
            "company_id": self.company_id.id,
            "cst_production_id": self.id,
            "cst_flow_kind": kind,
            "move_ids": [(0, 0, {
                "product_id": product.id,
                "product_uom": product.uom_id.id,
                "product_uom_qty": product.uom_id.round(qty),
                "location_id": location.id,
                "location_dest_id": location_dest.id,
                "company_id": self.company_id.id,
                link: self.id,
            }) for product, qty in merged.items()],
        })
        picking.action_confirm()
        picking.action_assign()
        label = _("Xomashyo so'rovi") if kind == "supply" else _("Tayyor mahsulot yuborildi")
        self.message_post(body=_("%(label)s: %(picking)s (%(src)s → %(dst)s).", label=label,
                                 picking=picking._get_html_link(), src=location.display_name,
                                 dst=location_dest.display_name))
        return picking

    def action_cancel(self):
        # a cancelled order's raw-material requests are no longer wanted
        requests = self.env["stock.picking"].sudo().search([
            ("cst_production_id", "in", self.ids), ("cst_flow_kind", "=", "supply"),
            ("state", "not in", ("done", "cancel"))])
        result = super().action_cancel()
        if requests:
            requests.action_cancel()
        return result

    def action_cst_request_supply(self):
        created = self._cst_request_supply(manual=True)
        if not created:
            raise UserError(_("Hamma xomashyo bo'lim omborida bor yoki allaqachon so'ralgan."))
        return self.action_view_cst_flow_pickings()

    def action_view_cst_flow_pickings(self):
        self.ensure_one()
        pickings = self.cst_flow_picking_ids
        action = {
            "type": "ir.actions.act_window", "name": _("Ombor ko'chirishlari"),
            "res_model": "stock.picking", "view_mode": "list,form",
            "domain": [("id", "in", pickings.ids)], "context": {"create": False},
        }
        if len(pickings) == 1:
            action.update(view_mode="form", res_id=pickings.id)
        return action

    # ------------------------------------------------------------------ output
    def _cst_used_in_department(self, product, department):
        """Is ``product`` a material in a bill made by ``department`` itself?"""
        return bool(self.env["mrp.bom.line"].sudo().search_count([
            ("product_id", "=", product.id),
            ("bom_id.active", "=", True),
            ("bom_id.operation_ids.workcenter_id.cst_department_id", "=", department.id),
        ], limit=1))

    def _cst_forward_output(self):
        """Send what this order put in its warehouse on to the next one.

        Produced − scrapped (brak and the 2-sort pieces regraded away) − already
        sent, for the finished product; for its 2-sort twin, what the shift lines
        brought into stock − already sent. Safe to call again: only the
        difference moves.
        """
        created = self.env["stock.picking"]
        Line = self.env["cst.production.shift.line"].sudo()
        for production in self:
            department = production._cst_flow_department()
            if not department or not department.cst_auto_forward or not department.output_warehouse_id:
                continue
            source = production.location_dest_id
            target = department.output_warehouse_id
            if not source.warehouse_id or source.warehouse_id == target:
                continue
            main = production.product_id
            if production._cst_used_in_department(main, department):
                # a semi-finished material (e.g. glue) the department makes
                # for its own orders stays where it is consumed
                continue
            qty = {}
            for move in production.move_finished_ids.filtered(lambda m: m.state == "done" and m.product_id == main):
                qty[main] = qty.get(main, 0.0) + move.product_uom._compute_quantity(move.quantity, main.uom_id)
            for scrap in production.scrap_ids.filtered(lambda s: s.state == "done" and s.product_id == main):
                qty[main] = qty.get(main, 0.0) - scrap.product_uom_id._compute_quantity(scrap.scrap_qty, main.uom_id)
            twins = Line.search([("production_id", "=", production.id)]).second_grade_move_ids.filtered(
                lambda m: m.state == "done" and m.location_dest_id == source)
            for move in twins:
                qty[move.product_id] = qty.get(move.product_id, 0.0) + move.product_uom._compute_quantity(
                    move.quantity, move.product_id.uom_id)
            sent = self.env["stock.move"].search([
                ("cst_forward_production_id", "=", production.id), ("state", "!=", "cancel")])
            for move in sent:
                qty[move.product_id] = qty.get(move.product_id, 0.0) - move.product_uom._compute_quantity(
                    move.product_uom_qty, move.product_id.uom_id)
            rows = [(product, q) for product, q in qty.items() if product.uom_id.compare(q, 0.0) > 0]
            if rows:
                created |= production._cst_make_transfer(
                    source.warehouse_id, source, target.lot_stock_id, rows, "output")
        return created

    def button_mark_done(self):
        result = super().button_mark_done()
        # a shift line booking its result sends the goods itself, after brak
        # and 2-sort have been taken out (see cst.production.shift.line)
        if not self.env.context.get("cst_posting_output"):
            self.filtered(lambda p: p.state == "done")._cst_forward_output()
        return result
