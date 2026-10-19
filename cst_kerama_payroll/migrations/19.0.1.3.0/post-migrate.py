"""Payroll moves to its own currency (so'm) while the books stay in dollars.

Everything payroll held so far was written in the company currency.  Lines
and piece rates are converted at the rate of their date; the kassa advance
takes the so'm the cashier actually handed out.  Lines the period generates
itself are dropped — recomputing the period writes them again, in so'm.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    uzs = env.ref("base.UZS", raise_if_not_found=False)
    if not uzs or not uzs.active:
        return
    companies = env["res.company"].search([])
    cr.execute("UPDATE res_company SET cst_payroll_currency_id = %s WHERE cst_payroll_currency_id IS NULL",
               [uzs.id])
    companies.invalidate_recordset(["cst_payroll_currency_id"])

    Line = env["cst.payroll.line"].with_context(cst_payroll_external_ok=True)
    for company in companies.filtered(lambda c: c.currency_id != uzs):
        lines = Line.search([("company_id", "=", company.id)])
        generated = lines.filtered(lambda l: l.state == "draft" and not l.is_manual
                                   and l.component_id.computation != "manual")
        if generated:
            _logger.info("payroll→so'm: %s dropping %s generated draft lines", company.name, len(generated))
            periods = generated.period_id
            cr.execute("DELETE FROM cst_payroll_line WHERE id IN %s", [tuple(generated.ids)])
            periods.filtered(lambda p: p.state == "computed").write({"state": "draft"})
        for line in (lines - generated).exists():
            amount = rate = None
            if line.source_model == "cst.kassa.operation" and line.source_id:
                # the kassa's models load after this module: read the table
                cr.execute("SELECT to_regclass('cst_kassa_operation') IS NOT NULL")
                if cr.fetchone()[0]:
                    cr.execute("SELECT amount FROM cst_kassa_operation WHERE id = %s AND currency_id = %s",
                               [line.source_id, uzs.id])
                    row = cr.fetchone()
                    if row:
                        amount = row[0]
            factor = company.currency_id._get_conversion_rate(company.currency_id, uzs, company, line.date)
            if amount is None:
                amount = uzs.round(line.amount * factor)
            if line.rate:
                rate = uzs.round(line.rate * factor)
            cr.execute("UPDATE cst_payroll_line SET amount = %s, signed_amount = signed_amount * %s / amount, "
                       "rate = COALESCE(%s, rate), currency_id = %s WHERE id = %s",
                       [amount, amount, rate, uzs.id, line.id])
            _logger.info("payroll→so'm: line %s %s → %s", line.id, line.amount, amount)
        cr.execute("UPDATE cst_payroll_line SET currency_id = %s WHERE company_id = %s", [uzs.id, company.id])


    # piece and sales rates were typed in dollars; products and BoMs are mostly
    # shared between the companies, so they are converted once
    main = env.ref("base.main_company")
    if main.currency_id == uzs:
        return
    factor = main.currency_id._get_conversion_rate(main.currency_id, uzs, main, None)
    cr.execute("UPDATE mrp_routing_workcenter SET cst_kpi_rate = round(cst_kpi_rate * %s, 2) "
               "WHERE COALESCE(cst_kpi_rate, 0) <> 0", [factor])
    _logger.info("payroll→so'm: %s operation rates ×%s", cr.rowcount, factor)
    cr.execute("UPDATE product_template SET cst_kpi_rate = round(cst_kpi_rate * %s, 2) "
               "WHERE COALESCE(cst_kpi_rate, 0) <> 0", [factor])
    cr.execute("UPDATE product_product SET cst_kpi_rate_variant = round(cst_kpi_rate_variant * %s, 2) "
               "WHERE COALESCE(cst_kpi_rate_variant, 0) <> 0", [factor])
    cr.execute("""UPDATE product_product p
                     SET cst_kpi_rate_effective = CASE WHEN p.cst_kpi_use_variant THEN p.cst_kpi_rate_variant
                                                       ELSE t.cst_kpi_rate END
                    FROM product_template t
                   WHERE t.id = p.product_tmpl_id
                     AND COALESCE(p.cst_kpi_rate_effective, 0) IS DISTINCT FROM
                         COALESCE(CASE WHEN p.cst_kpi_use_variant THEN p.cst_kpi_rate_variant
                                       ELSE t.cst_kpi_rate END, 0)""")
