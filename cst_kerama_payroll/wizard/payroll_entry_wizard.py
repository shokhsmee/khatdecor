from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CstPayrollEntryWizard(models.TransientModel):
    """Write a bonus or a fine for several people in one pass.

    The payroll line form can do one person at a time, which is fine for a
    fine and hopeless for a crew that unloaded a wagon at six in the morning.
    """

    _name = "cst.payroll.entry.wizard"
    _description = "Bonus / jarima yozish"

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company)
    component_id = fields.Many2one(
        "cst.payroll.component", string="Nima uchun", required=True,
        domain="[('kind', 'in', ('accrual', 'deduction'))]",
        help="Бонус, жарима ёки бошка тулов тури.")
    kind = fields.Selection(related="component_id.kind", string="Turi")
    date = fields.Date(required=True, default=fields.Date.context_today)
    period_id = fields.Many2one(
        "cst.payroll.period", string="Davr",
        domain="[('company_id', '=', company_id), ('state', 'in', ('draft', 'computed'))]",
        help="Ихтиёрий.  Курсатилмаса, катор санаси буйича хисоботга тушади.")
    note = fields.Char(string="Umumiy izoh")

    # Filling the list: pick people, give the amount once.
    employee_ids = fields.Many2many(
        "hr.employee", string="Xodimlar",
        domain="[('company_id', '=', company_id)]")
    default_amount = fields.Monetary(
        string="Har biriga", currency_field="currency_id")
    currency_id = fields.Many2one(related="company_id.currency_id")

    line_ids = fields.One2many(
        "cst.payroll.entry.wizard.line", "wizard_id", string="Qatorlar")
    total = fields.Monetary(compute="_compute_total", currency_field="currency_id")

    @api.depends("line_ids.amount")
    def _compute_total(self):
        for wizard in self:
            wizard.total = sum(wizard.line_ids.mapped("amount"))

    def action_fill(self):
        """Turn the chosen people into rows, without touching rows already there."""
        self.ensure_one()
        if not self.employee_ids:
            raise UserError(_("Аввал ходимларни танланг."))
        existing = self.line_ids.employee_id
        new_lines = [
            (0, 0, {"employee_id": employee.id, "amount": self.default_amount})
            for employee in self.employee_ids - existing
        ]
        self.write({"line_ids": new_lines, "employee_ids": [(5, 0, 0)]})
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_create(self):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda line: line.employee_id and line.amount)
        if not lines:
            raise UserError(_("Бирорта катор тулдирилмаган."))
        if self.period_id and self.period_id.state not in ("draft", "computed"):
            raise UserError(_(
                "«%s» даври тасдикланган — унга янги катор кушиб булмайди.",
                self.period_id.name))

        payroll_lines = self.env["cst.payroll.line"].create([{
            "employee_id": line.employee_id.id,
            "component_id": self.component_id.id,
            "company_id": self.company_id.id,
            "date": self.date,
            "period_id": self.period_id.id or False,
            "amount": line.amount,
            "name": self.component_id.name,
            "note": line.note or self.note or False,
            # Written by a person: a recompute must leave it alone.
            "is_manual": True,
        } for line in lines])

        return {
            "type": "ir.actions.act_window",
            "name": _("%(component)s — %(count)s ta xodim",
                      component=self.component_id.name, count=len(payroll_lines)),
            "res_model": "cst.payroll.line",
            "view_mode": "list,form",
            "domain": [("id", "in", payroll_lines.ids)],
        }


class CstPayrollEntryWizardLine(models.TransientModel):
    _name = "cst.payroll.entry.wizard.line"
    _description = "Bonus / jarima qatori"

    wizard_id = fields.Many2one("cst.payroll.entry.wizard", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="wizard_id.company_id")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    employee_id = fields.Many2one(
        "hr.employee", required=True, domain="[('company_id', '=', company_id)]")
    amount = fields.Monetary(required=True, currency_field="currency_id")
    balance = fields.Monetary(
        related="employee_id.cst_payroll_balance", string="Hozirgi qoldiq",
        currency_field="currency_id")
    note = fields.Char(string="Izoh")
