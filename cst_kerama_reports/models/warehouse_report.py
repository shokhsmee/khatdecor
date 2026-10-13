from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models


class CstWarehouseReport(models.AbstractModel):
    """«Omborlar hisoboti» — the warehouse sheet, photos and all.

    Company ▸ xom ashyo/tayyor mahsulot ▸ ombor ▸ kategoriya ▸ tovar, with the
    opening balance, what came in, what went out and the closing balance, plus
    the product photo and characteristic the paper sheet carries.

    Every figure comes from the move lines themselves — the opening balance is
    the flow before the period rather than a stored quantity — so a row always
    adds up: ``oxirgi qoldiq = boshlangich + kirim - chiqim``. A stored
    quantity read at a date and flows read from a range can disagree after a
    backdated correction, and a paper report that does not add up is worse
    than no report.
    """

    _name = "cst.warehouse.report"
    _description = "Omborlar hisoboti"

    # ------------------------------------------------------------------
    @api.model
    def _internal_locations(self, warehouses):
        return self.env["stock.location"].search([
            ("id", "child_of", warehouses.view_location_id.ids),
            ("usage", "=", "internal"),
        ])

    @api.model
    def _flows(self, locations, product_domain, date_from=None, date_to=None):
        """``{(warehouse, product): [in, out]}`` over one date range.

        A move between two locations of the same warehouse is internal
        shuffling and cancels out — it is counted on neither side.
        """
        domain = [
            ("state", "=", "done"),
            "|", ("location_id", "in", locations.ids),
                 ("location_dest_id", "in", locations.ids),
        ] + product_domain
        if date_from:
            domain.append(("date", ">=", fields.Datetime.to_datetime(date_from)))
        if date_to:
            # the end date is a whole day, like every other sheet in this app --
            # midnight would drop everything that moved on the last day
            domain.append(("date", "<=", fields.Datetime.to_datetime(date_to).replace(
                hour=23, minute=59, second=59)))

        inside = set(locations.ids)
        # which warehouse each internal location belongs to
        warehouse_of = {loc.id: loc.warehouse_id.id for loc in locations}

        flows = defaultdict(lambda: [0.0, 0.0])
        fields_to_read = ["product_id", "location_id", "location_dest_id",
                          "quantity_product_uom"]
        for row in self.env["stock.move.line"].sudo().search_read(domain, fields_to_read):
            source = row["location_id"][0]
            dest = row["location_dest_id"][0]
            qty = row["quantity_product_uom"] or 0.0
            product = row["product_id"][0]
            source_in = source in inside
            dest_in = dest in inside
            if source_in and dest_in and warehouse_of.get(source) == warehouse_of.get(dest):
                continue
            if dest_in:
                flows[(warehouse_of.get(dest), product)][0] += qty
            if source_in:
                flows[(warehouse_of.get(source), product)][1] += qty
        return flows

    # ------------------------------------------------------------------
    @api.model
    def build(self, date_from, date_to, warehouse_ids=None, category_ids=None,
              product_ids=None, hide_zero=True, show_image=True):
        """The whole sheet, nested the way it is printed."""
        Warehouse = self.env["stock.warehouse"]
        warehouses = Warehouse.browse(warehouse_ids) if warehouse_ids \
            else Warehouse.search([("company_id", "in", self.env.companies.ids)])
        warehouses = warehouses.filtered(lambda w: w.company_id in self.env.companies)
        if not warehouses:
            return []

        locations = self._internal_locations(warehouses)
        product_domain = []
        if product_ids:
            product_domain.append(("product_id", "in", product_ids))
        if category_ids:
            categories = self.env["product.category"].search(
                [("id", "child_of", category_ids)])
            product_domain.append(("product_id.categ_id", "in", categories.ids))

        # opening = everything up to the end of the day before the period;
        # _flows treats its end date as a whole day, so hand it the eve
        before = self._flows(locations, product_domain,
                             date_to=date_from - timedelta(days=1))
        during = self._flows(locations, product_domain, date_from=date_from,
                             date_to=date_to)

        product_ids_seen = {key[1] for key in before} | {key[1] for key in during}
        products = self.env["product.product"].browse(sorted(product_ids_seen)).exists()
        products = products.sorted(
            lambda p: (p.categ_id.complete_name or "", p.display_name or ""))

        result = []
        for warehouse in warehouses.sorted(lambda w: (w.company_id.name, w.name)):
            groups = {}
            for product in products:
                opening_in, opening_out = before.get((warehouse.id, product.id), (0.0, 0.0))
                period_in, period_out = during.get((warehouse.id, product.id), (0.0, 0.0))
                opening = opening_in - opening_out
                closing = opening + period_in - period_out
                if hide_zero and not any((opening, period_in, period_out, closing)):
                    continue
                root, leaf = self._category_pair(product.categ_id)
                group = groups.setdefault(root.id, {
                    "category": root, "leaves": {},
                    "opening": 0.0, "in": 0.0, "out": 0.0, "closing": 0.0,
                })
                leaf_group = group["leaves"].setdefault(leaf.id, {
                    "category": leaf, "products": [],
                    "opening": 0.0, "in": 0.0, "out": 0.0, "closing": 0.0,
                })
                leaf_group["products"].append({
                    "product": product,
                    "characteristic": self._characteristic(product),
                    "image": show_image,
                    "opening": opening,
                    "in": period_in,
                    "out": period_out,
                    "closing": closing,
                })
                for bucket in (group, leaf_group):
                    bucket["opening"] += opening
                    bucket["in"] += period_in
                    bucket["out"] += period_out
                    bucket["closing"] += closing
            if not groups:
                continue
            result.append({
                "warehouse": warehouse,
                "company": warehouse.company_id,
                "groups": sorted(
                    ({**group, "leaves": sorted(group["leaves"].values(),
                                                key=lambda l: l["category"].complete_name or "")}
                     for group in groups.values()),
                    key=lambda g: g["category"].complete_name or ""),
                "opening": sum(g["opening"] for g in groups.values()),
                "in": sum(g["in"] for g in groups.values()),
                "out": sum(g["out"] for g in groups.values()),
                "closing": sum(g["closing"] for g in groups.values()),
            })
        return result

    @api.model
    def _category_pair(self, category):
        """The top of the category tree and the category itself.

        The sheet reads «Xom ashyolar» over «Bo'yoq ranglar»: the coarse group
        first, then the shelf it sits on.
        """
        root = category
        while root.parent_id:
            root = root.parent_id
        return root, category

    @api.model
    def category_label(self, category):
        return category.name if category else "Kategoriyasiz"

    @api.model
    def _characteristic(self, product):
        """The variant's attribute values — «Глянцевый, 70 гр, 183 см, 277 см».

        Empty when the product has no variant attributes: the sheet's
        characteristic column is exactly that, never a stand-in like the code.
        """
        if "cst_characteristic" in product._fields and product.cst_characteristic:
            return product.cst_characteristic
        return ", ".join(product.product_template_attribute_value_ids.mapped("name"))

    @api.model
    def product_label(self, product):
        """«[00011749] Кашмир (115076) ЛДСП» — the product without its
        characteristic, because the sheets print the characteristic in its own
        column and would otherwise say it twice."""
        name = product.product_tmpl_id.name or product.display_name or ""
        return "[%s] %s" % (product.default_code, name) if product.default_code else name
