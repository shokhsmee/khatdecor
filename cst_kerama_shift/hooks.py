"""First-run data repair for this database.

Every bill of materials in the shop pointed all three of its operations at
«Preslash 1», so printing and cutting had no work center of their own. The
shift screens pull work by department, so each operation is put on the first
line of its department and the sister lines become alternatives. Names are
matched, because that is all the data offers; anything not found is logged
and left alone.
"""
import logging

_logger = logging.getLogger(__name__)

# operation name fragment -> (department code, primary work center, sister lines)
ROUTING = {
    "printer": ("BOSMA", "Printer 1", ["Printer 2"]),
    "bosma": ("BOSMA", "Printer 1", ["Printer 2"]),
    "kesish": ("KESISH", "Oboy 1", ["Oboy 2"]),
    "menemal": ("KESISH", "Oboy 1", ["Oboy 2"]),
    "preslash": ("PRESLASH", "Preslash 1", ["Preslash 2", "Preslash avtomat 1", "Preslash avtomat 2"]),
    "press": ("PRESLASH", "Preslash 1", ["Preslash 2", "Preslash avtomat 1", "Preslash avtomat 2"]),
}


def post_init_hook(env):
    Workcenter = env["mrp.workcenter"].with_context(active_test=False)
    Department = env["cst.production.department"]

    def workcenter(name):
        return Workcenter.search([("name", "=ilike", name)], limit=1)

    # 1. every work center joins its department, sister lines become alternatives
    for code, primary_name, sisters in {v[0]: (v[0], v[1], v[2]) for v in ROUTING.values()}.values():
        department = Department.search([("code", "=", code)], limit=1)
        primary = workcenter(primary_name)
        sister_wcs = Workcenter.browse()
        for name in sisters:
            sister_wcs |= workcenter(name)
        group = primary | sister_wcs
        if not group:
            _logger.warning("shift setup: no work center found for %s (%s)", code, primary_name)
            continue
        if department:
            group.write({"cst_department_id": department.id})
        for wc in group:
            wc.alternative_workcenter_ids = [(6, 0, (group - wc).ids)]
        _logger.info("shift setup: %s <- %s", code, ", ".join(group.mapped("name")))

    # 2. operations move to the first line of their department
    moved = 0
    for operation in env["mrp.routing.workcenter"].search([]):
        key = (operation.name or "").strip().lower()
        for fragment, (_code, primary_name, _sisters) in ROUTING.items():
            if fragment in key:
                primary = workcenter(primary_name)
                if primary and operation.workcenter_id != primary:
                    operation.workcenter_id = primary.id
                    moved += 1
                break
    _logger.info("shift setup: %s bill-of-materials operations moved to their own work center", moved)
