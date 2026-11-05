from odoo import api, fields, models


class CstProductionFactReport(models.AbstractModel):
    """«Ishlab chiqarish fakti» for shift work: dated by the shift.

    What a shift booked on an order's last operation is counted from the
    shift's results (corrections included), on the shift's date -- the 15.10
    2-smena typed on 16.10 is 15.10 output. Orders finished without a shift
    keep the order's finish date.
    """

    _inherit = "cst.production.fact.report"

    @api.model
    def build(self, date_from, date_to, company_ids=None, product_ids=None, warehouse_ids=None,
              department_ids=None):
        companies = self._companies(company_ids)
        # orders the shifts account for -- left out of the date_finished part
        shift_lines = self.env["cst.production.shift.line"].sudo().search([
            ("is_final_operation", "=", True), ("company_id", "in", companies.ids), ("entry_ids", "!=", False)])
        skip = shift_lines.production_id | shift_lines.correction_production_ids
        return super(CstProductionFactReport, self.with_context(cst_fact_skip_mo_ids=skip.ids)).build(
            date_from, date_to, company_ids=company_ids, product_ids=product_ids,
            warehouse_ids=warehouse_ids, department_ids=department_ids)

    @api.model
    def _fact_mo_domain(self, department_ids):
        domain = super()._fact_mo_domain(department_ids)
        if department_ids:
            domain.append(("workorder_ids.cst_department_id", "in", department_ids))
        return domain

    @api.model
    def _fact_extra_items(self, date_from, date_to, companies, product_ids, warehouse_ids, department_ids):
        items = super()._fact_extra_items(date_from, date_to, companies, product_ids, warehouse_ids, department_ids)
        domain = [("line_id.is_final_operation", "=", True), ("shift_date", ">=", date_from),
                  ("shift_date", "<=", date_to), ("line_id.company_id", "in", companies.ids)]
        if product_ids:
            domain.append(("product_id", "in", product_ids))
        if warehouse_ids:
            domain.append(("production_id.picking_type_id.warehouse_id", "in", warehouse_ids))
        if department_ids:
            domain.append(("department_id", "in", department_ids))
        for entry in self.env["cst.production.shift.entry"].sudo().search(domain):
            product = entry.product_id
            uom_from = entry.line_id.product_uom_id
            out = {key: uom_from._compute_quantity(qty, product.uom_id) for key, qty in (
                ("quantity", entry.qty_good), ("second", entry.qty_second), ("scrap", entry.qty_scrap))}
            items.append((entry.line_id.company_id, entry.production_id.picking_type_id.warehouse_id,
                          product, out, entry.production_id.id))
        return items


class CstProductionFactWizard(models.TransientModel):
    _inherit = "cst.production.fact.wizard"

    department_ids = fields.Many2many("cst.production.department", string="Bo'limlar")

    def _fact_filters(self):
        filters = super()._fact_filters()
        if self.department_ids:
            filters["department_ids"] = self.department_ids.ids
        return filters
