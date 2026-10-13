from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CstPickingUnloader(models.Model):
    """One unloader on one document, and what they are paid for it.

    A line per person rather than a total to divide: a wagon crew is not
    always paid in equal shares, and the foreman's cut should be visible on
    the document instead of hidden in an arithmetic rule.
    """

    _name = "cst.picking.unloader"
    _description = "Unloading Payment"
    _order = "picking_id, id"
    _check_company_auto = True

    picking_id = fields.Many2one(
        "stock.picking", required=True, index=True, ondelete="cascade",
        check_company=True)
    employee_id = fields.Many2one(
        "hr.employee", required=True, index=True, ondelete="restrict",
        check_company=True)
    company_id = fields.Many2one(
        "res.company", related="picking_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    amount = fields.Monetary(
        required=True, currency_field="currency_id",
        default=lambda self: self.env.company.cst_unload_rate_default,
        help="Шу ходимга шу юкни туширганлик учун туланадиган сумма.")
    note = fields.Char(help="Вагон раками, смена, ёки бошка изох.")

    # Read straight off the payroll line so the document can show whether the
    # money has actually been accrued yet.
    payroll_line_ids = fields.One2many(
        "cst.payroll.line", compute="_compute_payroll_line_ids",
        string="Payroll Lines")
    is_accrued = fields.Boolean(compute="_compute_payroll_line_ids", string="Accrued")

    _amount_not_zero = models.Constraint(
        "CHECK(amount != 0)",
        "An unloading payment of zero has nothing to record.",
    )
    _employee_once_per_picking = models.Constraint(
        "unique(picking_id, employee_id)",
        "That employee is already on this document — change the amount instead "
        "of adding a second line.",
    )

    def _compute_payroll_line_ids(self):
        lines = self.env["cst.payroll.line"].search([
            ("source_model", "=", self._name),
            ("source_id", "in", self.ids),
            ("state", "!=", "cancel"),
        ])
        by_source = {}
        for line in lines:
            by_source.setdefault(line.source_id, self.env["cst.payroll.line"])
            by_source[line.source_id] |= line
        for unloader in self:
            found = by_source.get(unloader.id, self.env["cst.payroll.line"])
            unloader.payroll_line_ids = found
            unloader.is_accrued = bool(found)

    @api.depends("picking_id.name", "employee_id")
    def _compute_display_name(self):
        # The payroll line's "Source" column shows this, and there it has to
        # name the document — the employee is already its own column.
        for unloader in self:
            unloader.display_name = " — ".join(filter(None, (
                unloader.picking_id.name, unloader.employee_id.display_name)))

    def _cst_source_redirect(self):
        """A payroll line pointing here should open the receipt, not this line."""
        return self.picking_id

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        if self.employee_id and not self.amount:
            self.amount = self.company_id.cst_unload_rate_default \
                or self.env.company.cst_unload_rate_default

    # ------------------------------------------------------------------
    # Once accrued, settled
    # ------------------------------------------------------------------
    def _check_not_accrued(self, action):
        accrued = self.filtered("is_accrued")
        if accrued:
            raise UserError(_(
                "«%(names)s» учун юк тушириш суммаси аллакачон ойликка "
                "хисобланган, шунинг учун уни %(action)s мумкин эмас.\n\n"
                "Ойлик даврини коралама холатига кайтариб, кайта хисоблангандан "
                "сунг узгартириш мумкин булади.",
                names=", ".join(accrued.employee_id.mapped("display_name")),
                action=action))

    def write(self, vals):
        if set(vals) & {"employee_id", "amount", "picking_id"}:
            self._check_not_accrued(_("узгартириш"))
        return super().write(vals)

    def unlink(self):
        self._check_not_accrued(_("учириш"))
        return super().unlink()
