# -*- coding: utf-8 -*-

{
    'name': "POS Direct Screen Login",
    'summary': "Allow users to log in directly to the POS screen without accessing the backend.",
    'description': """
        Enhance your point-of-sale workflow with the POS Direct Screen Login module.

        This module allows POS users to bypass the standard Odoo backend and access the
        Point of Sale interface directly after login, reducing startup time and improving
        efficiency for cashiers and sales staff.

        It also provides a dedicated POS logout option, enabling users to safely exit
        the POS screen without forcing the POS register to close, ensuring smoother
        session handling and uninterrupted operations.
        
    """,
    "author": "CodeSphere Tech",
    "website": "https://www.codespheretech.in/",
    "category": "Point of Sale",
    "version": "19.0.1.0.0",
    'sequence': 0,
    "currency": "USD",
    "price": "0.00",
    'depends': ['point_of_sale',],
    'data': [
        'views/res_users_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'cst_direct_login_pos/static/src/overrides/models/pos_store_redirect.js',
            'cst_direct_login_pos/static/src/overrides/screens/login_screen/login_screen.js',
        ],
    },
    'images': [
        'static/description/Banner.png',
    ],

    "license": "LGPL-3",
    "installable": True,
    "application": True,
    "auto_install": False,
}
