{
    "name": "Kerama Sales Team Company Scope",
    "version": "19.0.1.0.0",
    "summary": "Make the Sales Teams dashboard 'Invoicing' figure respect the active company",
    "description": """
The native Sales Teams kanban dashboard computes a team's invoiced amount with a
raw SQL query that filters only by team_id, ignoring company. With teams shared
across companies (no company_id), every filial shows the all-company total.

This module overrides crm.team._compute_invoiced to also filter by the companies
currently selected in the company switcher (self.env.companies), so each filial
sees only its own sales amount.
""",
    "category": "Sales/Sales",
    "author": "Kerama",
    "license": "LGPL-3",
    "depends": ["sale"],
    "data": [],
    "installable": True,
    "application": False,
}
