"""Data and actions behind the department floor screen («Bo'lim oynasi»).

One department, one screen: today's shifts, who came, the queue of orders
waiting for this department, the orders on the lines right now with their
results, the raw material at hand, and the closing of the shift. Everything
the OWL screen shows comes from :meth:`get_department_data`; every button it
has calls one method here and gets the fresh screen back.
"""
import re
from datetime import datetime, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

LINE_STATE = {"todo": "Kutilmoqda", "progress": "Jarayonda", "paused": "To'xtatilgan",
              "done": "Bajarildi", "carried": "Keyingi smenaga"}
WO_STATE = {"pending": "Oldingi bosqich kutilmoqda", "blocked": "Oldingi bosqich kutilmoqda",
            "waiting": "Xomashyo kutilmoqda", "ready": "Tayyor",
            "progress": "Jarayonda", "done": "Bajarildi", "cancel": "Bekor"}


_CYR = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i",
        "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
        "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "",
        "э": "e", "ю": "yu", "я": "ya", "ў": "o", "қ": "k", "ғ": "g", "ҳ": "h"}


def skeleton(text):
    """Cyrillic and Latin spellings of the same word fold to one key, so a
    storekeeper typing «kashmir» finds «Кашмир»."""
    out = []
    for ch in (text or "").lower():
        out.append(_CYR.get(ch, ch))
    folded = "".join(out)
    folded = folded.replace("kh", "h").replace("x", "h").replace("q", "k")
    folded = re.sub(r"[\'\u2018\u2019`\u02bb\u02bc]", "", folded)
    return re.sub(r"[^a-z0-9]+", "", folded)


class CstProductionFloor(models.AbstractModel):
    _name = "cst.production.floor"
    _description = "Bo'lim oynasi"

    # ------------------------------------------------------------------ helpers
    @api.model
    def _tz(self, department):
        return pytz.timezone(department.tz or "Asia/Tashkent")

    @api.model
    def _local(self, department, value, fmt="%H:%M"):
        if not value:
            return ""
        return pytz.utc.localize(value).astimezone(self._tz(department)).strftime(fmt)

    @api.model
    def _today(self, department):
        return datetime.now(self._tz(department)).date()

    @api.model
    def _can_manage(self, department):
        user = self.env.user
        return user.has_group("cst_kerama_shift.group_shift_admin") or user in department.manager_user_ids

    @api.model
    def _initials(self, name):
        parts = [p for p in (name or "").split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "?"

    @api.model
    def _department(self, department_id):
        department = self.env["cst.production.department"].browse(int(department_id)).exists()
        if not department:
            raise UserError(_("Bo'lim topilmadi."))
        return department

    # ------------------------------------------------------------------ reads
    @api.model
    def get_departments(self):
        """Departments this user may run, for the picker."""
        departments = self.env["cst.production.department"].search([])
        if not self.env.user.has_group("cst_kerama_shift.group_shift_admin"):
            mine = departments.filtered(lambda d: self.env.user in d.manager_user_ids)
            departments = mine or departments
        import json
        rows = []
        for d in departments:
            graph = json.loads(d.kanban_dashboard_graph or "[]")
            rows.append({
                "id": d.id, "name": d.name, "code": d.code, "color": d.color or 0,
                "output_kind": dict(d._fields["output_kind"].selection)[d.output_kind],
                "lines": len(d.workcenter_ids),
                "open_shift": d.open_shift_id.display_name or False,
                "open_shift_label": d.open_shift_label or "",
                "queue": d.queue_count, "late": d.late_count, "today": d.today_count, "tomorrow": d.tomorrow_count,
                "running": d.running_count, "today_good": d.today_good, "today_scrap": d.today_scrap,
                "employees": d.employee_count,
                "bars": graph[0]["values"] if graph else [],
                "bars_max": max([v["value"] for v in graph[0]["values"]] + [1]) if graph else 1,
            })
        return rows

    @api.model
    def get_department_data(self, department_id):
        department = self._department(department_id)
        today = self._today(department)
        Shift = self.env["cst.production.shift"]
        shifts_today = Shift.search([("department_id", "=", department.id), ("date", "=", today),
                                     ("state", "!=", "cancel")])
        open_shift = department.open_shift_id
        if open_shift:
            open_shift.line_ids._sync_external()
        by_template = {s.template_id.id: s for s in shifts_today}
        templates = []
        for template in department._templates():
            shift = by_template.get(template.id)
            templates.append({
                "id": template.id, "name": template.name, "hours": template._label_hours(),
                "sequence": template.sequence, "shift_id": shift.id if shift else False,
                "state": shift.state if shift else "waiting",
                "state_label": {"open": "Faol", "closed": "Yopilgan", "draft": "Qoralama"}.get(
                    shift.state if shift else "", "Kutilmoqda"),
            })
        lines_today = shifts_today.line_ids
        planned = sum(lines_today.mapped("planned_qty"))
        good = sum(lines_today.mapped("qty_good"))
        second = sum(lines_today.mapped("qty_second"))
        scrap = sum(lines_today.mapped("qty_scrap"))
        total = good + second + scrap
        return {
            "department": {
                "id": department.id, "name": department.name, "code": department.code,
                "output_kind": dict(department._fields["output_kind"].selection)[department.output_kind],
                "today": fields.Date.to_string(today), "today_label": today.strftime("%d.%m.%Y"),
                "lines": [{"id": w.id, "name": w.name} for w in department.workcenter_ids],
            },
            "can_manage": self._can_manage(department),
            "templates": templates,
            "shift": self._shift_data(open_shift) if open_shift else False,
            "employees": self._employees_data(department, open_shift),
            "kpis": {
                "planned": planned, "good": good, "second": second, "scrap": scrap,
                "plan_pct": round(good / planned * 100.0, 1) if planned else 0.0,
                "orders": len(lines_today), "remaining": max(planned - good, 0.0),
                "good_pct": round(good / total * 100.0, 1) if total else 0.0,
                "second_pct": round(second / total * 100.0, 1) if total else 0.0,
                "scrap_pct": round(scrap / total * 100.0, 1) if total else 0.0,
            },
            "queue": self._queue(department, open_shift),
            "materials": self._materials(department, open_shift),
            "history": self._history(department, shifts_today),
        }

    def _employees_data(self, department, shift):
        """The left column: department staff, who Face ID saw, who is in the shift."""
        staff = department.employee_ids
        in_shift = shift.employee_ids if shift else self.env["hr.employee"]
        present = shift.attendance_employee_ids if shift else self.env["hr.employee"]
        rows = []
        for employee in (staff | in_shift).sorted("name"):
            rows.append({
                "id": employee.id, "name": employee.name, "initials": self._initials(employee.name),
                "job": employee.job_title or "", "present": employee in present,
                "in_shift": employee in in_shift, "staff": employee in staff,
            })
        return rows

    def _shift_data(self, shift):
        department = shift.department_id
        return {
            "id": shift.id, "name": shift.name, "display_name": shift.display_name,
            "template": shift.template_id.name, "template_id": shift.template_id.id,
            "date": fields.Date.to_string(shift.date), "date_label": shift.date.strftime("%d.%m.%Y"),
            "start": self._local(department, shift.date_start), "end": self._local(department, shift.date_end),
            "manager": shift.manager_id.name, "state": shift.state,
            "employee_ids": shift.employee_ids.ids, "employee_count": len(shift.employee_ids),
            "qty_planned": shift.qty_planned, "qty_good": shift.qty_good, "qty_second": shift.qty_second,
            "qty_scrap": shift.qty_scrap, "plan_pct": round(shift.plan_pct, 1),
            "kpi_total": shift.kpi_total, "penalty_total": shift.penalty_total,
            "lines": [self._line_data(line) for line in shift.line_ids],
        }

    def _line_data(self, line):
        department = line.department_id
        return {
            "id": line.id, "mo": line.production_id.name, "mo_id": line.production_id.id,
            "product": line.product_id.cst_base_name(), "characteristic": line.cst_characteristic or "",
            "workcenter": line.workcenter_id.name, "workcenter_id": line.workcenter_id.id,
            "order_qty": line.order_qty, "planned": line.planned_qty,
            "good": line.qty_good, "second": line.qty_second, "scrap": line.qty_scrap, "total": line.qty_total,
            "remaining": max(line.planned_qty - line.qty_good, 0.0), "pct": round(line.progress_pct, 1),
            "order_left": max(line._order_remaining(), 0.0),
            "state": line.state, "state_label": LINE_STATE.get(line.state, line.state),
            "final": line.is_final_operation, "origin": line.sale_origin or "",
            "employees": ", ".join(line.employee_ids.mapped("name")), "employee_ids": line.employee_ids.ids,
            "started": self._local(department, line.date_start), "ended": self._local(department, line.date_end),
            "backorder": line.backorder_production_id.name or "",
            "can_cancel": line.state in ("todo", "progress", "paused") and self._can_cancel(line.production_id),
            "undo_blocker": self._undo_blocker(line) if line.state == "done" else "",
            "undo_title": (_("O'chirib bo'lmaydi: %s", self._undo_blocker(line)) if self._undo_blocker(line)
                           else _("O'chirish (ombordan qaytarish)")) if line.state == "done" else "",
            "entries": [{
                "id": e.id, "time": self._local(department, e.datetime), "user": e.user_id.name,
                "good": e.qty_good, "second": e.qty_second, "scrap": e.qty_scrap, "note": e.note or "",
                "posted": e.posted,
            } for e in line.entry_ids],
        }

    def _queue(self, department, shift):
        """Orders waiting for this department, not already on a line of the open shift."""
        taken = shift.line_ids.filtered(lambda l: l.state in ("todo", "progress", "paused")).workorder_id if shift else self.env["mrp.workorder"]
        rows = []
        for wo in department._pending_workorders() - taken:
            mo = wo.production_id
            blocked = wo.blocked_by_workorder_ids.filtered(lambda w: w.state not in ("done", "cancel"))
            rows.append({
                "workorder_id": wo.id, "mo_id": mo.id, "mo": mo.name, "operation": wo.name,
                "product": mo.product_id.cst_base_name(), "characteristic": mo.product_id.cst_characteristic or "",
                "qty": mo.product_qty, "remaining": wo.qty_remaining, "uom": mo.product_uom_id.name,
                "origin": mo.origin or "", "project": mo.project_id.name if "project_id" in mo._fields and mo.project_id else "",
                "workcenter_id": wo.workcenter_id.id, "workcenter": wo.workcenter_id.name,
                "state": wo.state, "state_label": WO_STATE.get(wo.state, wo.state),
                "blocked_by": ", ".join(blocked.mapped("name")),
                "availability": mo.components_availability or "",
                "availability_state": mo.components_availability_state or "available",
                # only stock on hand counts as green; an incoming receipt is a promise
                "available": (mo.components_availability_state or "available") == "available",
                "date_start": self._local(department, mo.date_start, "%d.%m"),
                "shift_line": self._carried_hint(wo),
                "can_cancel": self._can_cancel(mo),
            })
        return rows

    def _can_cancel(self, production, line=None):
        """Nothing made, nothing booked: a mistaken order can still go away."""
        if production.state not in ("draft", "confirmed", "progress"):
            return False
        if production.qty_produced or any(production.workorder_ids.mapped("qty_produced")):
            return False
        if (production.move_raw_ids | production.move_finished_ids).filtered(lambda m: m.state == "done"):
            return False
        lines = self.env["cst.production.shift.line"].search([("production_id", "=", production.id)])
        return not lines.entry_ids

    def _undo_blocker(self, line):
        """Why a finished card cannot be taken back (False = it can).

        Undo = an Odoo unbuild: the finished pieces leave the department's
        stock and the materials come back. Only for the plain case -- the
        order finished from this screen with 1-sort only, nothing split off,
        the pieces still at home.
        """
        mo = line.production_id
        if line.state != "done":
            return _("faqat yakunlangan buyurtma")
        if not line.is_final_operation or mo.state != "done":
            return _("buyurtma bu bo'limda to'liq yakunlanmagan")
        if line.backorder_production_id:
            return _("qoldig'i alohida buyurtmaga (%s) o'tgan", line.backorder_production_id.name)
        if mo.unbuild_ids.filtered(lambda u: u.state == "done"):
            return _("allaqachon qaytarilgan")
        entries = line.entry_ids
        if any(e.qty_second or e.qty_scrap or e.qty_material for e in entries):
            return _("2-sort yoki brak yozilgan")
        return False

    @api.model
    def undo_done(self, department_id, line_id):
        """🗑 on a «Bajarilganlar» card: put the stock back as if it was never made."""
        department = self._department(department_id)
        if not self._can_manage(department):
            raise UserError(_("Faqat bo'lim menejeri o'chira oladi."))
        line = self.env["cst.production.shift.line"].browse(int(line_id)).exists()
        if not line:
            raise UserError(_("Buyurtma topilmadi."))
        mo = line.production_id
        blocker = self._undo_blocker(line)
        if blocker:
            raise UserError(_("%(mo)s: o'chirib bo'lmaydi — %(why)s.", mo=mo.name, why=blocker))
        self._before_undo(mo)
        qty = mo.qty_produced
        unbuild = self.env["mrp.unbuild"].create({
            "product_id": mo.product_id.id, "bom_id": mo.bom_id.id, "mo_id": mo.id,
            "product_qty": qty, "product_uom_id": mo.product_uom_id.id,
            "location_id": mo.location_dest_id.id, "location_dest_id": mo.location_src_id.id,
            "company_id": mo.company_id.id,
        })
        unbuild.action_unbuild()
        # the shift no longer counts it: its result and its card go
        line.entry_ids.sudo().with_context(cst_undo=True).unlink()
        line.unlink()
        mo.message_post(body=_("Bo'lim oynasidan o'chirildi (%(dept)s): %(qty)s dona qaytarildi, xomashyo omborga qaytdi (%(ub)s).",
                               dept=department.name, qty=qty, ub=unbuild.name))
        return self.get_department_data(department.id)

    def _before_undo(self, production):
        """Hook: undo what other modules did with the finished pieces."""
        return True

    @api.model
    def cancel_order(self, department_id, line_id=None, workorder_id=None):
        """«Bekor qilish» on the board: the order is cancelled, its reservation
        released and its line taken off the shift."""
        department = self._department(department_id)
        if not self._can_manage(department):
            raise UserError(_("Buyurtmani faqat bo'lim menejeri bekor qila oladi."))
        line = self.env["cst.production.shift.line"].browse(int(line_id)).exists() if line_id else None
        if line:
            production = line.production_id
        else:
            production = self.env["mrp.workorder"].browse(int(workorder_id)).exists().production_id
        if not production:
            raise UserError(_("Buyurtma topilmadi."))
        if not self._can_cancel(production):
            raise UserError(_(
                "%s: natija kiritilgan yoki omborda harakat bo'lgan, bekor qilib bo'lmaydi. "
                "Buyurtmani yakunlang yoki menejerga murojaat qiling.", production.name))
        lines = self.env["cst.production.shift.line"].search([("production_id", "=", production.id)])
        for shift_line in lines:
            shift_line._clock_out()
        lines.unlink()
        production.action_cancel()
        production.message_post(body=_("Bo'lim oynasidan bekor qilindi (%s).", department.name))
        return self.get_department_data(department.id)

    def _carried_hint(self, workorder):
        """If an earlier shift left this order half done, say so."""
        line = self.env["cst.production.shift.line"].search(
            [("workorder_id", "=", workorder.id), ("state", "=", "carried")], order="id desc", limit=1)
        if not line:
            return ""
        return _("%(shift)s: %(good)s dona qilingan", shift=line.shift_id.display_name, good=line.qty_good)

    def _materials(self, department, shift):
        """Raw material the open shift's orders (or the head of the queue) still need."""
        productions = shift.line_ids.filtered(lambda l: l.state != "done").production_id if shift else self.env["mrp.production"]
        if not productions:
            productions = department._pending_workorders()[:5].production_id
        needs = {}
        for move in productions.move_raw_ids.filtered(lambda m: m.state not in ("done", "cancel")):
            product = move.product_id
            need = move.product_uom._compute_quantity(max(move.product_uom_qty - move.quantity, 0.0), product.uom_id)
            entry = needs.setdefault(product.id, {"product": product, "needed": 0.0})
            entry["needed"] += need
        warehouse = self.env["stock.warehouse"].search([("company_id", "=", department.company_id.id)], limit=1)
        rows = []
        for entry in needs.values():
            product = entry["product"]
            free = product.with_context(warehouse_id=warehouse.id).free_qty if warehouse else product.free_qty
            rows.append({
                "id": product.id, "product": product.cst_base_name(), "characteristic": product.cst_characteristic or "",
                "needed": entry["needed"], "free": free, "uom": product.uom_id.name,
                "ok": product.uom_id.compare(free, entry["needed"]) >= 0,
            })
        rows.sort(key=lambda r: (r["ok"], r["product"]))
        return rows

    def _history(self, department, shifts):
        rows = []
        for entry in shifts.entry_ids.sorted(lambda e: (e.datetime, e.id), reverse=True)[:40]:
            rows.append({
                "id": entry.id, "time": self._local(department, entry.datetime), "user": entry.user_id.name,
                "mo": entry.production_id.name, "product": entry.product_id.cst_base_name(),
                "workcenter": entry.workcenter_id.name, "good": entry.qty_good, "second": entry.qty_second,
                "scrap": entry.qty_scrap, "note": entry.note or "", "shift": entry.shift_id.template_id.name,
                "second_product": entry.second_product_id.cst_base_name() if entry.second_product_id else "",
                "material": ("%s: %s %s" % (entry.material_product_id.cst_base_name(),
                                            ("%g" % entry.qty_material), entry.material_product_id.uom_id.name)
                             if entry.qty_material else ""),
            })
        return rows

    @api.model
    def check_materials(self, workorder_id):
        """Components of one order: needed against free stock, before «Ishni boshlash»."""
        wo = self.env["mrp.workorder"].browse(int(workorder_id))
        department = wo.workcenter_id.cst_department_id
        return self._materials_for(wo.production_id, department)

    def _materials_for(self, production, department):
        warehouse = self.env["stock.warehouse"].search([("company_id", "=", production.company_id.id)], limit=1)
        rows = []
        for move in production.move_raw_ids.filtered(lambda m: m.state not in ("done", "cancel")):
            product = move.product_id
            need = move.product_uom._compute_quantity(max(move.product_uom_qty - move.quantity, 0.0), product.uom_id)
            free = product.with_context(warehouse_id=warehouse.id).free_qty if warehouse else product.free_qty
            rows.append({"id": product.id, "product": product.cst_base_name(), "characteristic": product.cst_characteristic or "",
                         "needed": need, "free": free, "uom": product.uom_id.name,
                         "ok": product.uom_id.compare(free, need) >= 0 or need <= 0})
        return rows

    @api.model
    def product_options(self, department_id, all_products=False):
        """Products this department can make: every variant of a product whose
        bill of materials has an operation on one of the department's lines.
        With ``all_products`` every product with a bill of materials is listed
        and the ones this department has no operation for are flagged."""
        department = self._department(department_id)
        workcenters = department.workcenter_ids | department.workcenter_ids.alternative_workcenter_ids
        domain = [("active", "=", True), ("type", "=", "normal"),
                  ("company_id", "in", (department.company_id.id, False))]
        if not all_products:
            domain.append(("operation_ids.workcenter_id", "in", workcenters.ids))
        boms = self.env["mrp.bom"].search(domain)
        # thousands of bills: read every variant in one go, or each bill's
        # variants are fetched (and their names computed) one query at a time
        all_variants = (boms.product_id | boms.product_tmpl_id.product_variant_ids).filtered(
            lambda v: v.active and not v.cst_is_second_grade)
        info = {}
        for variant, label in zip(all_variants, all_variants.mapped("display_name")):
            info[variant.id] = {
                "id": variant.id, "name": variant.cst_base_name(),
                "characteristic": variant.cst_characteristic or "",
                "label": label, "uom": variant.uom_id.name,
                "code": variant.default_code or "",
            }
        operations = boms.operation_ids
        operations.mapped("workcenter_id")
        operations.mapped("name")
        rows = []
        # one row per bill, not per variant: «110093 Обой» has a 70, 75 and 80 гр
        # texkarta and the manager must be able to pick which one is made
        for bom in boms.sorted(lambda b: (b.product_tmpl_id.name or "", b.sequence, b.code or "", b.id)):
            variants = bom.product_id or bom.product_tmpl_id.product_variant_ids
            foreign = not (bom.operation_ids.workcenter_id & workcenters)
            op_names = ", ".join(bom.operation_ids.mapped("name"))
            for variant_id in variants.ids:
                base = info.get(variant_id)
                if not base:
                    continue
                rows.append(dict(
                    base, key="%s-%s" % (variant_id, bom.id), havola=bom.code or "",
                    search=skeleton("%s %s %s %s" % (base["code"], base["label"],
                                                     base["characteristic"], bom.code or "")),
                    bom_id=bom.id, operations=op_names, foreign=foreign,
                ))
        return rows

    @api.model
    def search_products(self, query, limit=20, department_id=None):
        """Storable products for the extra-material picker; Cyrillic or Latin spelling."""
        return self.env["cst.mo.builder"].mo_search_products(query, limit)

    @api.model
    def bom_materials(self, product_id, qty, bom_id=None, department_id=None):
        """Components a new order of ``qty`` would need, against free stock."""
        product = self.env["product.product"].browse(int(product_id))
        bom = self.env["mrp.bom"].browse(int(bom_id)).exists() if bom_id else None
        return self.env["cst.mo.builder"].mo_materials(product, qty, bom=bom)

    @api.model
    def create_order(self, shift_id, product_id, qty, workcenter_id=None, employee_ids=None, start=True, materials=None,
                     bom_id=None):
        """«50 ta shunday mahsulot chiqaramiz»: a new manufacturing order raised
        from the floor, confirmed, and its work order for this department put
        on the chosen line at once."""
        shift = self.env["cst.production.shift"].browse(int(shift_id))
        if shift.state != "open":
            raise UserError(_("Smena ochiq emas."))
        department = shift.department_id
        product = self.env["product.product"].browse(int(product_id))
        qty = float(qty or 0)
        if qty <= 0:
            raise UserError(_("Miqdor noldan katta bo'lishi kerak."))
        company = department.company_id
        bom = self.env["mrp.bom"].browse(int(bom_id)).exists() if bom_id else None
        if bom and not (bom.product_id == product or (not bom.product_id and bom.product_tmpl_id == product.product_tmpl_id)):
            raise UserError(_("Tanlangan texkarta «%s» mahsulotiga tegishli emas.", product.display_name))
        if not bom:
            bom = self.env["mrp.bom"]._bom_find(product, company_id=company.id).get(product)
        if not bom:
            raise UserError(_("«%s» uchun texkarta (BoM) yo'q.", product.display_name))
        origin = _("%(dept)s · %(shift)s", dept=department.code, shift=shift.name)
        twin = self.env["mrp.production"].search([
            ("product_id", "=", product.id), ("product_qty", "=", qty), ("origin", "=", origin),
            ("state", "!=", "cancel"),
            ("create_date", ">=", fields.Datetime.subtract(fields.Datetime.now(), seconds=30))], limit=1)
        if twin:
            raise UserError(_("%s hozirgina xuddi shu mahsulot va miqdor bilan yaratildi. "
                              "Ikkinchi marta bosilgan bo'lsa — kerak emas.", twin.name))
        picking_type = self.env["stock.picking.type"].search(
            [("code", "=", "mrp_operation"), ("company_id", "=", company.id)], limit=1)
        production = self.env["mrp.production"].with_company(company).with_context(from_project_action=True).create({
            "product_id": product.id, "product_qty": qty, "product_uom_id": product.uom_id.id,
            "bom_id": bom.id, "company_id": company.id,
            "picking_type_id": picking_type.id if picking_type else False,
            "origin": _("%(dept)s · %(shift)s", dept=department.code, shift=shift.name),
        })
        if materials is not None:
            self._apply_materials(production, materials)
        production.action_confirm()
        production.action_assign()
        workorders = production.workorder_ids.filtered(
            lambda w: w.workcenter_id.cst_department_id == department
            or w.workcenter_id in department.workcenter_ids.alternative_workcenter_ids)
        if not workorders:
            raise UserError(_(
                "«%s» texkartasida bu bo'lim bajaradigan operatsiya yo'q. Buyurtma yaratildi, "
                "lekin u boshqa bo'limning navbatiga tushdi.", product.display_name))
        workorder = workorders.sorted(lambda w: (w.sequence, w.id))[:1]
        values = {
            "shift_id": shift.id, "production_id": production.id, "workorder_id": workorder.id,
            "workcenter_id": int(workcenter_id) if workcenter_id else workorder.workcenter_id.id,
            "planned_qty": qty,
        }
        if employee_ids:
            values["employee_ids"] = [(6, 0, [int(i) for i in employee_ids])]
        line = self.env["cst.production.shift.line"].create(values)
        if line.workcenter_id and workorder.workcenter_id != line.workcenter_id:
            # not started yet the order still belongs on this line, not on the
            # bill's machine (Преслаш 1) -- or it shows in the old press's queue
            workorder.workcenter_id = line.workcenter_id
        if start:
            line.action_start()
        return self.get_department_data(department.id)

    @api.model
    def _apply_materials(self, production, materials):
        """Shape this order's raw material to what the manager listed."""
        return self.env["cst.mo.builder"]._mo_apply_materials(production, materials)

    # ------------------------------------------------------------------ actions
    @api.model
    def open_shift(self, department_id, template_id, date_str, employee_ids):
        department = self._department(department_id)
        shift = self.env["cst.production.shift"].create({
            "department_id": department.id, "template_id": int(template_id),
            "date": fields.Date.to_date(date_str) if date_str else self._today(department),
            "employee_ids": [(6, 0, [int(i) for i in employee_ids or []])],
        })
        shift.action_open()
        return self.get_department_data(department.id)

    @api.model
    def update_employees(self, shift_id, employee_ids):
        shift = self.env["cst.production.shift"].browse(int(shift_id))
        if shift.state != "open":
            raise UserError(_("Smena ochiq emas."))
        shift.employee_ids = [(6, 0, [int(i) for i in employee_ids])]
        return self.get_department_data(shift.department_id.id)

    @api.model
    def pull_order(self, shift_id, workorder_id, workcenter_id, planned_qty, employee_ids=None, start=True):
        shift = self.env["cst.production.shift"].browse(int(shift_id))
        wo = self.env["mrp.workorder"].browse(int(workorder_id))
        values = {
            "shift_id": shift.id, "production_id": wo.production_id.id, "workorder_id": wo.id,
            "workcenter_id": int(workcenter_id) if workcenter_id else wo.workcenter_id.id,
            "planned_qty": float(planned_qty or 0) or wo.qty_remaining or wo.production_id.product_qty,
        }
        if employee_ids:
            values["employee_ids"] = [(6, 0, [int(i) for i in employee_ids])]
        line = self.env["cst.production.shift.line"].create(values)
        if start:
            line.action_start()
        return self.get_department_data(shift.department_id.id)

    @api.model
    def line_action(self, line_id, action):
        line = self.env["cst.production.shift.line"].browse(int(line_id))
        if action not in ("start", "pause", "finish", "carry"):
            raise UserError(_("Noma'lum amal."))
        getattr(line, "action_%s" % action)()
        return self.get_department_data(line.department_id.id)

    @api.model
    def add_entry(self, line_id, good, second, scrap, note=None, second_product_id=None,
                  material_product_id=None, material_qty=0, finish=False):
        """Book one count; with ``finish`` the order is also done for this
        shift, in the same transaction, so a failed finish leaves no half entry."""
        line = self.env["cst.production.shift.line"].browse(int(line_id))
        self.env["cst.production.shift.entry"].create({
            "line_id": line.id, "qty_good": float(good or 0), "qty_second": float(second or 0),
            "qty_scrap": float(scrap or 0), "note": note or False,
            "second_product_id": int(second_product_id) if second_product_id and float(second or 0) else False,
            "material_product_id": int(material_product_id) if material_product_id and float(material_qty or 0) else False,
            "qty_material": float(material_qty or 0) if material_product_id else 0.0,
        })
        if finish:
            line.action_finish()
        return self.get_department_data(line.department_id.id)

    @api.model
    def entry_options(self, line_id):
        """Choices for the result dialog: which 2-sort product the pieces become
        (the automatic twin or any 2-sort product) and which raw material of the
        order can be booked as brak."""
        line = self.env["cst.production.shift.line"].browse(int(line_id))
        product = line.production_id.product_id
        twin = product.cst_second_grade_id
        seconds = self.env["product.product"].search(
            [("cst_is_second_grade", "=", True), ("id", "!=", twin.id or 0)], order="name")
        materials = line.production_id.move_raw_ids.filtered(lambda m: m.state != "cancel").product_id
        return {
            "twin": (twin.cst_base_name() if twin else _("%s — 2-sort", product.cst_base_name())),
            "seconds": [{"id": p.id, "name": p.cst_base_name(), "characteristic": p.cst_characteristic or ""}
                        for p in seconds],
            "materials": [{"id": p.id, "name": p.cst_base_name(), "characteristic": p.cst_characteristic or "",
                           "uom": p.uom_id.name} for p in materials],
            "final": line.is_final_operation,
        }

    @api.model
    def close_preview(self, shift_id, kpi_total, penalty_total):
        shift = self.env["cst.production.shift"].browse(int(shift_id))
        rows = self.env["cst.production.shift.close"]._employee_lines(shift, float(kpi_total or 0), float(penalty_total or 0))
        for row in rows:
            row["name"] = self.env["hr.employee"].browse(row["employee_id"]).name
        return {"shares": rows,
                "open_lines": len(shift.line_ids.filtered(lambda l: l.state in ("progress", "paused")))}

    @api.model
    def close_shift(self, shift_id, kpi_total, penalty_total, shares, note=None):
        shift = self.env["cst.production.shift"].browse(int(shift_id))
        shift._check_manager()
        currency = shift.currency_id
        pairs = []
        for row in shares:
            employee = self.env["hr.employee"].browse(int(row["employee_id"]))
            pairs.append((employee, float(row.get("kpi_amount") or 0), float(row.get("penalty_amount") or 0)))
        if currency.compare_amounts(sum(p[1] for p in pairs), float(kpi_total or 0)) != 0:
            raise UserError(_("Xodimlar ulushlari yig'indisi umumiy KPI summasiga teng emas."))
        if currency.compare_amounts(sum(p[2] for p in pairs), float(penalty_total or 0)) != 0:
            raise UserError(_("Jarima ulushlari yig'indisi umumiy jarimaga teng emas."))
        shift._do_close(float(kpi_total or 0), float(penalty_total or 0), pairs, note=note)
        return self.get_department_data(shift.department_id.id)
