{
    "name": "Khatdecor AppsBar Toggle",
    "summary": "Collapse / expand the MuK apps sidebar to icons only.",
    "description": """
Adds a toggle button on top of the MuK apps sidebar.  Collapsed, the sidebar
shows only the app icons (names in tooltips); expanded, icons with names.
The choice is saved on the user (sidebar_type small/large), so it survives
reloads and follows the user to other devices.
    """,
    "author": "Khatdecor",
    "category": "Tools/UI",
    "version": "19.0.1.0.0",
    "depends": ["muk_web_appsbar"],
    "assets": {
        "web.assets_backend": [
            "cst_kerama_appsbar/static/src/appsbar/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
