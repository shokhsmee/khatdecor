from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["stock.warehouse"].with_context(active_test=False).search([])._cst_sync_view_location_name()
