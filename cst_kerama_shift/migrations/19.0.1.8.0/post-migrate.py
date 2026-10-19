"""KPI rows for every shift closed before they existed (crew + whatever the
payroll already holds), so HR can enter KPI on old shifts too. Nothing is
capitalized for them automatically."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    shifts = env["cst.production.shift"].search([("state", "=", "closed"), ("worker_ids", "=", False)])
    shifts.with_context(cst_no_sync=True).action_create_workers()
    shifts.write({"kpi_cost_pending": False})
