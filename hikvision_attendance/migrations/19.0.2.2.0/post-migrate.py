from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Everyone works the standard 08:00–17:00 today: start them all on
    1-smena, then move the night people to 2-smena from the employee list.
    Attendances already recorded get the employee's shift too."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    shift = env.ref("hikvision_attendance.work_shift_1", raise_if_not_found=False)
    if not shift:
        return
    employees = env["hr.employee"].with_context(active_test=False).search([("hik_shift_id", "=", False)])
    employees.write({"hik_shift_id": shift.id})
    attendances = env["hr.attendance"].search([("hik_shift_id", "=", False)])
    for attendance in attendances:
        attendance.hik_shift_id = attendance.employee_id.hik_shift_id
