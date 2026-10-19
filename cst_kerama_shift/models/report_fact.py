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
    def build(self, date_from, date_to, company_ids=None, product_ids=None):
        Line = self.env["cst.production.shift.line"].sudo()
        companies = self._companies(company_ids)
        # orders the shifts account for -- left out of the date_finished part
        shift_lines = Line.search([("is_final_operation", "=", True), ("company_id", "in", companies.ids),
                                   ("entry_ids", "!=", False)])
        skip = shift_lines.production_id | shift_lines.correction_production_ids
        result = super(CstProductionFactReport, self.with_context(cst_fact_skip_mo_ids=skip.ids)).build(
            date_from, date_to, company_ids=company_ids, product_ids=product_ids)
        domain = [("line_id.is_final_operation", "=", True), ("shift_date", ">=", date_from),
                  ("shift_date", "<=", date_to), ("line_id.company_id", "in", companies.ids)]
        if product_ids:
            domain.append(("product_id", "in", product_ids))
        entries = self.env["cst.production.shift.entry"].sudo().search(domain)
        if not entries:
            return result
        by_company = {block["company"].id: block for block in result}
        for company in companies:
            mine = entries.filtered(lambda e: e.line_id.company_id == company)
            if not mine:
                continue
            block = by_company.get(company.id)
            if not block:
                block = {"company": company, "categories": [], "quantity": 0.0, "second": 0.0, "scrap": 0.0,
                         "orders": 0}
                result.append(block)
            categories = {c["category"].id: c for c in block["categories"]}
            for cat in categories.values():
                cat["products"] = {p["product"].id: p for p in cat["products"]}
            orders = set()
            for entry in mine:
                product = entry.product_id
                uom_from = entry.line_id.product_uom_id
                out = {key: uom_from._compute_quantity(qty, product.uom_id) for key, qty in (
                    ("quantity", entry.qty_good), ("second", entry.qty_second), ("scrap", entry.qty_scrap))}
                cat = categories.setdefault(product.categ_id.id, {
                    "category": product.categ_id, "products": {}, "quantity": 0.0, "second": 0.0, "scrap": 0.0})
                prod = cat["products"].setdefault(product.id, {
                    "product": product, "characteristic": self._characteristic(product),
                    "uom": product.uom_id.name, "quantity": 0.0, "second": 0.0, "scrap": 0.0, "orders": 0})
                if (product.id, entry.production_id.id) not in orders:
                    orders.add((product.id, entry.production_id.id))
                    prod["orders"] += 1
                for key, qty in out.items():
                    prod[key] += qty
                    cat[key] += qty
                    block[key] += qty
            block["orders"] += len({o for _p, o in orders})
            for cat in categories.values():
                cat["products"] = sorted(cat["products"].values(), key=lambda p: p["product"].display_name or "")
            block["categories"] = sorted(categories.values(), key=lambda c: c["category"].complete_name or "")
        return result
