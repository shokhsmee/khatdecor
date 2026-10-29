from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CstProductionShiftLine(models.Model):
    """One order run on one line during one shift.

    The work order carries the Odoo mechanics (start, employees, time); this
    line carries what the shift did with it: the plan for today, the results
    entered during the day, and where the product went at the end.
    """

    _name = "cst.production.shift.line"
    _description = "Smena buyurtmasi"
    _order = "sequence, id"

    shift_id = fields.Many2one("cst.production.shift", required=True, ondelete="cascade", index=True)
    department_id = fields.Many2one(related="shift_id.department_id", store=True)
    company_id = fields.Many2one(related="shift_id.company_id", store=True)
    shift_state = fields.Selection(related="shift_id.state")
    sequence = fields.Integer(default=10)
    production_id = fields.Many2one(
        "mrp.production", string="Buyurtma", required=True, index=True, ondelete="restrict",
        domain="[('state', 'in', ('confirmed', 'progress', 'to_close')), ('company_id', '=', company_id)]")
    workorder_id = fields.Many2one(
        "mrp.workorder", string="Ish buyurtmasi", required=True, index=True, ondelete="restrict",
        domain="[('production_id', '=', production_id), ('state', 'not in', ('done', 'cancel'))]")
    workcenter_id = fields.Many2one(
        "mrp.workcenter", string="Liniya", required=True,
        domain="[('cst_department_id', '=', department_id)]",
        help="Bu buyurtma shu smenada qaysi liniyada bajariladi.")
    product_id = fields.Many2one(related="production_id.product_id", store=True, string="Mahsulot")
    cst_characteristic = fields.Char(related="product_id.cst_characteristic", string="Xarakteristika")
    product_uom_id = fields.Many2one(related="production_id.product_uom_id")
    sale_origin = fields.Char(related="production_id.origin", string="Buyurtma manbai")
    order_qty = fields.Float(related="production_id.product_qty", string="Buyurtma miqdori")
    planned_qty = fields.Float(
        string="Smena rejasi", required=True, digits="Product Unit of Measure",
        help="Shu smenada nechta chiqarish mo'ljallangan.")
    qty_good = fields.Float(string="1-sort", compute="_compute_qty", store=True, digits="Product Unit of Measure")
    qty_second = fields.Float(string="2-sort", compute="_compute_qty", store=True, digits="Product Unit of Measure")
    qty_scrap = fields.Float(string="Brak", compute="_compute_qty", store=True, digits="Product Unit of Measure")
    qty_total = fields.Float(string="Jami", compute="_compute_qty", store=True, digits="Product Unit of Measure")
    progress_pct = fields.Float(string="Bajarilishi %", compute="_compute_qty", store=True)
    employee_ids = fields.Many2many(
        "hr.employee", "cst_shift_line_employee_rel", "line_id", "employee_id", string="Xodimlar",
        help="Shu buyurtmada ishlaganlar. Bo'sh qolsa smenadagi hamma xodim.")
    entry_ids = fields.One2many("cst.production.shift.entry", "line_id", string="Natijalar")
    state = fields.Selection([
        ("todo", "Kutilmoqda"),
        ("progress", "Jarayonda"),
        ("paused", "To'xtatilgan"),
        ("done", "Bajarildi"),
        ("carried", "Keyingi smenaga"),
    ], default="todo", required=True, index=True)
    is_final_operation = fields.Boolean(
        string="Oxirgi operatsiya", compute="_compute_is_final", store=True,
        help="Buyurtmaning oxirgi operatsiyasi: natija kiritilganda mahsulot omborga tushadi.")
    date_start = fields.Datetime(string="Boshlandi", readonly=True)
    date_end = fields.Datetime(string="Tugadi", readonly=True)
    backorder_production_id = fields.Many2one(
        "mrp.production", string="Qoldiq buyurtma", readonly=True,
        help="Smena rejadan kam chiqarganda qolgan miqdor uchun yaratilgan buyurtma.")
    second_grade_move_ids = fields.Many2many(
        "stock.move", "cst_shift_line_second_move_rel", "line_id", "move_id",
        string="2-sort kirimlari", readonly=True)
    scrap_ids = fields.Many2many(
        "stock.scrap", "cst_shift_line_scrap_rel", "line_id", "scrap_id", string="Scrap'lar", readonly=True)
    correction_production_ids = fields.Many2many(
        "mrp.production", "cst_shift_line_correction_mo_rel", "line_id", "production_id",
        string="Tuzatish buyurtmalari", readonly=True, copy=False,
        help="Natija tuzatilib ko'paytirilganda qo'shimcha chiqarilgan miqdor uchun yaratilgan buyurtmalar.")
    unbuild_ids = fields.Many2many(
        "mrp.unbuild", "cst_shift_line_unbuild_rel", "line_id", "unbuild_id",
        string="Tuzatish (qaytarish)", readonly=True, copy=False)
    correction_move_ids = fields.Many2many(
        "stock.move", "cst_shift_line_correction_move_rel", "line_id", "move_id",
        string="Tuzatish harakatlari", readonly=True, copy=False)

    # ------------------------------------------------------------------ computes
    @api.depends("entry_ids.qty_good", "entry_ids.qty_second", "entry_ids.qty_scrap", "planned_qty")
    def _compute_qty(self):
        for line in self:
            entries = line.entry_ids
            line.qty_good = sum(entries.mapped("qty_good"))
            line.qty_second = sum(entries.mapped("qty_second"))
            line.qty_scrap = sum(entries.mapped("qty_scrap"))
            line.qty_total = line.qty_good + line.qty_second + line.qty_scrap
            line.progress_pct = (line.qty_good / line.planned_qty * 100.0) if line.planned_qty else 0.0

    @api.depends("workorder_id", "production_id.workorder_ids.sequence")
    def _compute_is_final(self):
        for line in self:
            wo = line.workorder_id
            others = line.production_id.workorder_ids - wo
            line.is_final_operation = bool(wo) and not others.filtered(
                lambda w: w.state != "cancel" and (w.sequence, w.id) > (wo.sequence, wo.id))

    @api.onchange("production_id")
    def _onchange_production(self):
        for line in self:
            wos = line.production_id.workorder_ids.filtered(
                lambda w: w.state not in ("done", "cancel")
                and w.workcenter_id.cst_department_id == line.department_id)
            line.workorder_id = wos[:1]
            if not line.planned_qty:
                line.planned_qty = line.workorder_id.qty_remaining or line.production_id.product_qty

    @api.onchange("workorder_id")
    def _onchange_workorder(self):
        for line in self:
            if line.workorder_id and not line.workcenter_id:
                line.workcenter_id = line.workorder_id.workcenter_id
            if line.workorder_id and not line.planned_qty:
                line.planned_qty = line.workorder_id.qty_remaining or line.production_id.product_qty

    @api.model_create_multi
    def create(self, vals_list):
        # the line and the plan default from the work order -- before the insert,
        # both columns are NOT NULL
        Workorder = self.env["mrp.workorder"]
        for vals in vals_list:
            workorder = Workorder.browse(vals.get("workorder_id")) if vals.get("workorder_id") else Workorder
            if not vals.get("workcenter_id") and workorder:
                vals["workcenter_id"] = workorder.workcenter_id.id
            if not vals.get("planned_qty") and workorder:
                vals["planned_qty"] = workorder.qty_remaining or workorder.production_id.product_qty
        lines = super().create(vals_list)
        for line in lines:
            if not line.employee_ids:
                # sudo: the shift manager has no read access to hr.employee
                line.sudo().employee_ids = line.shift_id.employee_ids
        return lines

    # ------------------------------------------------------------------ guards
    def _order_remaining(self):
        """What the manufacturing order can still turn out: its quantity less
        what is already produced and what this line has counted but not yet
        booked."""
        self.ensure_one()
        mo = self.production_id
        pending = sum(self.entry_ids.filtered(lambda e: not e.posted).mapped(
            lambda e: e.qty_good + e.qty_second + e.qty_scrap))
        return mo.product_qty - mo.qty_produced - pending

    def _check_order_remaining(self):
        """Counting more pieces than the order has left is a typing error; say
        so the moment it is typed, not when the shift closes."""
        for line in self.filtered("is_final_operation"):
            left = line._order_remaining()
            if line.product_uom_id.compare(left, 0.0) < 0:
                raise UserError(_(
                    "%(order)s: buyurtmada %(qty)s dona qoldi, undan ko'p kiritildi (%(over)s dona ortiqcha). "
                    "Ortiqcha chiqarilgan bo'lsa avval buyurtma miqdorini oshiring.",
                    order=line.production_id.name,
                    qty=line.production_id.product_qty - line.production_id.qty_produced, over=-left))

    def _cst_increase_order(self, total):
        """More pieces came off the line than the order has left (the manager
        added an extra batch to a sales request): the order grows to take them,
        its raw material with it, before the count is booked."""
        self.ensure_one()
        if not self.is_final_operation:
            return
        mo = self.production_id
        extra = total - self._order_remaining()
        if mo.product_uom_id.compare(extra, 0.0) <= 0:
            return
        if mo.state not in ("confirmed", "progress", "to_close"):
            raise UserError(_("%s: buyurtma holati miqdorni o'zgartirishga imkon bermaydi.", mo.name))
        self.check_access("write")
        old = mo.product_qty
        # sudo: the shift manager may run the line without rights on the order's wizard
        self.env["change.production.qty"].sudo().create({
            "mo_id": mo.id, "product_qty": old + extra,
        }).change_prod_qty()
        if self.product_uom_id.compare(self.planned_qty, self.qty_good + total) < 0:
            self.sudo().planned_qty = self.qty_good + total
        mo.sudo().message_post(body=_(
            "Buyurtma miqdori smena natijasi bo'yicha oshirildi: %(old)s → %(new)s (%(shift)s).",
            old=old, new=mo.product_qty, shift=self.shift_id.display_name))

    def _check_open(self):
        for line in self:
            if line.shift_id.state != "open":
                raise UserError(_("Smena ochiq emas: %s", line.shift_id.display_name))

    def _workers(self):
        self.ensure_one()
        return self.employee_ids or self.shift_id.employee_ids

    # ------------------------------------------------------------------ actions
    def action_start(self):
        """Put the order on the line: the work order starts, the crew is clocked in."""
        for line in self:
            line._check_open()
            if line.state not in ("todo", "paused"):
                raise UserError(_("«%s» allaqachon jarayonda yoki tugatilgan.", line.production_id.name))
            wo = line.workorder_id
            if wo.state in ("done", "cancel"):
                raise UserError(_("Ish buyurtmasi %s allaqachon yopilgan.", wo.display_name))
            values = {"cst_shift_id": line.shift_id.id}
            code = line.shift_id.template_id._payroll_code()
            if code:
                values["cst_shift"] = code
            if wo.workcenter_id != line.workcenter_id:
                values["workcenter_id"] = line.workcenter_id.id
            wo.write(values)
            workers = line._workers()
            if workers:
                wo.sudo().employee_assigned_ids |= workers
            if wo.state != "progress":
                wo.with_context(cst_shift_bypass=True).button_start(bypass=True)
            for employee in workers:
                wo.sudo().start_employee(employee.id)
            line.write({"state": "progress", "date_start": line.date_start or fields.Datetime.now()})
        return True

    def action_pause(self):
        for line in self:
            line._check_open()
            if line.state != "progress":
                continue
            line._clock_out()
            if line.workorder_id.state == "progress":
                line.workorder_id.button_pending()
            line.state = "paused"
        return True

    def action_finish(self):
        """Done with this order in this shift: the product goes where it belongs."""
        for line in self:
            line._check_open()
            if line.state not in ("progress", "paused"):
                raise UserError(_("Avval ishni boshlang: %s", line.production_id.name))
            line._fill_unrecorded()
            line._post_output()
            line._clock_out()
            wo = line.workorder_id
            if wo.state not in ("done", "cancel"):
                if line.is_final_operation and line.production_id.state == "done":
                    pass  # mark done already finished every work order
                else:
                    wo.button_finish()
            line.write({"state": "done", "date_end": fields.Datetime.now()})
        return True

    def _fill_unrecorded(self):
        """Finished with no result typed: the whole order was made, all 1-sort.

        Otherwise the work order closes with nothing booked and the
        manufacturing order hangs in «to close» with no stock and no report line.
        """
        self.ensure_one()
        if any(e.qty_good or e.qty_second or e.qty_scrap for e in self.entry_ids):
            return
        if self.is_final_operation:
            left = self._order_remaining()
        else:
            left = self.workorder_id.qty_production - self.workorder_id.qty_produced
        if self.product_uom_id.compare(left, 0.0) > 0:
            self.env["cst.production.shift.entry"].create({
                "line_id": self.id, "qty_good": left,
                "note": _("Natija kiritilmasdan yakunlandi — to'liq 1-sort"),
            })

    def action_carry(self):
        """Leave the rest for the next shift: post what was made, keep the order open."""
        for line in self:
            line._check_open()
            if line.state not in ("progress", "paused"):
                continue
            line._post_output()
            line._clock_out()
            wo = line.workorder_id
            if wo.state == "progress":
                wo.button_pending()
            line.write({"state": "carried", "date_end": fields.Datetime.now()})
        return True

    def _sync_external(self):
        """Follow orders finished or cancelled outside this screen.

        The shop also has the Manufacturing app and the Shop Floor; an order
        marked done there would otherwise sit on our line as «in progress»
        with nothing produced. What Odoo already booked is written down as a
        system entry (no stock effect -- that happened out there) and the line
        closes; a cancelled order steps aside.
        """
        now = fields.Datetime.now()
        Entry = self.env["cst.production.shift.entry"].with_context(cst_sync=True)
        for line in self.filtered(lambda l: l.state in ("todo", "progress", "paused")):
            mo, wo = line.production_id, line.workorder_id
            if mo.state == "cancel" or wo.state == "cancel":
                line._clock_out()
                line.write({"state": "carried", "date_end": now})
                continue
            finished_outside = (line.is_final_operation and mo.state == "done") or wo.state == "done"
            if not finished_outside:
                continue
            produced = mo.qty_produced if line.is_final_operation else wo.qty_produced
            missing = produced - line.qty_total
            if line.product_uom_id.compare(missing, 0.0) > 0:
                Entry.create({"line_id": line.id, "qty_good": missing, "posted": True,
                              "note": _("Odoo'da yakunlangan (avtomatik yozuv)")})
            line.entry_ids.filtered(lambda e: not e.posted).write({"posted": True})
            line._clock_out()
            line.write({"state": "done", "date_end": now})

    def _clock_out(self):
        self.ensure_one()
        wo = self.workorder_id
        working = wo.employee_ids
        if working:
            wo.stop_employee(working.ids)

    # ------------------------------------------------------------------ stock
    def _post_output(self):
        """Book the results entered so far.

        Final operation: the counted pieces (1-sort + 2-sort + brak) are
        produced, then brak is scrapped and 2-sort is regraded to its twin
        product. A shift that made less than the order is left with a backorder
        for the rest. Intermediate operation: the department's output is written
        on the work order; nothing moves in stock yet.
        """
        self.ensure_one()
        started = fields.Datetime.now()
        self._post_output_now()
        self._cst_backdate(started)

    def _cst_backdate(self, since):
        """Results typed after the shift (the 15.10 2-smena entered on 16.10)
        belong to the shift's day: the order's finish date and the stock moves
        it just made are put at the end of the shift. Stock levels do not
        change, only the date the reports read; the accounting entry keeps
        today's date."""
        self.ensure_one()
        moment = self.shift_id._cst_moment()
        if not moment or abs((fields.Datetime.now() - moment).total_seconds()) < 60:
            return
        mo = self.production_id
        moves = self.env["stock.move"].sudo().search([
            ("state", "=", "done"), ("date", ">=", since),
            "|", "|", "|", ("production_id", "=", mo.id), ("raw_material_production_id", "=", mo.id),
            ("scrap_id", "in", self.scrap_ids.ids), ("id", "in", self.second_grade_move_ids.ids),
        ])
        if moves:
            safe = self._cst_backdate_moment(moves, moment)
            if safe != moment:
                # the material reached the line only after the shift (moved in
                # the next morning): dated at the shift end the stock would read
                # below zero in between — the results go to when it arrived
                mo.sudo().message_post(body=_(
                    "Natija smena oxiriga (%(moment)s) sanalmadi: xomashyo omborga smenadan keyin kelgan, "
                    "aks holda o'sha paytdagi qoldiq minus bo'lib ko'rinardi. Harakatlar %(safe)s bilan sanaldi.",
                    moment=fields.Datetime.context_timestamp(self, moment).strftime("%d.%m.%Y %H:%M"),
                    safe=fields.Datetime.context_timestamp(self, safe).strftime("%d.%m.%Y %H:%M")))
                moment = safe
            if moment >= since:
                return
        if moves:
            moves.write({"date": moment})
            moves.move_line_ids.write({"date": moment})
        if mo.state == "done" and mo.date_finished and mo.date_finished >= since:
            mo.sudo().write({"date_finished": moment})
        self.scrap_ids.filtered(lambda s: s.date_done and s.date_done >= since).sudo().write({"date_done": moment})

    @api.model
    def _cst_backdate_moment(self, moves, moment, until=None):
        """The earliest time from ``moment`` on at which these moves can be
        dated without a negative balance: ``moment`` itself, or just after a
        later arrival of what they take, or — failing that — their real time."""
        if self._cst_backdate_ok(moves, moment, until=until):
            return moment
        real = until or max(moves.move_line_ids.mapped("date") or [moment])
        out = moves.move_line_ids.filtered(
            lambda l: l.location_id.usage == "internal" and l.location_id != l.location_dest_id)
        if not out:
            return real
        self.env.cr.execute("""
            SELECT DISTINCT date FROM stock_move_line
             WHERE state = 'done' AND product_id = ANY(%s) AND location_dest_id = ANY(%s)
               AND location_id != location_dest_id AND id != ALL(%s)
               AND date > %s AND date < %s
          ORDER BY date
        """, [out.product_id.ids, out.location_id.ids, moves.move_line_ids.ids, moment, real])
        for (arrival,) in self.env.cr.fetchall():
            candidate = arrival + timedelta(seconds=1)
            if self._cst_backdate_ok(moves, candidate, until=until):
                return candidate
        return real

    @api.model
    def _cst_backdate_ok(self, moves, moment, until=None):
        """Can these done moves be dated ``moment`` without any internal
        location showing a negative balance from then until their own date?

        Only what they take out matters (what they bring in only raises the
        earlier balances). For each product and location: the balance of the
        other done moves at ``moment``, then its lowest point up to the moves'
        current date (or ``until``, their real time when they already carry
        the earlier date), must still cover what the moves take."""
        taken = {}
        ends = {}
        for line in moves.move_line_ids:
            if line.location_id.usage != "internal" or line.location_id == line.location_dest_id:
                continue
            key = (line.product_id.id, line.location_id.id)
            taken[key] = taken.get(key, 0.0) + line.quantity_product_uom
            real = until or line.date
            ends[key] = max(ends.get(key, real), real)
        own = tuple(moves.move_line_ids.ids) or (0,)
        Product = self.env["product.product"]
        for (product_id, location_id), qty in taken.items():
            if ends[(product_id, location_id)] <= moment:
                continue
            self.env.cr.execute("""
                SELECT date, SUM(CASE WHEN location_dest_id = %(loc)s THEN quantity_product_uom
                                      ELSE -quantity_product_uom END)
                  FROM stock_move_line
                 WHERE state = 'done' AND product_id = %(product)s
                   AND (location_id = %(loc)s OR location_dest_id = %(loc)s)
                   AND location_id != location_dest_id
                   AND id NOT IN %(own)s AND date < %(until)s
              GROUP BY date ORDER BY date
            """, {"loc": location_id, "product": product_id, "own": own,
                  "until": ends[(product_id, location_id)]})
            balance = 0.0
            lowest = None
            for day, delta in self.env.cr.fetchall():
                if day > moment and lowest is None:
                    lowest = balance  # the balance at the moment itself
                balance += delta or 0.0
                if lowest is not None:
                    lowest = min(lowest, balance)
            if lowest is None:
                lowest = balance  # nothing moved after the moment
            rounding = Product.browse(product_id).uom_id.rounding or 0.001
            if lowest - qty < -rounding:
                return False
        return True

    def _post_output_now(self):
        self.ensure_one()
        entries = self.entry_ids.filtered(lambda e: not e.posted)
        good = sum(entries.mapped("qty_good"))
        second = sum(entries.mapped("qty_second"))
        scrap = sum(entries.mapped("qty_scrap"))
        total = good + second + scrap
        mo = self.production_id
        wo = self.workorder_id
        # spoiled material (a torn обой on the press) leaves the order's raw
        # stock whatever the stage; it is not a finished piece
        for entry in entries.filtered(lambda e: e.qty_material and e.material_product_id):
            self._scrap_material(mo, wo, entry.material_product_id, entry.qty_material)
        if not entries or not total:
            entries.write({"posted": True})
            return
        uom = mo.product_uom_id
        if self.is_final_operation:
            remaining = mo.product_qty - mo.qty_produced
            if uom.compare(total, remaining) > 0:
                raise UserError(_(
                    "%(order)s: %(total)s dona kiritildi, buyurtmada esa %(left)s dona qoldi. "
                    "Ortiqcha chiqarilgan bo'lsa buyurtma miqdorini oshiring.",
                    order=mo.name, total=total, left=remaining))
            mo.qty_producing = total
            mo._set_qty_producing()
            self._cst_apply_consumption(mo, entries)
            to_backorder = uom.compare(total, remaining) < 0
            # cst_posting_output: this shift line is the one booking the result;
            # the Shop Floor hook on button_mark_done must not book it again
            ctx = dict(skip_backorder=True, skip_consumption=True, skip_immediate=True,
                       skip_redirection=True, cst_posting_output=True,
                       mo_ids_to_backorder=mo.ids if to_backorder else [])
            mo.with_context(**ctx).button_mark_done()
            if to_backorder:
                # Odoo 19 links an order and its backorders through the production group
                backorder = mo.production_group_id.production_ids.filtered(
                    lambda p: p.id != mo.id and p.state not in ("done", "cancel")).sorted("id")[-1:]
                self.backorder_production_id = backorder
            if scrap:
                self._scrap(mo, wo, scrap, self.department_id.scrap_reason_tag_id, _("Brak"))
            # 2-sort per product: the automatic twin, or the one the manager picked
            seconds = {}
            for entry in entries.filtered("qty_second"):
                seconds[entry.second_product_id] = seconds.get(entry.second_product_id, 0.0) + entry.qty_second
            for product, qty in seconds.items():
                self._regrade_second(mo, wo, qty, product or None)
        else:
            wo.qty_produced += good + second
        entries.write({"posted": True})

    def _cst_apply_consumption(self, mo, entries):
        """Raw material as the manager counted it in the result dialog.

        ``_set_qty_producing`` has just filled every raw move with the bill's
        ratio. Where an entry says otherwise (one обой printed instead of two)
        the move gets the counted quantity; for entries that did not touch a
        material its norm share is kept.
        """
        counted = entries.consume_ids
        if not counted:
            return
        raw = mo.move_raw_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        for product in counted.product_id:
            moves = raw.filtered(lambda m: m.product_id == product)
            if not moves:
                continue
            per_unit = sum(m.product_uom._compute_quantity(m.unit_factor, product.uom_id) for m in moves)
            actual = 0.0
            for entry in entries:
                rows = entry.consume_ids.filtered(lambda c: c.product_id == product)
                if rows:
                    actual += sum(rows.mapped("qty"))
                else:
                    actual += (entry.qty_good + entry.qty_second + entry.qty_scrap) * per_unit
            first = moves[0]
            first._set_quantity_done(product.uom_id._compute_quantity(actual, first.product_uom))
            first.picked = True
            for other in moves[1:]:
                other._set_quantity_done(0.0)
            mo.message_post(body=_("%(product)s: haqiqiy sarf %(qty)s %(uom)s (bo'lim oynasidan).",
                                   product=product.cst_base_name(), qty=round(actual, 4), uom=product.uom_id.name))

    def _cst_set_crew(self, employees):
        """Who worked on the order, as ticked in the result dialog; a running
        work order clocks the newcomers in and the ones taken off out."""
        self.ensure_one()
        if employees == self.employee_ids:
            return
        wo = self.workorder_id
        removed = self.employee_ids - employees
        added = employees - self.employee_ids
        # sudo: the shift manager has no read access to hr.employee; the
        # caller (floor.add_entry) checks the crew belongs to the department
        self.sudo().employee_ids = employees
        if self.state != "progress" or wo.state != "progress":
            return
        if added:
            wo.sudo().employee_assigned_ids |= added
            for employee in added:
                wo.sudo().start_employee(employee.id)
        working = removed & wo.employee_ids
        if working:
            wo.stop_employee(working.ids)

    def _scrap(self, mo, wo, qty, reason_tag, label):
        """Scrap ``qty`` of the finished product just produced, with a reason."""
        self.ensure_one()
        Scrap = self.env["stock.scrap"]
        values = {
            "product_id": mo.product_id.id,
            "product_uom_id": mo.product_uom_id.id,
            "scrap_qty": qty,
            "location_id": mo.location_dest_id.id,
            "production_id": mo.id,
            "workorder_id": wo.id if wo.production_id == mo else False,
            "company_id": mo.company_id.id,
            "origin": "%s / %s" % (self.shift_id.display_name, label),
        }
        if reason_tag:
            values["scrap_reason_tag_ids"] = [(6, 0, reason_tag.ids)]
        scrap = Scrap.create(values)
        # do_scrap() rather than action_validate(): the shift already knows the
        # pieces exist (they were produced a moment ago). The warehouse-control
        # module asks for a photo on hand-written write-offs; its own bypass
        # key marks this as a system entry, the shift record is the evidence.
        if not scrap.check_available_qty():
            raise UserError(_(
                "%(product)s: %(qty)s dona brakka chiqarish uchun %(loc)s joyida yetarli qoldiq yo'q.",
                product=mo.product_id.display_name, qty=qty, loc=mo.location_dest_id.display_name))
        scrap.with_context(cst_skip_wh_control=True).do_scrap()
        self.scrap_ids |= scrap
        return scrap

    def _scrap_material(self, mo, wo, product, qty):
        """Brak of a raw material: ``qty`` of ``product`` written off from the
        order's raw-material location, linked to the order."""
        self.ensure_one()
        location = mo.location_src_id
        values = {
            "product_id": product.id,
            "product_uom_id": product.uom_id.id,
            "scrap_qty": qty,
            "location_id": location.id,
            "production_id": mo.id,
            "workorder_id": wo.id if wo.production_id == mo else False,
            "company_id": mo.company_id.id,
            "origin": "%s / %s" % (self.shift_id.display_name, _("Material braki")),
        }
        reason = self.department_id.scrap_reason_tag_id
        if reason:
            values["scrap_reason_tag_ids"] = [(6, 0, reason.ids)]
        scrap = self.env["stock.scrap"].create(values)
        if not scrap.check_available_qty():
            raise UserError(_(
                "%(product)s: %(qty)s %(uom)s brakka chiqarish uchun %(loc)s joyida yetarli qoldiq yo'q.",
                product=product.display_name, qty=qty, uom=product.uom_id.name, loc=location.display_name))
        scrap.with_context(cst_skip_wh_control=True).do_scrap()
        self.scrap_ids |= scrap
        return scrap

    def _regrade_second(self, mo, wo, qty, product=None):
        """2-sort: the first-grade piece leaves as scrap, and a 2-sort product
        arrives in stock -- the one the manager picked, else the automatic twin."""
        self.ensure_one()
        reason = self.env.ref("cst_kerama_shift.scrap_reason_second_grade", raise_if_not_found=False)
        scrap = self._scrap(mo, wo, qty, reason, _("2-sort"))
        twin = product or mo.product_id.cst_get_or_create_second_grade()
        # Odoo 19 stock.move has no `name`; the description carries the label
        move = self.env["stock.move"].create({
            "description_picking": _("2-sort: %s", twin.display_name),
            "product_id": twin.id,
            "product_uom": twin.uom_id.id,
            "product_uom_qty": qty,
            "location_id": scrap.scrap_location_id.id,
            "location_dest_id": mo.location_dest_id.id,
            "company_id": mo.company_id.id,
            "origin": self.shift_id.display_name,
            "picked": True,
            "move_line_ids": [(0, 0, {
                "product_id": twin.id,
                "product_uom_id": twin.uom_id.id,
                "quantity": qty,
                "location_id": scrap.scrap_location_id.id,
                "location_dest_id": mo.location_dest_id.id,
            })],
        })
        move._action_confirm()
        move._action_done()
        self.second_grade_move_ids |= move
        return move

    def action_open_production(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "mrp.production",
                "res_id": self.production_id.id, "view_mode": "form"}

    # ------------------------------------------------------------------ corrections
    def _cst_scrap_location(self):
        self.ensure_one()
        scrap = self.scrap_ids.filtered(lambda s: s.state == "done")[:1]
        if scrap:
            return scrap.scrap_location_id
        return self.env["stock.location"].search([
            ("company_id", "in", (self.company_id.id, False)), ("usage", "=", "inventory")], order="id", limit=1)

    def _cst_done_move(self, product, qty, source, destination, label):
        """A plain done stock move -- the building block of a correction."""
        self.ensure_one()
        move = self.env["stock.move"].sudo().create({
            "description_picking": label,
            "product_id": product.id, "product_uom": product.uom_id.id, "product_uom_qty": qty,
            "location_id": source.id, "location_dest_id": destination.id,
            "company_id": self.company_id.id, "origin": "%s / %s" % (self.shift_id.name, label),
            "picked": True,
            "move_line_ids": [(0, 0, {
                "product_id": product.id, "product_uom_id": product.uom_id.id, "quantity": qty,
                "location_id": source.id, "location_dest_id": destination.id,
            })],
        })
        move._action_confirm()
        move._action_done()
        self.correction_move_ids |= move
        return move

    def _cst_correction_pull_back(self, rows):
        """Hook: bring ``[(product, qty)]`` back from wherever the output was
        sent on to (cst_kerama_wh_flow), before it is taken away here."""
        return True

    def _cst_correction_push(self, rows):
        """Hook: send ``[(product, qty)]`` added by a correction on, the way
        the original output went (cst_kerama_wh_flow)."""
        return True

    def _cst_apply_correction(self, d_good, d_second, d_scrap, second_product=None):
        """Make stock agree with a corrected result: posting a counter-document
        for every difference, never editing what is already done.

        Final operation, order done: fewer pieces → back from the next
        warehouse, then an unbuild of the order (pieces out, materials back);
        more pieces → a small correction order that consumes materials in the
        same proportion as the original. 2-sort and brak move between the
        scrap location, the 2-sort product and the first-grade product.
        Earlier operation: only the work order's produced count changes.
        """
        self.ensure_one()
        mo, wo = self.production_id, self.workorder_id
        uom = mo.product_uom_id
        d_total = d_good + d_second + d_scrap
        if not self.is_final_operation:
            if wo.state != "cancel":
                wo.sudo().qty_produced = max(wo.qty_produced + d_good + d_second, 0.0)
            return
        if mo.state != "done":
            raise UserError(_(
                "%s hali yakunlanmagan: natijani smena ichida o'zgartiring (yangi yozuv), tuzatish faqat "
                "yakunlangan buyurtma uchun.", mo.name))
        main = mo.product_id
        twin = second_product or (self.entry_ids.filtered("second_product_id")[:1].second_product_id) \
            or main.cst_get_or_create_second_grade()
        stock = mo.location_dest_id
        scrap_location = self._cst_scrap_location()
        # 1. what goes down must first come back from the next warehouse
        back = []
        if uom.compare(d_good, 0.0) < 0:
            back.append((main, -d_good))
        if uom.compare(d_second, 0.0) < 0:
            back.append((twin, -d_second))
        if back:
            self._cst_correction_pull_back(back)
        # 2. less 2-sort: the 2-sort pieces go, first-grade ones come back from scrap
        if uom.compare(d_second, 0.0) < 0:
            self._cst_done_move(twin, -d_second, stock, scrap_location, _("2-sort tuzatish (qaytarish)"))
            self._cst_done_move(main, -d_second, scrap_location, stock, _("2-sort tuzatish (1-sortga)"))
        # 3. less brak: the pieces were not spoiled after all
        if uom.compare(d_scrap, 0.0) < 0:
            self._cst_done_move(main, -d_scrap, scrap_location, stock, _("Brak tuzatish (qaytarish)"))
        # 4. more pieces in total: a correction order makes them
        if uom.compare(d_total, 0.0) > 0:
            self._cst_correction_order(d_total)
        # 5. more brak / more 2-sort, the regular way
        if uom.compare(d_scrap, 0.0) > 0:
            self._scrap(mo, wo, d_scrap, self.department_id.scrap_reason_tag_id, _("Brak (tuzatish)"))
        if uom.compare(d_second, 0.0) > 0:
            self._regrade_second(mo, wo, d_second, twin)
        # 6. fewer pieces in total: unbuild them, the materials go back
        if uom.compare(d_total, 0.0) < 0:
            self._cst_correction_unbuild(-d_total)
        # 7. what was added goes on to the next warehouse
        push = []
        if uom.compare(d_good, 0.0) > 0:
            push.append((main, d_good))
        if uom.compare(d_second, 0.0) > 0:
            push.append((twin, d_second))
        if push:
            self._cst_correction_push(push)

    def _cst_correction_order(self, qty):
        """``qty`` more pieces of the order's product, made by a small order
        that eats the materials the original one ate per piece."""
        self.ensure_one()
        mo = self.production_id
        produced = mo.qty_produced or mo.product_qty
        materials = {}
        for move in mo.move_raw_ids.filtered(lambda m: m.state == "done"):
            used = move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)
            materials[move.product_id.id] = materials.get(move.product_id.id, 0.0) + used * qty / produced
        Production = self.env["mrp.production"].sudo().with_company(mo.company_id).with_context(
            cst_flow_department_id=self.department_id.id, from_project_action=True)
        fix = Production.create({
            "product_id": mo.product_id.id, "product_qty": qty, "product_uom_id": mo.product_uom_id.id,
            "bom_id": mo.bom_id.id, "company_id": mo.company_id.id,
            "picking_type_id": mo.picking_type_id.id,
            "location_src_id": mo.location_src_id.id, "location_dest_id": mo.location_dest_id.id,
            "origin": _("Tuzatish: %(mo)s · %(shift)s", mo=mo.name, shift=self.shift_id.name),
        })
        self.env["cst.mo.builder"]._mo_apply_materials(
            fix, [{"product_id": pid, "qty": q} for pid, q in materials.items() if q > 0])
        fix.action_confirm()
        fix.action_assign()
        fix.qty_producing = qty
        fix._set_qty_producing()
        for move in fix.move_raw_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        fix.with_context(skip_backorder=True, skip_consumption=True, skip_immediate=True,
                         skip_redirection=True, cst_posting_output=True).button_mark_done()
        if fix.state != "done":
            raise UserError(_("Tuzatish buyurtmasi %s yakunlanmadi (xomashyo yetarlimi?).", fix.name))
        moment = self.shift_id._cst_moment()
        fix.write({"date_finished": moment})
        self.correction_production_ids |= fix
        fix.message_post(body=_("Smena natijasi tuzatildi: %(line)s, +%(qty)s dona.",
                                line=self.shift_id.display_name, qty=qty))
        return fix

    def _cst_correction_unbuild(self, qty):
        """Take ``qty`` pieces back out of the order: product out of stock,
        its materials back where they came from."""
        self.ensure_one()
        mo = self.production_id
        unbuild = self.env["mrp.unbuild"].sudo().create({
            "product_id": mo.product_id.id, "bom_id": mo.bom_id.id, "mo_id": mo.id,
            "product_qty": qty, "product_uom_id": mo.product_uom_id.id,
            "location_id": mo.location_dest_id.id, "location_dest_id": mo.location_src_id.id,
            "company_id": mo.company_id.id,
        })
        unbuild.action_unbuild()
        self.unbuild_ids |= unbuild
        return unbuild
