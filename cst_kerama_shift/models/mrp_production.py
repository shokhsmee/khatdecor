"""What a shift did to a manufacturing order.

The counted results (1-sort, 2-sort, brak) live on the shift lines; this is
where an order reads them back and where closing an order books whatever the
floor typed but has not booked yet.
"""
from odoo import _, api, fields, models


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    cst_second_qty = fields.Float(
        string="2-sort (kiritilgan)", compute="_compute_cst_grades", digits="Product Unit of Measure")
    cst_scrap_qty = fields.Float(
        string="Brak (kiritilgan)", compute="_compute_cst_grades", digits="Product Unit of Measure")

    def _compute_cst_grades(self):
        """2-sort and brak counted for this order: what the shift lines hold,
        plus scraps of the finished product booked outside a shift line."""
        Line = self.env["cst.production.shift.line"].sudo()
        Scrap = self.env["stock.scrap"].sudo()
        lines = Line.search([("production_id", "in", self.ids)])
        scraps = Scrap.search([("production_id", "in", self.ids), ("state", "=", "done")])
        second_reason = self.env.ref("cst_kerama_shift.scrap_reason_second_grade", raise_if_not_found=False)
        line_scrap_ids = set(lines.scrap_ids.ids)
        for mo in self:
            my_lines = lines.filtered(lambda l: l.production_id == mo)
            second = sum(my_lines.mapped("qty_second"))
            scrap = sum(my_lines.mapped("qty_scrap"))
            for record in scraps.filtered(
                    lambda s: s.production_id == mo and s.id not in line_scrap_ids and s.product_id == mo.product_id):
                if second_reason and second_reason in record.scrap_reason_tag_ids:
                    second += record.scrap_qty
                else:
                    scrap += record.scrap_qty
            mo.cst_second_qty = second
            mo.cst_scrap_qty = scrap

    def _cst_open_lines_with_entries(self):
        """Shift lines of these orders that still hold unbooked results."""
        return self.env["cst.production.shift.line"].sudo().search([
            ("production_id", "in", self.ids), ("shift_id.state", "=", "open"),
            ("state", "in", ("todo", "progress", "paused")),
        ]).filtered(lambda l: l.entry_ids.filtered(lambda e: not e.posted))

    def button_mark_done(self):
        """Closing an order whose operators typed 2-sort / brak on the Shop
        Floor: those results are booked the shift way (produce the counted
        total, scrap the brak, regrade the 2-sort, backorder the rest) instead
        of Odoo quietly producing everything as first grade. Whatever was
        registered above the typed total counts as 1-sort."""
        if self.env.context.get("cst_posting_output"):
            return super().button_mark_done()
        handled = self.env["mrp.production"]
        for mo in self:
            lines = mo._cst_open_lines_with_entries()
            if not lines:
                continue
            final = lines.filtered("is_final_operation")
            if final:
                target = mo.qty_producing if mo.product_uom_id.compare(mo.qty_producing, 0.0) > 0 else mo.product_qty - mo.qty_produced
                counted = sum(final.mapped(lambda l: sum(l.entry_ids.filtered(lambda e: not e.posted).mapped(
                    lambda e: e.qty_good + e.qty_second + e.qty_scrap))))
                missing = target - counted
                if mo.product_uom_id.compare(missing, 0.0) > 0:
                    self.env["cst.production.shift.entry"].sudo().with_context(cst_sync=True).create({
                        "line_id": final[0].id, "qty_good": missing,
                        "note": _("Shop Floor'da yopildi (qoldiq 1-sort)"),
                    })
            for line in lines.sorted(lambda l: (l.is_final_operation, l.id)):
                line.with_context(cst_posting_output=True).action_finish()
            # only a final-operation line closes the order; if the shift was
            # holding an earlier operation, the order still has to be closed
            if mo.state not in ("done", "cancel"):
                continue
            handled |= mo
        rest = self - handled
        if rest:
            return super(MrpProduction, rest).button_mark_done()
        return True
