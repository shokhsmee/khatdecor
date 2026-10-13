from odoo import _, fields, models


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    cst_shift_id = fields.Many2one(
        "cst.production.shift", string="Smena yozuvi", index="btree_not_null", copy=False,
        help="Bu ish buyurtmasi qaysi smenada bajarilgan. Smenaga bog'langan ish oylikda smena "
             "fondi orqali to'lanadi, alohida ishbay yozilmaydi.")
    cst_department_id = fields.Many2one(related="workcenter_id.cst_department_id", store=True, string="Bo'lim")
    cst_shift = fields.Selection(selection_add=[("3", "3-smena")], ondelete={"3": "set null"})
    cst_shift_line_ids = fields.One2many(
        "cst.production.shift.line", "workorder_id", string="Smena qatorlari")

    def do_finish(self):
        """«Mark as Done» on the Shop Floor for a work order that carries
        2-sort / brak typed by the operator: the shift line books the result
        (final operation: produce, scrap, regrade, backorder; earlier
        operation: write the department's output) and closes the work order.
        The rest go the normal way."""
        if self.env.context.get("cst_posting_output"):
            return super().do_finish()
        Line = self.env["cst.production.shift.line"].sudo()
        handled = self.env["mrp.workorder"]
        for workorder in self:
            lines = Line.search([
                ("workorder_id", "=", workorder.id), ("shift_id.state", "=", "open"),
                ("state", "in", ("todo", "progress", "paused")),
            ]).filtered(lambda l: l.entry_ids.filtered(lambda e: not e.posted))
            if not lines:
                continue
            line = lines.sorted("id")[-1]
            if line.is_final_operation:
                target = workorder.qty_producing if workorder.product_uom_id.compare(workorder.qty_producing, 0.0) > 0 else workorder.qty_remaining
                counted = sum(line.entry_ids.filtered(lambda e: not e.posted).mapped(
                    lambda e: e.qty_good + e.qty_second + e.qty_scrap))
                missing = target - counted
                if workorder.product_uom_id.compare(missing, 0.0) > 0:
                    self.env["cst.production.shift.entry"].sudo().with_context(cst_sync=True).create({
                        "line_id": line.id, "qty_good": missing,
                        "note": _("Shop Floor'da yakunlandi (qoldiq 1-sort)"),
                    })
            for other in lines - line:
                other.entry_ids.filtered(lambda e: not e.posted).write({"line_id": line.id})
            line.with_context(cst_posting_output=True).action_finish()
            handled |= workorder
        rest = self - handled
        if rest:
            return super(MrpWorkorder, rest).do_finish()
        return True

