# -*- coding: utf-8 -*-
# Copyright (C) 2026 Zarixsol
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).
{
    'name': 'Internal Payment Transfer',
    'summary': 'Transfer funds between bank and cash journals with paired Send/Receive payments.',
    'description': """
Internal Payment Transfer
=======================

Restore the classic Odoo internal liquidity transfer workflow for Odoo 19.

Supported transfer scenarios
----------------------------
* Bank → Bank
* Bank → Cash
* Cash → Bank
* Cash → Cash and any other bank/cash journal pair in the same company

Key features
------------
* Transfer money between bank and cash journals
* Create a Send payment on the source journal
* Automatically create the matching Receive payment on the destination journal
* Post journal entries on both sides and reconcile the internal transfer account
* Journal dashboard shortcut and dedicated Internal Transfers menu

Availability: Odoo.sh and On Premise. Community and Enterprise (account only).
    """,
    'author': 'Zarixsol',
    'website': 'https://www.zarixsol.com',
    'maintainer': 'Rizwan Chaudhary',
    'support': 'info@zarixsol.com',
    'version': '19.0.1.0.3',
    'license': 'LGPL-3',
    'category': 'Accounting/Accounting',
    'depends': ['account'],
    'data': [
        'views/account_payment_views.xml',
        'views/account_journal_dashboard_views.xml',
        'views/account_menu.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
