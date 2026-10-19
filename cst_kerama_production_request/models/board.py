"""«Ishlab chiqarish zayafkalari» — the planning screen's server side.

Rows come in two shapes:

* a *need*: an open sales-order line whose product the sales warehouse
  cannot cover. Stock is handed out oldest order first: what is already
  reserved on the line's delivery is its own, free stock goes to the earliest
  orders, and whatever production already holds for the line is taken off.
* a *request*: a zayafka already raised, read back from its manufacturing order.

Raw material is checked against the making department's warehouse: there is
enough («Bor»), the department's raw-material warehouses hold the rest
(«Ko'chirish kerak»), or it is short («Yetmaydi»).
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

MATERIAL_LABELS = {
    "ok": "Bor",
    "move": "Ko'chirish kerak",
    "short": "Yetmaydi",
    "none": "Texkarta yo'q",
    "requested": "Ko'chirish so'raldi",
    "na": "—",
}
MATERIAL_RANK = {"ok": 0, "move": 1, "requested": 1, "short": 2, "none": 3, "na": -1}


class CstProductionRequestBoard(models.AbstractModel):
    _name = "cst.production.request.board"
    _description = "Ishlab chiqarish zayafkalari oynasi"

    # ------------------------------------------------------------------ access
    @api.model
    def _check_user(self):
        user = self.env.user
        if not (user.has_group("sales_team.group_sale_salesman") or user.has_group("mrp.group_mrp_user")):
            raise AccessError(_("Ishlab chiqarish zayafkalari faqat sotuv va ishlab chiqarish xodimlari uchun."))

    @api.model
    def _company(self):
        return self.env.company

    # ------------------------------------------------------------------ helpers
    @api.model
    def _departments(self, company=None):
        company = company or self._company()
        return self.env["cst.production.department"].sudo().search([("company_id", "=", company.id)])

    @api.model
    def _bom_department(self, bom):
        operations = bom.operation_ids.sorted(lambda o: (o.sequence, o.id))
        return operations[-1:].workcenter_id.cst_department_id

    @api.model
    def _boms_for(self, products, company=None):
        """{product id: [bom, …]} — variant bills first, then by sequence; the first is what Odoo would pick."""
        company = company or self._company()
        boms = self.env["mrp.bom"].sudo().search([
            ("product_tmpl_id", "in", products.product_tmpl_id.ids), ("type", "=", "normal"),
            ("active", "=", True), ("company_id", "in", (company.id, False))])
        result = {}
        for product in products:
            mine = boms.filtered(lambda b: b.product_tmpl_id == product.product_tmpl_id
                                 and (not b.product_id or b.product_id == product))
            result[product.id] = mine.sorted(lambda b: (0 if b.product_id else 1, b.sequence, b.id))
        return result

    @api.model
    def _bom_data(self, boms):
        rows = []
        for index, bom in enumerate(boms):
            department = self._bom_department(bom)
            label = bom.code or _("Texkarta %s", index + 1)
            if index == 0:
                label = _("%s (asosiy)", label)
            rows.append({
                "id": bom.id, "name": label,
                "department_id": department.id or False, "department": department.name or "",
                "operations": ", ".join(bom.operation_ids.sorted(lambda o: (o.sequence, o.id)).mapped("name")),
            })
        return rows

    @api.model
    def _free_map(self, products, warehouse):
        if not products or not warehouse:
            return {}
        return {p.id: p.free_qty for p in products.with_context(warehouse_id=warehouse.id)}

    # ------------------------------------------------------------------ demand
    @api.model
    def _open_sale_lines(self, company):
        lines = self.env["sale.order.line"].sudo().search([
            ("order_id.state", "=", "sale"), ("company_id", "=", company.id),
            ("display_type", "=", False), ("product_id.is_storable", "=", True),
        ])
        lines = lines.filtered(lambda l: l.product_uom_id.compare(l.product_uom_qty, l.qty_delivered) > 0)
        return lines.sorted(lambda l: (l.order_id.date_order or fields.Datetime.now(), l.order_id.id, l.id))

    @api.model
    def _line_reserved(self, line):
        uom = line.product_id.uom_id
        return sum(
            m.product_uom._compute_quantity(m.quantity, uom)
            for m in line.move_ids
            if m.state not in ("done", "cancel") and m.location_dest_id.usage == "customer")

    @api.model
    def _demand(self, company):
        """Every open sales line with what stock covers it and what is short."""
        lines = self._open_sale_lines(company)
        if not lines:
            return []
        Production = self.env["mrp.production"].sudo()
        productions = Production.search([("sale_line_id", "in", lines.ids), ("state", "not in", ("done", "cancel"))])
        in_production = {}
        for mo in productions:
            uom = mo.sale_line_id.product_id.uom_id
            left = mo.product_uom_id._compute_quantity(max(mo.product_qty - mo.qty_produced, 0.0), uom)
            in_production[mo.sale_line_id.id] = in_production.get(mo.sale_line_id.id, 0.0) + left
        free = {}
        for warehouse in lines.order_id.warehouse_id:
            products = lines.filtered(lambda l: l.order_id.warehouse_id == warehouse).product_id
            for pid, qty in self._free_map(products, warehouse).items():
                free[(warehouse.id, pid)] = max(qty, 0.0)
        result = []
        for line in lines:
            product = line.product_id
            uom = product.uom_id
            to_deliver = line.product_uom_id._compute_quantity(line.product_uom_qty - line.qty_delivered, uom)
            reserved = min(self._line_reserved(line), to_deliver)
            key = (line.order_id.warehouse_id.id, product.id)
            from_free = min(free.get(key, 0.0), max(to_deliver - reserved, 0.0))
            if key in free:
                free[key] -= from_free
            stock = reserved + from_free
            making = in_production.get(line.id, 0.0)
            short = max(to_deliver - stock - making, 0.0)
            result.append({
                "line": line, "to_deliver": to_deliver, "reserved": reserved, "stock": stock,
                "in_production": making, "short": uom.round(short) if hasattr(uom, "round") else short,
            })
        return result

    # ------------------------------------------------------------------ material
    @api.model
    def _material_check(self, items):
        """``items``: [(key, product, bom, qty, department)] → {key: {status, label, materials}}."""
        exploded, components = {}, self.env["product.product"]
        for key, product, bom, qty, department in items:
            if not bom:
                exploded[key] = None
                continue
            factor = product.uom_id._compute_quantity(float(qty or 0) or 1.0, bom.product_uom_id) / (bom.product_qty or 1.0)
            needs = {}
            for bom_line, data in bom.explode(product, factor)[1]:
                component = bom_line.product_id
                if not component.is_storable:
                    continue
                need = bom_line.product_uom_id._compute_quantity(data["qty"], component.uom_id)
                needs[component] = needs.get(component, 0.0) + need
                components |= component
            exploded[key] = needs
        free_cache = {}

        def free_in(warehouse, component):
            if not warehouse:
                return 0.0
            if warehouse.id not in free_cache:
                free_cache[warehouse.id] = self._free_map(components, warehouse)
            return max(free_cache[warehouse.id].get(component.id, 0.0), 0.0)

        result = {}
        for key, product, bom, qty, department in items:
            needs = exploded[key]
            if needs is None:
                result[key] = {"status": "none", "label": MATERIAL_LABELS["none"], "materials": []}
                continue
            warehouse = department._cst_warehouse() if department else self.env["stock.warehouse"]
            supply = department.supply_warehouse_ids if department else self.env["stock.warehouse"]
            worst, rows = "ok", []
            for component, need in needs.items():
                here = free_in(warehouse, component)
                elsewhere = sum(free_in(wh, component) for wh in supply)
                uom = component.uom_id
                if uom.compare(here, need) >= 0:
                    status = "ok"
                elif uom.compare(here + elsewhere, need) >= 0:
                    status = "move"
                else:
                    status = "short"
                if MATERIAL_RANK[status] > MATERIAL_RANK[worst]:
                    worst = status
                rows.append({
                    "id": component.id, "product": component.product_tmpl_id.name or "",
                    "characteristic": component.cst_characteristic or "",
                    "need": need, "free": here, "supply": elsewhere, "uom": uom.name,
                    "status": status, "label": MATERIAL_LABELS[status],
                })
            rows.sort(key=lambda r: -MATERIAL_RANK[r["status"]])
            result[key] = {"status": worst, "label": MATERIAL_LABELS[worst], "materials": rows,
                           "warehouse": warehouse.name or "", "supply": ", ".join(supply.mapped("name"))}
        return result

    @api.model
    def _request_material(self, request):
        mos = request.production_ids.filtered(lambda p: p.state not in ("done", "cancel"))
        if request.state != "sent" or not mos:
            return {"status": "na", "label": MATERIAL_LABELS["na"], "materials": []}
        if all((mo.components_availability_state or "available") == "available" for mo in mos):
            return {"status": "ok", "label": MATERIAL_LABELS["ok"], "materials": []}
        asked = mos.cst_flow_picking_ids.filtered(
            lambda p: p.cst_flow_kind == "supply" and p.state not in ("done", "cancel"))
        if asked:
            return {"status": "requested", "label": MATERIAL_LABELS["requested"], "materials": [],
                    "pickings": ", ".join(asked.mapped("name"))}
        return {"status": "short", "label": MATERIAL_LABELS["short"], "materials": []}

    # ------------------------------------------------------------------ rows
    @api.model
    def _product_info(self, product):
        return {"product_id": product.id, "product": product.product_tmpl_id.name or "",
                "characteristic": product.cst_characteristic or "", "code": product.default_code or "",
                "uom": product.uom_id.name}

    @api.model
    def _need_rows(self, company):
        demand = self._demand(company)
        if not demand:
            return []
        products = self.env["product.product"].browse({d["line"].product_id.id for d in demand})
        boms = self._boms_for(products, company)
        bom_data = {pid: self._bom_data(rows) for pid, rows in boms.items()}
        items = []
        for d in demand:
            line = d["line"]
            bom = boms.get(line.product_id.id)[:1]
            d["bom"] = bom
            d["department"] = self._bom_department(bom) if bom else self.env["cst.production.department"]
            if d["short"] > 0:
                items.append((line.id, line.product_id, bom, d["short"], d["department"]))
        materials = self._material_check(items)
        rows = []
        for d in demand:
            line = d["line"]
            order = line.order_id
            row = self._product_info(line.product_id)
            row.update({
                "key": "need-%s" % line.id, "type": "need", "kind": "order", "kind_label": "Zakaz",
                "sale_line_id": line.id, "order_id": order.id, "order": order.name,
                "partner": order.partner_id.name or "", "date": fields.Date.to_string(order.date_order.date()) if order.date_order else "",
                "boms": bom_data.get(line.product_id.id, []), "bom_id": d["bom"].id or False,
                "department_id": d["department"].id or False, "department": d["department"].name or "",
                "ordered": d["to_deliver"], "reserved": d["reserved"], "stock": d["stock"],
                "in_production": d["in_production"], "short": d["short"], "qty": d["short"],
                "urgent": False, "state": "need", "state_label": "Berilmagan",
                "material": materials.get(line.id) or {"status": "na", "label": MATERIAL_LABELS["na"], "materials": []},
                "can_release": d["short"] <= 0 and d["stock"] > d["reserved"],
            })
            rows.append(row)
        return rows

    @api.model
    def _request_row(self, request):
        state_label = dict(request._fields["state"].selection).get(request.state, request.state)
        mos = request.production_ids.sorted("id")
        live = mos.filtered(lambda p: p.state != "cancel")
        stage_note = ""
        if request.state == "progress" and live and all(p.state == "done" for p in live):
            stage_note = "Yakunlandi, omborga ko'chirilmoqda"
        row = self._product_info(request.product_id)
        row.update({
            "key": "req-%s" % request.id, "type": "request", "kind": request.kind,
            "kind_label": "Zakaz" if request.kind == "order" else "Ombor",
            "request_id": request.id, "request": request.name,
            "sale_line_id": request.sale_line_id.id or False,
            "order_id": request.sale_order_id.id or False, "order": request.sale_order_id.name or "",
            "partner": request.partner_id.name or "",
            "date": fields.Date.to_string(fields.Datetime.context_timestamp(self, request.create_date).date()),
            "boms": self._bom_data(request.bom_id) if request.bom_id else [], "bom_id": request.bom_id.id or False,
            "department_id": request.department_id.id or False, "department": request.department_id.name or "",
            "ordered": request.demand_qty, "stock": request.stock_qty, "short": request.short_qty,
            "qty": request.qty, "produced": request.qty_produced, "urgent": request.urgent,
            "state": request.state, "state_label": state_label, "stage_note": stage_note,
            "mos": [{"id": mo.id, "name": mo.name, "state": mo.state} for mo in mos],
            "material": self._request_material(request),
            "can_cancel": request._cst_can_cancel(),
            "can_release": request.state == "done",
        })
        return row

    @api.model
    def _request_domain(self, company):
        recent = fields.Datetime.now() - timedelta(days=14)
        return [("company_id", "=", company.id), "|", ("state", "in", ("sent", "progress", "done")),
                "&", ("state", "=", "released"), ("released_date", ">=", recent)]

    # ------------------------------------------------------------------ API
    @api.model
    def get_data(self):
        self._check_user()
        company = self._company()
        requests = self.env["cst.production.request"].sudo().search(self._request_domain(company))
        rows = self._need_rows(company) + [self._request_row(r) for r in requests]
        departments = []
        for department in self._departments(company):
            mine = requests.filtered(lambda r: r.department_id == department and r.state in ("sent", "progress", "done"))
            chips = []
            for state, label in (("sent", "Yuborildi"), ("progress", "Ishlab chiqarilmoqda"), ("done", "Tayyor")):
                count = len(mine.filtered(lambda r, s=state: r.state == s))
                if count:
                    chips.append({"state": state, "label": label, "count": count})
            departments.append({"id": department.id, "name": department.name, "code": department.code,
                                "count": len(mine), "chips": chips,
                                "warehouse": department.warehouse_id.name or ""})
        return {"rows": rows, "departments": departments, "company": company.name}

    @api.model
    def check_row(self, product_id, bom_id, qty, department_id=None):
        """Raw material for one row as the planner has shaped it."""
        self._check_user()
        product = self.env["product.product"].sudo().browse(int(product_id)).exists()
        bom = self.env["mrp.bom"].sudo().browse(int(bom_id)).exists() if bom_id else self.env["mrp.bom"]
        if department_id:
            department = self.env["cst.production.department"].sudo().browse(int(department_id)).exists()
        else:
            department = self._bom_department(bom) if bom else self.env["cst.production.department"]
        if not product:
            return {"status": "none", "label": MATERIAL_LABELS["none"], "materials": []}
        return self._material_check([("row", product, bom, float(qty or 0), department)])["row"]

    # ------------------------------------------------------------------ create
    @api.model
    def _route(self, production, department):
        """Make sure the order shows in ``department``'s queue: if the bill has no
        operation there, its last operation moves to one of the department's
        lines (an alternative line of that operation first); a bill with no
        operation at all gets one."""
        workorders = production.workorder_ids.sorted(lambda w: (w.sequence, w.id))
        if workorders.filtered(lambda w: w.workcenter_id.cst_department_id == department):
            return
        lines = department.workcenter_ids.sorted(lambda w: (w.sequence, w.id))
        if not lines:
            raise UserError(_("«%s» bo'limida liniya (stanok) yo'q.", department.name))
        last = workorders[-1:]
        if last:
            options = last.workcenter_id | last.workcenter_id.alternative_workcenter_ids
            last.workcenter_id = (options & lines)[:1] or lines[:1]
        else:
            self.env["mrp.workorder"].sudo().create({
                "production_id": production.id, "name": department.name,
                "workcenter_id": lines[:1].id, "product_uom_id": production.product_uom_id.id,
            })

    @api.model
    def _make_production(self, request, materials=None, operations=None):
        department = request.department_id
        builder = self.env["cst.mo.builder"].sudo().with_context(cst_flow_department_id=department.id)
        values = {"origin": request.sale_order_id.name or request.name, "cst_request_id": request.id,
                  "priority": "1" if request.urgent else "0"}
        if request.bom_id:
            values["bom_id"] = request.bom_id.id
        if request.sale_line_id:
            values["sale_line_id"] = request.sale_line_id.id
            project = request.sale_order_id.project_id if "project_id" in request.sale_order_id._fields else False
            if project:
                values["project_id"] = project.id
        production = builder._mo_create(
            request.product_id, request.qty, materials=materials, operations=operations, values=values,
            company=request.company_id, warehouse=department.warehouse_id or None, confirm=False)
        self._route(production, department)
        production.action_confirm()
        production.action_assign()
        production.message_post(body=_("Ishlab chiqarish zayafkasi %s bo'yicha.", request.name))
        return production

    @api.model
    def _create_one(self, spec, department):
        Request = self.env["cst.production.request"]
        line = self.env["sale.order.line"].sudo().browse(int(spec.get("sale_line_id") or 0)).exists()
        if not line or line.order_id.state != "sale":
            raise UserError(_("Sotuv qatori topilmadi yoki buyurtma tasdiqlanmagan."))
        product = line.product_id
        qty = float(spec.get("qty") or 0)
        if qty <= 0:
            raise UserError(_("%s: zayafka soni noldan katta bo'lishi kerak.", product.display_name))
        boms = self._boms_for(product, line.company_id).get(product.id)
        bom = boms.filtered(lambda b: b.id == int(spec.get("bom_id") or 0))[:1] or boms[:1]
        if not bom:
            raise UserError(_("%s: texkarta (BoM) yo'q.", product.display_name))
        department = department or self._bom_department(bom)
        if not department:
            raise UserError(_("%s: texkartada operatsiya yo'q — «Bo'limga» tanlang.", product.display_name))
        twin = Request.sudo().search([
            ("sale_line_id", "=", line.id), ("qty", "=", qty), ("state", "!=", "cancel"),
            ("create_date", ">=", fields.Datetime.now() - timedelta(seconds=30))], limit=1)
        if twin:
            raise UserError(_("%s hozirgina xuddi shu qator va son bilan yaratildi.", twin.name))
        demand = next((d for d in self._demand(line.company_id) if d["line"] == line), None)
        request = Request.create({
            "kind": "order", "company_id": line.company_id.id, "sale_line_id": line.id,
            "product_id": product.id, "bom_id": bom.id, "department_id": department.id, "qty": qty,
            "urgent": bool(spec.get("urgent")),
            "demand_qty": demand["to_deliver"] if demand else 0.0,
            "stock_qty": demand["stock"] if demand else 0.0,
            "short_qty": demand["short"] if demand else 0.0,
        })
        production = self._make_production(request)
        line.order_id.sudo().message_post(body=_(
            "Ishlab chiqarish zayafkasi %(req)s: %(product)s × %(qty)s → %(dept)s (%(mo)s).",
            req=request.name, product=product.display_name, qty=qty, dept=department.name, mo=production.name))
        return request

    @api.model
    def create_requests(self, rows, department_id=None):
        """«Zayafka yaratish»: one request (and order) per row; a row that fails
        is reported and the others still go through."""
        self._check_user()
        department = self.env["cst.production.department"]
        if department_id:
            department = department.sudo().browse(int(department_id)).exists()
        created, errors = [], []
        for spec in rows or []:
            try:
                with self.env.cr.savepoint():
                    request = self._create_one(spec, department)
                    created.append(request.name)
            except (UserError, ValidationError) as error:
                self.env.invalidate_all()
                errors.append(str(error.args[0] if error.args else error))
        return {"created": created, "errors": errors}

    # ------------------------------------------------------------------ stock request (dialog)
    @api.model
    def mo_options(self):
        self._check_user()
        builder = self.env["cst.mo.builder"].sudo()
        return {"products": builder.mo_products(self._company()), "workcenters": builder.mo_workcenters()}

    @api.model
    def mo_preview(self, product_id, qty):
        self._check_user()
        return self.env["cst.mo.builder"].sudo().mo_preview(product_id, qty)

    @api.model
    def mo_search_products(self, query, limit=20):
        self._check_user()
        return self.env["cst.mo.builder"].sudo().mo_search_products(query, limit)

    @api.model
    def create_stock_request(self, product_id, qty, materials=None, operations=None):
        """«Ombor to'ldirish zayafkasi»: no sales order, the goods go to stock."""
        self._check_user()
        product = self.env["product.product"].sudo().browse(int(product_id)).exists()
        if not product:
            raise UserError(_("Mahsulot topilmadi."))
        qty = float(qty or 0)
        if qty <= 0:
            raise UserError(_("Miqdor noldan katta bo'lishi kerak."))
        company = self._company()
        bom = self._boms_for(product, company).get(product.id)[:1]
        if not bom:
            raise UserError(_("«%s» uchun texkarta (BoM) yo'q.", product.display_name))
        department = self.env["cst.production.department"]
        chosen = [row for row in operations or [] if row.get("selected", True) and row.get("workcenter_id")]
        if chosen:
            department = self.env["mrp.workcenter"].sudo().browse(int(chosen[-1]["workcenter_id"])).cst_department_id
        department = department or self._bom_department(bom)
        if not department:
            raise UserError(_("Texkartada operatsiya yo'q, bo'limni aniqlab bo'lmadi."))
        request = self.env["cst.production.request"].create({
            "kind": "stock", "company_id": company.id, "product_id": product.id, "bom_id": bom.id,
            "department_id": department.id, "qty": qty,
        })
        production = self._make_production(request, materials=materials, operations=operations)
        return {"id": production.id, "name": production.name, "product_id": product.id, "request": request.name}

    # ------------------------------------------------------------------ row actions
    @api.model
    def set_urgent(self, request_id, value):
        self._check_user()
        request = self.env["cst.production.request"].browse(int(request_id)).exists()
        if not request:
            raise UserError(_("Zayafka topilmadi."))
        request.check_access("write")
        request.sudo()._cst_set_urgent(value)
        return True

    @api.model
    def cancel_request(self, request_id):
        self._check_user()
        request = self.env["cst.production.request"].browse(int(request_id)).exists()
        if not request:
            raise UserError(_("Zayafka topilmadi."))
        request.check_access("write")
        request.sudo().action_cst_cancel()
        return True

    @api.model
    def _cst_reserve_line(self, line):
        """Reserve the line's pending delivery from the stock now in the warehouse."""
        line = line.sudo()
        moves = line.move_ids.filtered(
            lambda m: m.state not in ("done", "cancel", "assigned") and m.location_dest_id.usage == "customer")
        before = self._line_reserved(line)
        if moves:
            moves._action_assign()
        return self._line_reserved(line) - before

    @api.model
    def release(self, keys):
        """«Sotuvga chiqarish»: ready requests and covered order lines get their
        delivery reserved, so the warehouse can hand the goods over."""
        self._check_user()
        reserved, done = 0.0, []
        for key in keys or []:
            kind, _sep, rid = str(key).partition("-")
            if kind == "req":
                request = self.env["cst.production.request"].browse(int(rid)).exists()
                if request:
                    request.check_access("write")
                    reserved += request.sudo()._cst_release()
                    done.append(request.name)
            elif kind == "need":
                line = self.env["sale.order.line"].sudo().browse(int(rid)).exists()
                if line:
                    reserved += self._cst_reserve_line(line)
                    done.append("%s · %s" % (line.order_id.name, line.product_id.product_tmpl_id.name))
        return {"done": done, "reserved": reserved}
