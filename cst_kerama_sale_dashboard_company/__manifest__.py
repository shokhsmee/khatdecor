{
    "name": "Kerama Sale Mini Dashboard Company Scope",
    "version": "19.0.1.0.0",
    "summary": "Scope the Sales mini-dashboard amount totals to the active company",
    "description": """
The Cybrosys 'sale_mini_dashboard' module computes the dashboard amount totals
(total_sale_amount / total_draft_amount) with raw SQL that has no company filter,
so every filial sees the sum of all companies' sales orders.

This module overrides sale.order.get_dashboard_values to re-scope those two amounts
to the companies currently selected in the company switcher (self.env.companies).
Depends on sale_mini_dashboard so this override loads last and wins.
""",
    "category": "Sales/Sales",
    "author": "Kerama",
    "license": "LGPL-3",
    "depends": ["sale_mini_dashboard"],
    "data": [],
    "installable": True,
    "application": False,
}
