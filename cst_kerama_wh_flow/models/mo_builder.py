from odoo import api, models


class CstMoBuilder(models.AbstractModel):
    _inherit = "cst.mo.builder"

    @api.model
    def _cst_bom_warehouse(self, product):
        """The warehouse of the department that runs the bill's last operation."""
        bom = self.env["mrp.bom"]._bom_find(
            product, company_id=(product.company_id or self.env.company).id).get(product)
        operations = bom.operation_ids.sorted(lambda o: (o.sequence, o.id)) if bom else bom
        department = self.env.context.get("cst_flow_department_id")
        if department:
            return self.env["cst.production.department"].browse(int(department)).warehouse_id
        return operations[-1:].workcenter_id.cst_department_id.warehouse_id if operations else self.env["stock.warehouse"]

    @api.model
    def mo_materials(self, product, qty, warehouse=None, bom=None):
        # free stock is what the making department holds, not the sales warehouse
        return super().mo_materials(product, qty, self._cst_bom_warehouse(product) or warehouse, bom=bom)
