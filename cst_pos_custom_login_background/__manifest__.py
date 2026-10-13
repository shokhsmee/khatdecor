# -*- coding: utf-8 -*-

{
    'name': 'POS Custom Login Background',
    'summary': 'Set custom background image for POS login screen from settings',
    'description': """
        Enhance the POS interface by configuring a custom background image for the login screen directly from 
        system settings.

        Features:
        - Upload and set a background image for the POS login screen
        - Configuration available under Point of Sale settings
        - Real-time application without code changes
        - Supports multi-company environment

    """,
    "author": "CodeSphere Tech",
    "website": "https://www.codespheretech.in/",
    "category": "Tools",
    "version": "19.0.1.0.0",
    "sequence": 0,
    "currency": "USD",
    "price": "0.00",
    'depends': ['point_of_sale', ],
    'data': [
        'views/res_config_setting_view.xml',
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            'cst_pos_custom_login_background/static/src/xml/pos_login_screen.xml',
        ],
    },
    'images': ['static/description/Banner.png'],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False
}
