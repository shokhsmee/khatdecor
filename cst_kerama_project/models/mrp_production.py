from collections import defaultdict

from odoo import _, api, fields, models


class MrpProduction(models.Model):
    """Manufacturing orders raised from a project's material request.

    ``project_id`` itself comes from the standard ``project_mrp`` module; here we
    only keep the link back to the request that triggered the order and expose
    the value of the components it consumes.
    """

    _inherit = "mrp.production"

    cst_mrf_line_id = fields.Many2one(
        "cst.material.request.line", string="Material Request Line",
        readonly=True, copy=False, index="btree_not_null")
    cst_mrf_id = fields.Many2one(
        related="cst_mrf_line_id.request_id", string="Material Request", store=True)
    cst_material_cost = fields.Monetary(
        string="Material Cost", compute="_compute_cst_material_cost",
        currency_field="cst_currency_id",
        help="Value of the components consumed by this order, at cost price.")
    cst_currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", readonly=True)

    @api.depends("move_raw_ids.quantity", "move_raw_ids.state", "move_raw_ids.product_id")
    def _compute_cst_material_cost(self):
        dashboard = self.env["kerama.project.dashboard"]
        groups = self.grouped(lambda p: (p.company_id, p.project_id))
        for (company, project), productions in groups.items():
            # what the project paid for the components, cost price for stock ones
            quantities = defaultdict(float)
            for move in productions.move_raw_ids:
                if move.state == "cancel":
                    continue
                qty = move.quantity if move.state == "done" else move.product_uom_qty
                quantities[move.product_id.id] += move.product_uom._compute_quantity(
                    qty, move.product_id.uom_id)
            unit_costs = dashboard._component_unit_costs(
                productions.move_raw_ids.product_id, company or self.env.company,
                project, quantities)
            for production in productions:
                cost = 0.0
                for move in production.move_raw_ids:
                    if move.state == "cancel":
                        continue
                    qty = move.quantity if move.state == "done" else move.product_uom_qty
                    qty = move.product_uom._compute_quantity(qty, move.product_id.uom_id)
                    cost += qty * unit_costs.get(move.product_id.id, 0.0)
                production.cst_material_cost = cost

    def action_cst_open_mrf(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Material Request"),
            "res_model": "cst.material.request",
            "res_id": self.cst_mrf_id.id,
            "view_mode": "form",
        }
