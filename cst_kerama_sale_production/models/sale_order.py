from odoo import _, api, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    @api.depends("stock_reference_ids.production_ids", "order_line")
    def _compute_mrp_production_ids(self):
        """Also count the orders raised with «Ishlab chiqarishga yuborish» — they
        carry the sales line (``sale_line_id``), not a procurement reference."""
        super()._compute_mrp_production_ids()
        Production = self.env["mrp.production"]
        for sale in self:
            if not sale.id:
                continue
            extra = Production.search([("sale_line_id.order_id", "=", sale.id), ("state", "!=", "cancel")])
            if extra - sale.mrp_production_ids:
                sale.mrp_production_ids |= extra
                sale.mrp_production_count = len(sale.mrp_production_ids)

    def action_cst_send_to_production(self):
        self.ensure_one()
        if self.state != "sale":
            raise UserError(_("Only a confirmed sales order can be sent to production."))
        wizard = self.env["cst.sale.production.wizard"].create({"order_id": self.id})
        wizard._cst_fill_lines()
        return {
            "type": "ir.actions.act_window",
            "name": _("Send to production — %(order)s", order=self.name),
            "res_model": wizard._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    # ------------------------------------------------------------ «Yangi buyurtma» dialog calls
    def _cst_sp_warehouse(self):
        self.ensure_one()
        return self.warehouse_id or self.env["cst.mo.builder"].sudo()._mo_warehouse(self.company_id)

    def cst_sp_options(self):
        self.ensure_one()
        Builder = self.env["cst.mo.builder"].sudo()
        return {"products": Builder.mo_products(self.company_id), "workcenters": Builder.mo_workcenters()}

    def cst_sp_preview(self, product_id, qty):
        self.ensure_one()
        return self.env["cst.mo.builder"].sudo().mo_preview(product_id, qty, warehouse_id=self._cst_sp_warehouse().id)

    def cst_sp_search_products(self, query, limit=20):
        self.ensure_one()
        return self.env["cst.mo.builder"].sudo().mo_search_products(
            query, limit, warehouse_id=self._cst_sp_warehouse().id)

    def cst_sp_create(self, product_id, qty, materials=None, operations=None):
        """Raise the order the dialog described: confirmed, not started, stamped
        with this sales order's line — the department starts it from its window."""
        self.ensure_one()
        self.check_access("read")
        if self.state != "sale":
            raise UserError(_("Only a confirmed sales order can be sent to production."))
        product = self.env["product.product"].browse(int(product_id)).exists()
        if not product:
            raise UserError(_("Product not found."))
        line = self.order_line.filtered(lambda l: l.product_id == product and not l.display_type)[:1]
        values = {"origin": self.name, "sale_line_id": line.id or False}
        if self.project_id:
            values["project_id"] = self.project_id.id
        production = self.env["cst.mo.builder"].sudo()._mo_create(
            product, qty, materials=materials, operations=operations, values=values,
            company=self.company_id, warehouse=self._cst_sp_warehouse())
        production.message_post(body=_("Sent to production from %(order)s.", order=self.name))
        self.message_post(body=_("%(mo)s sent to production: %(product)s × %(qty)s.",
                                 mo=production.name, product=product.display_name, qty=qty))
        return {"id": production.id, "name": production.name, "product_id": product.id}
