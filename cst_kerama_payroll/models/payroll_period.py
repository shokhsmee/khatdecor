from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CstPayrollPeriod(models.Model):
    """A payroll month.  It is the gate: nothing reaches the ledger until a
    period is confirmed, and posting is a single, reversible step."""

    _name = "cst.payroll.period"
    _description = "Payroll Period"
    _order = "date_from desc, id desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    date_from = fields.Date(required=True, tracking=True)
    date_to = fields.Date(required=True, tracking=True)
    date_posted = fields.Date(
        string="Accounting Date", tracking=True,
        help="Date of the journal entry.  Defaults to the last day of the period.")
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("computed", "Computed"),
            ("confirmed", "Confirmed"),
            ("posted", "Posted"),
            ("closed", "Closed"),
        ],
        default="draft", required=True, tracking=True, readonly=True, copy=False)

    line_ids = fields.One2many("cst.payroll.line", "period_id")
    line_count = fields.Integer(compute="_compute_totals")
    employee_count = fields.Integer(compute="_compute_totals")
    total_accrued = fields.Monetary(compute="_compute_totals", currency_field="currency_id")
    total_deducted = fields.Monetary(compute="_compute_totals", currency_field="currency_id")
    total_employer = fields.Monetary(compute="_compute_totals", currency_field="currency_id")
    move_id = fields.Many2one(
        "account.move", string="Journal Entry", readonly=True, copy=False,
        index="btree_not_null")

    _dates_ordered = models.Constraint(
        "CHECK(date_from <= date_to)",
        "A payroll period must end on or after it starts.",
    )

    @api.depends("line_ids.signed_amount", "line_ids.amount", "line_ids.kind")
    def _compute_totals(self):
        for period in self:
            lines = period.line_ids
            period.line_count = len(lines)
            period.employee_count = len(lines.employee_id)
            period.total_accrued = sum(
                lines.filtered(lambda l: l.kind == "accrual").mapped("amount"))
            period.total_deducted = sum(
                lines.filtered(lambda l: l.kind == "deduction").mapped("amount"))
            period.total_employer = sum(
                lines.filtered(lambda l: l.kind == "employer").mapped("amount"))

    @api.onchange("date_to")
    def _onchange_date_to(self):
        if self.date_to and not self.date_posted:
            self.date_posted = self.date_to

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    def action_compute(self):
        """Rebuild the automatic lines.  Hand-entered lines are left alone."""
        for period in self:
            if period.state not in ("draft", "computed"):
                raise UserError(_(
                    "“%s” is already confirmed.  Reset it to draft before recomputing.",
                    period.name))
            period._clear_generated_lines()
            period._adopt_external_lines()
            vals = []
            vals += period._collect_wage_lines()
            vals += period._collect_kpi_lines()
            period.env["cst.payroll.line"].create(vals)
            # Taxes read the accruals that were just written.
            period.env["cst.payroll.line"].create(period._collect_tax_lines())
            period.state = "computed"
        return True

    def _clear_generated_lines(self):
        """Drop draft lines this module generated, keeping manual entries."""
        self.ensure_one()
        generated = self.line_ids.filtered(
            lambda line: line.state == "draft"
            and not line.is_manual
            and line.component_id.computation != "manual")
        generated.unlink()

    def _adopt_external_lines(self):
        """Pull in the lines other documents booked in this period (kassa
        advances) that were written before the period existed."""
        self.ensure_one()
        self.env["cst.payroll.line"].search([
            ("company_id", "=", self.company_id.id),
            ("is_external", "=", True),
            ("period_id", "=", False),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
        ]).write({"period_id": self.id})

    def _employees(self):
        """Employees to pay this period: hired on or before it ends, and not
        departed before it starts."""
        self.ensure_one()
        return self.env["hr.employee"].search([
            ("company_id", "=", self.company_id.id),
            ("active", "=", True),
        ]).filtered(lambda employee: not (
            employee.departure_date and employee.departure_date < self.date_from))

    def _component(self, xmlid):
        component = self.env.ref(f"cst_kerama_payroll.{xmlid}", raise_if_not_found=False)
        if not component:
            raise UserError(_(
                "Payroll component “%s” is missing.  Reinstall or upgrade the "
                "module to restore the default components.", xmlid))
        return component

    def _line_defaults(self, employee, component, amount, **extra):
        self.ensure_one()
        vals = {
            "employee_id": employee.id,
            "component_id": component.id,
            "is_manual": False,
            "period_id": self.id,
            "company_id": self.company_id.id,
            "date": self.date_to,
            "amount": amount,
            "name": component.name,
        }
        vals.update(extra)
        return vals

    def _collect_wage_lines(self):
        """Monthly salary, split into its official and cash halves.

        A period shorter than the month — or an employee who started or left
        inside it — is paid pro rata on calendar days, and the official/cash
        ratio is preserved through that proration.
        """
        self.ensure_one()
        component = self._component("component_oylik")
        currency = self.company_id.currency_id
        month_start = fields.Date.start_of(self.date_to, "month")
        month_end = fields.Date.end_of(self.date_to, "month")
        month_days = (month_end - month_start).days + 1

        vals = []
        for employee in self._employees():
            version = employee._get_version(self.date_to)
            if not version or version.cst_salary_scheme == "kpi":
                continue
            wage = version.wage or 0.0
            if currency.is_zero(wage):
                continue

            paid_days = self._paid_days(employee)
            if paid_days <= 0:
                continue
            factor = min(paid_days / month_days, 1.0)

            official = min(version.cst_official_wage or 0.0, wage) * factor
            total = wage * factor
            cash = total - official
            if not currency.is_zero(official):
                vals.append(self._line_defaults(
                    employee, component, currency.round(official), is_official=True))
            if not currency.is_zero(cash):
                vals.append(self._line_defaults(
                    employee, component, currency.round(cash), is_official=False))
        return vals

    def _paid_days(self, employee):
        """Calendar days of this period the employee was actually employed."""
        self.ensure_one()
        start, end = self.date_from, self.date_to
        version = employee._get_version(self.date_to)
        hired = version.contract_date_start
        left = version.contract_date_end or employee.departure_date
        if hired and hired > start:
            start = hired
        if left and left < end:
            end = left
        if start > end:
            return 0
        return (end - start).days + 1

    def _collect_kpi_lines(self):
        """The KPI engines.  Sales is wired up; manufacturing and unloading
        follow the same shape and append to the same list."""
        self.ensure_one()
        return (self._collect_kpi_sales_lines()
                + self._collect_kpi_production_lines()
                + self._collect_kpi_unloading_lines())

    # ------------------------------------------------------------------
    # Sales KPI
    # ------------------------------------------------------------------
    def _employee_by_user(self):
        """{user id: employee} — how a salesperson on an order becomes someone
        the payroll can pay.  An employee with no user can never earn sales KPI."""
        self.ensure_one()
        return {
            employee.user_id.id: employee
            for employee in self._employees().filtered("user_id")
        }

    def _kpi_accrued_source_ids(self, component, source_model):
        """Source documents whose KPI has already been written, in any period.

        This period's own generated drafts are cleared before collection, so
        whatever is left belongs to another period or is already confirmed —
        either way it must not be paid twice.
        """
        self.ensure_one()
        lines = self.env["cst.payroll.line"].search([
            ("component_id", "=", component.id),
            ("source_model", "=", source_model),
            ("company_id", "=", self.company_id.id),
            ("state", "!=", "cancel"),
        ])
        return set(lines.mapped("source_id"))

    def _collect_kpi_sales_lines(self):
        """Sales-manager KPI: rate per unit sold, accrued when the customer has
        paid in full.

        The quantity is the *posted invoiced* quantity, so a return credited
        through cst_kerama_sale_return takes its KPI back with it.  The rate is
        copied onto the line, never re-read, which is what lets a rate change
        today leave last month alone.
        """
        self.ensure_one()
        component = self._component("component_bonus_kpi")
        currency = self.company_id.currency_id
        by_user = self._employee_by_user()
        accrued = self._kpi_accrued_source_ids(component, "sale.order")

        orders = self.env["sale.order"].search([
            ("company_id", "=", self.company_id.id),
            ("state", "=", "sale"),
            ("invoice_status", "=", "invoiced"),
        ])

        vals = []
        skipped_no_employee = self.env["sale.order"]
        skipped_not_on_kpi = self.env["sale.order"]
        skipped_no_rate = self.env["product.product"]

        for order in orders:
            if order.id in accrued:
                continue
            paid_on = order._cst_kpi_paid_date()
            if not paid_on or not (self.date_from <= paid_on <= self.date_to):
                continue

            employee = by_user.get(order.user_id.id)
            if not employee:
                skipped_no_employee |= order
                continue
            version = employee._get_version(self.date_to)
            if not version or version.cst_salary_scheme not in ("kpi", "mixed"):
                skipped_not_on_kpi |= order
                continue

            # One line per product, not per order line, so the report reads
            # like the Excel it replaces: manager -> category -> product.
            per_product = {}
            for line in order.order_line:
                if line.display_type or not line.product_id:
                    continue
                quantity = line.qty_invoiced_posted
                if not quantity:
                    continue
                product = line.product_id
                # the variant's own rate when it has one, the template's otherwise
                if not product.cst_kpi_rate_effective:
                    skipped_no_rate |= product
                    continue
                per_product[product] = per_product.get(product, 0.0) + quantity

            for product, quantity in per_product.items():
                rate = product.cst_kpi_rate_effective
                amount = currency.round(quantity * rate)
                if currency.is_zero(amount):
                    continue
                vals.append(self._line_defaults(
                    employee, component, amount,
                    date=paid_on,
                    product_id=product.id,
                    quantity=quantity,
                    rate=rate,
                    source_model="sale.order",
                    source_id=order.id,
                    name=_("%(component)s — %(order)s",
                           component=component.name, order=order.name),
                ))

        self._log_kpi_sales_skips(
            skipped_no_employee, skipped_not_on_kpi, skipped_no_rate)
        return vals

    def _log_kpi_sales_skips(self, no_employee, not_on_kpi, no_rate):
        """Say out loud what was passed over.

        Silence here is how KPI quietly goes missing: an order whose
        salesperson is not an employee, or a product nobody priced, simply
        earns nothing.  The period's chatter is where that gets noticed.
        """
        self.ensure_one()
        blocks = []
        if no_employee:
            blocks.append(self._kpi_skip_block(
                _("Сотувчиси ходим эмас"),
                _("Ходим картасида «Related User» тулдирилиши керак"),
                no_employee.mapped("name")))
        if not_on_kpi:
            blocks.append(self._kpi_skip_block(
                _("Иш хаки схемаси «Salary only»"),
                _("KPI олмайдиган ходимларнинг буюртмалари"),
                not_on_kpi.mapped("name")))
        if no_rate:
            blocks.append(self._kpi_skip_block(
                _("KPI ставкаси белгиланмаган махсулотлар"),
                _("махсулот картасидаги «Sotuv KPI» майдонини тулдиринг"),
                no_rate.mapped("display_name")))
        self._kpi_post_blocks(blocks)

    def _kpi_skip_block(self, title, hint, names):
        """One line of the chatter note.  Built through Markup so a product
        name containing a bracket cannot break the message."""
        return Markup("<b>%s</b> — %s: %s") % (
            title, hint, ", ".join(sorted(set(names))))

    def _kpi_post_blocks(self, blocks):
        blocks = [block for block in blocks if block]
        if blocks:
            self.message_post(body=Markup("<br/>").join(blocks))

    # ------------------------------------------------------------------
    # Production KPI (ишбай)
    # ------------------------------------------------------------------
    def _kpi_accrued_workorder_keys(self, component):
        """{(work order id, employee id)} already paid, in any period.

        Production pays every worker on an order in full, so the same work
        order legitimately produces several lines — the pair is the key, not
        the order.
        """
        self.ensure_one()
        lines = self.env["cst.payroll.line"].search([
            ("component_id", "=", component.id),
            ("source_model", "=", "mrp.workorder"),
            ("company_id", "=", self.company_id.id),
            ("state", "!=", "cancel"),
        ])
        return {(line.source_id, line.employee_id.id) for line in lines}

    def _collect_kpi_production_lines(self):
        """Piece rate (ишбай иш хаки): quantity produced x the rate on the
        product's own BOM operation, paid to everyone who worked the order.

        Accrues when the work order is finished, dated by the day it finished —
        so a period recomputed later cannot pull work into the wrong month.
        """
        self.ensure_one()
        component = self._component("component_ishbay")
        currency = self.company_id.currency_id
        employees = self._employees()
        accrued = self._kpi_accrued_workorder_keys(component)

        workorders = self.env["mrp.workorder"].search([
            ("company_id", "=", self.company_id.id),
            ("state", "=", "done"),
            ("date_finished", ">=", fields.Datetime.to_datetime(self.date_from)),
            ("date_finished", "<=",
             fields.Datetime.to_datetime(self.date_to).replace(
                 hour=23, minute=59, second=59)),
        ])

        vals = []
        skipped_no_employee = self.env["mrp.workorder"]
        skipped_not_on_kpi = self.env["hr.employee"]
        skipped_no_rate = self.env["mrp.workorder"]
        skipped_no_shift = self.env["mrp.workorder"]
        skipped_no_operation = self.env["mrp.workorder"]

        for workorder in workorders:
            quantity = workorder.qty_produced
            if not quantity:
                continue
            operation = workorder._cst_kpi_operation()
            rate = operation.cst_kpi_rate
            if not rate:
                # Two different problems, and they need two different fixes.
                if operation:
                    skipped_no_rate |= workorder
                else:
                    skipped_no_operation |= workorder
                continue
            workers = workorder._cst_kpi_employees()
            if not workers:
                skipped_no_employee |= workorder
                continue
            if not workorder.cst_shift:
                # Not a reason to withhold pay — only to say the report will
                # have a blank column for it.
                skipped_no_shift |= workorder

            amount = currency.round(quantity * rate)
            if currency.is_zero(amount):
                continue

            for worker in workers:
                if worker not in employees:
                    skipped_not_on_kpi |= worker
                    continue
                version = worker._get_version(self.date_to)
                if not version or version.cst_salary_scheme not in ("kpi", "mixed"):
                    skipped_not_on_kpi |= worker
                    continue
                if (workorder.id, worker.id) in accrued:
                    continue
                vals.append(self._line_defaults(
                    worker, component, amount,
                    date=workorder.date_finished.date(),
                    product_id=workorder.production_id.product_id.id,
                    quantity=quantity,
                    rate=rate,
                    cst_operation_name=workorder.name,
                    cst_workcenter_id=workorder.workcenter_id.id,
                    cst_shift=workorder.cst_shift,
                    source_model="mrp.workorder",
                    source_id=workorder.id,
                    name=_("%(component)s — %(operation)s / %(order)s",
                           component=component.name, operation=workorder.name,
                           order=workorder.production_id.name),
                ))

        self._log_kpi_production_skips(
            skipped_no_employee, skipped_not_on_kpi, skipped_no_rate,
            skipped_no_shift, skipped_no_operation)
        return vals

    def _log_kpi_production_skips(self, no_employee, not_on_kpi, no_rate,
                                  no_shift, no_operation):
        """Same reasoning as the sales version: unpaid work must be visible."""
        self.ensure_one()
        blocks = []
        if no_rate:
            blocks.append(self._kpi_skip_block(
                _("Ишбай ставкаси белгиланмаган операциялар"),
                _("спецификация (BoM) ичидаги операция каторида «Ishbay KPI» "
                  "майдонини тулдиринг"),
                [f"{wo.production_id.product_id.display_name} / {wo.name}"
                 for wo in no_rate]))
        if no_operation:
            blocks.append(self._kpi_skip_block(
                _("Спецификацияда бундай операция йук"),
                _("иш буюртмаси кулда кушилган ва махсулотнинг хеч бир "
                  "спецификациясида шу номли операция мавжуд эмас — операцияни "
                  "спецификацияга кушиб, ставкасини белгиланг"),
                [f"{wo.production_id.product_id.display_name} / {wo.name}"
                 for wo in no_operation]))
        if no_employee:
            blocks.append(self._kpi_skip_block(
                _("Ким ишлагани маълум эмас"),
                _("иш буюртмасида таймер босилмаган ва ходим тайинланмаган"),
                [f"{wo.production_id.name} / {wo.name}" for wo in no_employee]))
        if not_on_kpi:
            blocks.append(self._kpi_skip_block(
                _("Ишбай олмайдиган ходимлар"),
                _("иш хаки схемаси KPI'ни уз ичига олмайди ёки бошка компанияда"),
                not_on_kpi.mapped("display_name")))
        if no_shift:
            blocks.append(self._kpi_skip_block(
                _("Смена курсатилмаган"),
                _("хисобланди, лекин хисоботда смена устуни буш булади"),
                [f"{wo.production_id.name} / {wo.name}" for wo in no_shift]))
        self._kpi_post_blocks(blocks)

    # ------------------------------------------------------------------
    # Unloading KPI (юк тушириш)
    # ------------------------------------------------------------------
    def _collect_kpi_unloading_lines(self):
        """Юк тушириш: the amounts the warehouse wrote on the document itself.

        Nothing is calculated here — the crew and the money were agreed at the
        dock.  The period's job is only to move validated ones onto the salary
        account, once, dated by the day the goods actually arrived.
        """
        self.ensure_one()
        component = self._component("component_yuk_tushirish")
        currency = self.company_id.currency_id
        employees = self._employees()

        unloaders = self.env["cst.picking.unloader"].search([
            ("company_id", "=", self.company_id.id),
            ("picking_id.state", "=", "done"),
            ("picking_id.date_done", ">=", fields.Datetime.to_datetime(self.date_from)),
            ("picking_id.date_done", "<=",
             fields.Datetime.to_datetime(self.date_to).replace(
                 hour=23, minute=59, second=59)),
        ])
        accrued = self._kpi_accrued_source_ids(component, "cst.picking.unloader")

        vals = []
        skipped_not_on_kpi = self.env["hr.employee"]
        for unloader in unloaders:
            if unloader.id in accrued:
                continue
            if currency.is_zero(unloader.amount):
                continue
            employee = unloader.employee_id
            if employee not in employees:
                skipped_not_on_kpi |= employee
                continue
            version = employee._get_version(self.date_to)
            if not version or version.cst_salary_scheme not in ("kpi", "mixed"):
                skipped_not_on_kpi |= employee
                continue
            picking = unloader.picking_id
            vals.append(self._line_defaults(
                employee, component, unloader.amount,
                date=picking.date_done.date(),
                quantity=1,
                rate=unloader.amount,
                source_model="cst.picking.unloader",
                source_id=unloader.id,
                note=unloader.note,
                name=_("%(component)s — %(picking)s",
                       component=component.name, picking=picking.name),
            ))

        if skipped_not_on_kpi:
            self._kpi_post_blocks([self._kpi_skip_block(
                _("Юк тушириш: KPI олмайдиган ходимлар"),
                _("иш хаки схемаси KPI'ни уз ичига олмайди ёки бошка компанияда"),
                skipped_not_on_kpi.mapped("display_name"))])
        return vals

    def _collect_tax_lines(self):
        """Income tax and pension withheld from the employee, social tax borne
        by the employer — all on the official, taxable base only."""
        self.ensure_one()
        company = self.company_id
        currency = company.currency_id
        rates = [
            ("component_soliq_jshds", company.cst_income_tax_rate),
            ("component_inps", company.cst_pension_rate),
            ("component_soliq_ijtimoiy", company.cst_social_tax_rate),
        ]
        if all(not rate for _xmlid, rate in rates):
            return []

        bases = {}
        for line in self.line_ids:
            if line.kind == "accrual" and line.is_taxable:
                bases[line.employee_id] = bases.get(line.employee_id, 0.0) + line.amount

        vals = []
        for xmlid, rate in rates:
            if not rate:
                continue
            component = self._component(xmlid)
            for employee, base in bases.items():
                amount = currency.round(base * rate / 100.0)
                if currency.is_zero(amount):
                    continue
                vals.append(self._line_defaults(
                    employee, component, amount, is_official=True))
        return vals

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_confirm(self):
        for period in self:
            if period.state not in ("draft", "computed"):
                raise UserError(_("“%s” is already confirmed.", period.name))
            if not period.line_ids:
                raise UserError(_(
                    "“%s” has no lines.  Compute it, or add lines by hand.", period.name))
            period.line_ids.filtered(lambda line: line.state == "draft").state = "confirmed"
            period.state = "confirmed"
        return True

    def action_post(self):
        for period in self:
            if period.state != "confirmed":
                raise UserError(_(
                    "Confirm “%s” before posting it to the ledger.", period.name))
            journal = period.company_id.cst_payroll_journal_id
            if not journal:
                raise UserError(_(
                    "No payroll journal set for %s.\n\n"
                    "Settings ▸ Payroll ▸ Salary Journal.", period.company_id.display_name))
            lines = period.line_ids.filtered(lambda line: line.state == "confirmed")
            if not lines:
                raise UserError(_("“%s” has nothing left to post.", period.name))

            move = period.env["account.move"].create({
                "journal_id": journal.id,
                "company_id": period.company_id.id,
                "date": period.date_posted or period.date_to,
                "ref": _("Payroll — %s", period.name),
                "line_ids": lines._move_line_vals(period.date_posted or period.date_to),
            })
            move.action_post()
            lines.write({"state": "posted", "move_id": move.id})
            period.move_id = move
            period.state = "posted"
        return True

    def action_close(self):
        for period in self:
            if period.state != "posted":
                raise UserError(_("Only a posted period can be closed."))
            period.state = "closed"
        return True

    def action_reset_to_draft(self):
        """Undo posting.  The journal entry is reversed rather than deleted, so
        the audit trail survives."""
        for period in self:
            if period.state == "closed":
                raise UserError(_(
                    "“%s” is closed.  Reopen it deliberately before changing anything.",
                    period.name))
            if period.move_id:
                if period.move_id.state == "posted":
                    period.move_id._reverse_moves(cancel=True)
                else:
                    period.move_id.button_draft()
                    period.move_id.unlink()
                period.move_id = False
            # Lines booked by another document keep their own entry and state.
            period.line_ids.filtered(lambda line: not line.is_external).write(
                {"state": "draft", "move_id": False})
            period.state = "draft"
        return True

    def action_reopen(self):
        for period in self:
            if period.state == "closed":
                period.state = "posted"
        return True

    def action_view_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Payroll Lines — %s", self.name),
            "res_model": "cst.payroll.line",
            "view_mode": "list,form",
            "domain": [("period_id", "=", self.id)],
            "context": {"default_period_id": self.id, "default_company_id": self.company_id.id},
        }

    def action_view_move(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": self.move_id.id,
            "view_mode": "form",
        }
