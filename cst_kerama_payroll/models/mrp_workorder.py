from odoo import fields, models

SHIFTS = [
    ("1", "1-smena"),
    ("2", "2-smena"),
]


class MrpWorkorder(models.Model):
    """Report #22 reads по участку и смене, and the shift is the one thing the
    system cannot know by itself — so the operator says which it was."""

    _inherit = "mrp.workorder"

    cst_shift = fields.Selection(
        SHIFTS, string="Smena", index="btree_not_null", copy=False,
        help="Кайси сменада бажарилди.  Ишбай хисоботи участка ва смена "
             "буйича гурухланади.")

    def _cst_kpi_operation(self):
        """The bill-of-materials operation whose rate this work order is paid at.

        Normally the operation it was generated from.  Work orders added by
        hand — the Start Manufacturing wizard does exactly that — carry no
        operation at all, so fall back to an operation of the same name on a
        bill of materials for the same finished product: its name is the only
        record of what work was done.

        Returned even when its rate is zero, so the caller can tell an
        unpriced operation apart from one the product's routing never had.
        """
        self.ensure_one()
        if self.operation_id:
            return self.operation_id
        product = self.production_id.product_id
        if not (self.name and product):
            return self.env["mrp.routing.workcenter"]
        # The order's own bill of materials first, then any other for the same
        # product (alternative MDF-brand BoMs share the same operations).
        boms = self.production_id.bom_id | self.env["mrp.bom"].search([
            ("company_id", "in", (self.company_id.id, False)),
            "|",
            ("product_id", "=", product.id),
            ("product_tmpl_id", "=", product.product_tmpl_id.id),
        ])
        matches = boms.operation_ids.filtered(lambda op: op.name == self.name)
        priced = matches.filtered("cst_kpi_rate")
        return priced[:1] or matches[:1]

    def _cst_kpi_rate(self):
        self.ensure_one()
        return self._cst_kpi_operation().cst_kpi_rate

    def _cst_kpi_employees(self):
        """Who is paid for this work order.

        The employees who actually clocked time on it, because that is the only
        record of who stood at the machine.  Falling back to the assignment
        keeps an order that was closed without a timer from paying nobody.
        """
        self.ensure_one()
        worked = self.time_ids.employee_id
        return worked or self.employee_assigned_ids or self.employee_ids
