"""Server side of the Khatdecor Shop Floor additions.

Everything the patched Shop Floor screen asks the server is here: who the
user is and what they may see (operator mode), whether Face ID saw them
today, the pieces of a new order (products, bill of materials, operations
and lines), and the 2-sort / brak result that lands in the shift record.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


# A user in any of these groups gets the full Shop Floor; everybody else is
# an operator who sees only their own work.
MANAGER_GROUPS = (
    "mrp.group_mrp_manager",
    "cst_kerama_shift.group_shift_manager",
    "cst_kerama_shift.group_shift_admin",
)
# Face ID keeps the attendance open until the person leaves; an attendance
# older than this without a check-out is a forgotten one, not «still here».
PRESENCE_WINDOW_HOURS = 20


class CstShopfloor(models.AbstractModel):
    _name = "cst.shopfloor"
    _description = "Khatdecor Shop Floor"

    # ------------------------------------------------------------------ who
    @api.model
    def _is_operator(self, user=None):
        user = user or self.env.user
        return not any(user.has_group(group) for group in MANAGER_GROUPS)

    @api.model
    def _own_employee(self):
        return self.env.user.employee_id.sudo()

    @api.model
    def _session_employee(self):
        """The Shop Floor session owner, else the user's own employee."""
        Employee = self.env["hr.employee"].sudo()
        owner = Employee.get_session_owner()
        if owner and isinstance(owner, int):
            employee = Employee.browse(owner).exists()
            if employee:
                return employee
        return self._own_employee()

    @api.model
    def _own_workcenters(self, employee):
        if not employee:
            return self.env["mrp.workcenter"]
        return self.env["mrp.workcenter"].sudo().search(
            [("employee_ids", "in", employee.ids)], order="sequence, id")

    @api.model
    def get_config(self):
        employee = self._own_employee()
        operator = self._is_operator()
        workcenters = self._own_workcenters(employee)
        departments = workcenters.cst_department_id
        return {
            "operator_mode": operator,
            "employee": {"id": employee.id, "name": employee.name} if employee else False,
            "workcenters": [{"id": wc.id, "display_name": wc.display_name} for wc in workcenters],
            "departments": [{"id": d.id, "name": d.name, "code": d.code} for d in departments],
            "presence": self.presence(employee.id) if employee else {"employee_id": False, "online": False},
            "wo_domain": [("cst_operator_ids", "in", employee.ids)] if employee else [("id", "=", 0)],
        }

    # ------------------------------------------------------------------ Face ID
    @api.model
    def presence(self, employee_id=None):
        """Did Face ID see this person come in and not yet leave?"""
        Employee = self.env["hr.employee"].sudo()
        employee = Employee.browse(int(employee_id)).exists() if employee_id else self._own_employee()
        if not employee:
            return {"employee_id": False, "online": False, "check_in": False, "name": ""}
        since = fields.Datetime.now() - timedelta(hours=PRESENCE_WINDOW_HOURS)
        attendance = self.env["hr.attendance"].sudo().search([
            ("employee_id", "=", employee.id), ("check_out", "=", False), ("check_in", ">=", since),
        ], order="check_in desc", limit=1)
        return {
            "employee_id": employee.id,
            "name": employee.name,
            "online": bool(attendance),
            "check_in": fields.Datetime.to_string(attendance.check_in) if attendance else False,
            "has_barcode": bool(employee.barcode),
        }

    # ------------------------------------------------------------------ new order
    @api.model
    def new_order_options(self):
        """Every product with a bill of materials, one row per variant, plus
        the lines of the shop for the operation → line choice."""
        return self.env["cst.mo.builder"].mo_options()

    @api.model
    def bom_preview(self, product_id, qty):
        """What a new order of ``qty`` would take: components against free
        stock, and the operations with the lines each may run on."""
        return self.env["cst.mo.builder"].mo_preview(product_id, qty)

    @api.model
    def create_order(self, product_id, qty, materials=None, operations=None):
        """A new manufacturing order raised from the Shop Floor.

        The order itself is built by :mod:`cst.mo.builder`, the same service
        the Project Hub uses, so both screens create orders the same way. What
        is particular to the shop happens afterwards: the operator is assigned
        to the work orders on their own lines (or to all of them when none is
        theirs) and, where that line's department has an open shift, the order
        is put on the shift so the department screen sees it too.
        """
        product = self.env["product.product"].browse(int(product_id)).exists()
        if not product:
            raise UserError(_("Mahsulot topilmadi."))
        employee = self._session_employee()
        Builder = self.env["cst.mo.builder"]
        # The operator may create the order but has no business reading every
        # record Odoo touches on the way (analytic lines, rules): the order is
        # raised as the system, still stamped with the operator as its author.
        production = Builder.sudo()._mo_create(
            product, qty, materials=materials, operations=operations,
            values={"origin": _("Shop Floor · %s", employee.name if employee else self.env.user.name)})
        if employee:
            allowed = production.workorder_ids.filtered(
                lambda w: w.all_employees_allowed or employee in w.allowed_employees)
            if self._is_operator() and not allowed:
                raise UserError(_(
                    "Tanlangan stanoklarda (%s) ishlashga ruxsatingiz yo'q. Boshqa stanok tanlang.",
                    ", ".join(production.workorder_ids.mapped("workcenter_id.name"))))
            own = allowed.filtered(lambda w: employee in w.workcenter_id.employee_ids) or allowed
            own.write({"employee_assigned_ids": [(4, employee.id)]})
            Line = self.env["cst.production.shift.line"].sudo()
            for workorder in own:
                shift = workorder.workcenter_id.cst_department_id.sudo().open_shift_id
                if shift and not Line.search_count([("workorder_id", "=", workorder.id), ("shift_id", "=", shift.id)]):
                    Line.create({
                        "shift_id": shift.id, "production_id": production.id, "workorder_id": workorder.id,
                        "workcenter_id": workorder.workcenter_id.id, "planned_qty": production.product_qty,
                        "employee_ids": [(6, 0, employee.ids)],
                    })
        return {"id": production.id, "name": production.name}

    # ------------------------------------------------------------------ 2-sort / brak
    @api.model
    def _open_line_for(self, workorder, create=True, employee=None):
        """The shift line this work order runs on right now; made on the spot
        when the department has an open shift and the order is not on it yet."""
        Line = self.env["cst.production.shift.line"].sudo()
        line = Line.search([
            ("workorder_id", "=", workorder.id), ("shift_id.state", "=", "open"),
            ("state", "in", ("todo", "progress", "paused")),
        ], order="id desc", limit=1)
        if line or not create:
            return line
        department = workorder.workcenter_id.cst_department_id
        shift = department.sudo().open_shift_id if department else False
        if not shift:
            raise UserError(_(
                "«%(wc)s» stanogining bo'limida ochiq smena yo'q. Natijani menejer smena ochgach kiriting.",
                wc=workorder.workcenter_id.name))
        mo = workorder.production_id
        values = {
            "shift_id": shift.id, "production_id": mo.id, "workorder_id": workorder.id,
            "workcenter_id": workorder.workcenter_id.id,
            "planned_qty": workorder.qty_remaining or mo.product_qty,
        }
        if employee:
            values["employee_ids"] = [(6, 0, employee.ids)]
        return Line.create(values)

    @api.model
    def record_result(self, workorder_id, good=0, second=0, scrap=0, note=None):
        workorder = self.env["mrp.workorder"].browse(int(workorder_id)).exists()
        if not workorder:
            raise UserError(_("Ish buyurtmasi topilmadi."))
        if workorder.state in ("done", "cancel"):
            raise UserError(_("%s allaqachon yopilgan.", workorder.display_name))
        employee = self._session_employee()
        if self._is_operator() and employee and employee not in workorder.cst_operator_ids \
                and employee not in workorder.workcenter_id.employee_ids:
            raise UserError(_("Bu buyurtma sizga biriktirilmagan."))
        line = self._open_line_for(workorder, employee=employee)
        entry = self.env["cst.production.shift.entry"].sudo().create({
            "line_id": line.id,
            "qty_good": float(good or 0), "qty_second": float(second or 0), "qty_scrap": float(scrap or 0),
            "note": note or _("Shop Floor"),
        })
        if employee and employee not in workorder.employee_assigned_ids:
            workorder.sudo().employee_assigned_ids = [(4, employee.id)]
        mo = workorder.production_id
        return {"id": entry.id, "second_qty": mo.cst_second_qty, "scrap_qty": mo.cst_scrap_qty,
                "line_id": line.id, "shift": line.shift_id.display_name}

    @api.model
    def result_action(self, production_id, kind="second"):
        """The list behind the «2-sort +N» / «Brak +N» chip on a card."""
        mo = self.env["mrp.production"].browse(int(production_id)).exists()
        if not mo:
            raise UserError(_("Buyurtma topilmadi."))
        field = "qty_second" if kind == "second" else "qty_scrap"
        domain = [("production_id", "=", mo.id), (field, ">", 0)]
        Entry = self.env["cst.production.shift.entry"].sudo()
        if kind == "second" or Entry.search_count(domain):
            view = self.env.ref("cst_kerama_shift.view_shift_entry_list")
            return {
                "type": "ir.actions.act_window",
                "name": _("%(order)s — %(kind)s", order=mo.name, kind=_("2-sort") if kind == "second" else _("Brak")),
                "res_model": "cst.production.shift.entry",
                "view_mode": "list",
                "views": [[view.id, "list"]],
                "domain": domain,
                "target": "new",
                "context": {"create": False, "edit": False, "delete": False},
            }
        return {
            "type": "ir.actions.act_window",
            "name": _("%s — Brak (scrap)", mo.name),
            "res_model": "stock.scrap",
            "view_mode": "list",
            "domain": [("production_id", "=", mo.id), ("product_id", "=", mo.product_id.id)],
            "target": "new",
            "context": {"create": False},
        }
