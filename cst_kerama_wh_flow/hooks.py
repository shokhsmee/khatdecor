"""Wire the departments to the warehouses of the 2026-09-28 scheme.

Matched by department code and warehouse code; a department or warehouse
that is not found is logged and left alone, and a department that already
has a warehouse is not touched (the hook may run on a database where the
manager has set things by hand).
"""
import logging

_logger = logging.getLogger(__name__)

# department code -> (works in, raw material from, finished goods go to)
SCHEME = {
    "PRINTER": ("ПЦ", ["ХАО"], "ОЦ"),
    "KESISH": ("ОЦ", ["ХАО", "ПЦ"], "ТОО"),
    "PRESLASH1": ("ПЭО", ["ТОО", "ХАО"], "СО"),
    "PRESLASH2": ("ЯП", ["ТОО", "ХАО"], "СО"),
}


def post_init_hook(env):
    Warehouse = env["stock.warehouse"]
    for department in env["cst.production.department"].search([]):
        spec = SCHEME.get((department.code or "").upper())
        if not spec or department.warehouse_id:
            continue
        own, sources, output = spec

        def wh(code):
            found = Warehouse.search([("code", "=", code), ("company_id", "=", department.company_id.id)], limit=1)
            if not found:
                _logger.warning("cst_kerama_wh_flow: warehouse %s not found for %s", code, department.code)
            return found

        values = {"warehouse_id": wh(own).id,
                  "supply_warehouse_ids": [(6, 0, [w.id for w in map(wh, sources) if w])],
                  "output_warehouse_id": wh(output).id}
        department.write(values)
        _logger.info("cst_kerama_wh_flow: %s -> %s", department.code, values)
