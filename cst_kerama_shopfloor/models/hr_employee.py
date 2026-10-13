"""Operator mode on the Shop Floor: the only operator on the panel is the
user's own employee, so nobody can start work under a colleague's name."""
from odoo import api, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def _cst_operator_scope(self):
        """The user's own employee when the user is a plain operator, else
        ``None`` (managers keep the full panel)."""
        if self.env["cst.shopfloor"]._is_operator():
            return self.env.user.employee_id.sudo()
        return None

    def get_all_employees(self, login=False):
        own = self._cst_operator_scope()
        if own is not None and own and login and not own.pin:
            # no PIN: the operator is the session owner the moment the screen opens
            own.login()
        out = super().get_all_employees(login=login)
        if own is not None:
            out["connected"] = [row for row in out["connected"] if row["id"] == own.id]
            if login:
                out["all"] = [row for row in out.get("all", []) if row["id"] == own.id]
            out["admin"] = own.id if own and out.get("admin") == own.id else False
        return out

    def login(self, pin=False, set_in_session=True):
        own = self._cst_operator_scope()
        if own is not None and (not own or self.id != own.id):
            return False
        return super().login(pin=pin, set_in_session=set_in_session)

    def set_employees_connected(self):
        own = self._cst_operator_scope()
        if own is not None:
            return super(HrEmployee, own).set_employees_connected()
        return super().set_employees_connected()
