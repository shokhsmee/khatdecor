def post_init_hook(env):
    """Create one kassa per cash journal and a starter category per company."""
    env["cst.kassa"]._cst_ensure_kassas()

    Category = env["cst.kassa.category"]
    Account = env["account.account"]
    for company in env["res.company"].search([]):
        domain = Account._check_company_domain(company)
        expense = Account.search(domain + [("account_type", "=", "expense")], order="code", limit=1)
        income = Account.search(domain + [("account_type", "=", "income_other")], order="code", limit=1) \
            or Account.search(domain + [("account_type", "=", "income")], order="code", limit=1)
        if expense and not Category.search_count([("company_id", "=", company.id), ("direction", "=", "out")]):
            Category.create({"name": "Xo'jalik xarajatlari", "direction": "out",
                             "company_id": company.id, "account_id": expense.id})
        if income and not Category.search_count([("company_id", "=", company.id), ("direction", "=", "in")]):
            Category.create({"name": "Boshqa kirim", "direction": "in",
                             "company_id": company.id, "account_id": income.id})
