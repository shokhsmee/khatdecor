{
    "name": "Hikvision Attendance Webhook (DS-K1T320)",
    "version": "19.0.2.2.0",
    "summary": "Hikvision DS-K1T320 webhook → hr.attendance, plus a Telegram bot "
               "that pushes employee check-in/out events with photos to admins.",
    "depends": ["hr_attendance", "hr"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ir.model.access.csv",
        "views/hr_attendance_views.xml",
        "views/hr_employee_views.xml",
        "data/work_shift_data.xml",
        "views/work_shift_views.xml",
        "views/subscriber_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
}
