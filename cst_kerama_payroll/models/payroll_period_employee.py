from odoo import _, api, fields, models, tools

# Deductions that are money handed to the employee (kassa or card), not a
# withholding: dated inside the period they are an advance, after it a payout.
PAYOUT_CODES = ("AVANS_NAQD", "AVANS_PLASTIK")


class CstPayrollPeriodEmployee(models.Model):
    """One row per employee and payroll period: «Oylik davri → Xodimlar».

    A read-only SQL view over cst.payroll.line, so it can never drift from
    the lines the period posts.  Oklad is «Ойлик суммаси»; every other accrual
    (KPI, ishbay, bonuses) is KPI.  Money given out before the period ends is
    Avans, after it To'langan; other deductions (jarima, taxes…) are Ushlanma.
    """

    _name = "cst.payroll.period.employee"
    _description = "Payroll period — employee summary"
    _auto = False
    _order = "employee_name, id"
    _rec_name = "employee_id"

    period_id = fields.Many2one("cst.payroll.period", string="Oylik davri", readonly=True)
    employee_id = fields.Many2one("hr.employee", string="Xodim", readonly=True)
    employee_name = fields.Char(readonly=True)
    department_id = fields.Many2one("hr.department", string="Bo'lim", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    currency_id = fields.Many2one("res.currency", readonly=True)
    oklad = fields.Monetary(string="Oklad", readonly=True)
    kpi = fields.Monetary(string="KPI", readonly=True)
    accrued = fields.Monetary(string="Jami hisoblandi", readonly=True)
    advance = fields.Monetary(string="Avans", readonly=True)
    withheld = fields.Monetary(string="Ushlanma", readonly=True)
    to_pay = fields.Monetary(string="To'lanadi", readonly=True,
                             help="Jami hisoblandi − avans − ushlanma.")
    paid = fields.Monetary(string="To'langan", readonly=True,
                           help="Davr tugagandan keyin kassa yoki karta orqali berilgan pul.")
    balance = fields.Monetary(string="Qoldiq", readonly=True,
                              help="To'lanadi − to'langan. Manfiy: xodim oylikdan ko'p olgan (qarz).")
    has_official = fields.Boolean(string="Rasmiy", readonly=True)
    has_advance = fields.Boolean(readonly=True)
    pay_state = fields.Selection(
        [("unpaid", "To'lanmagan"), ("partial", "Qisman"), ("paid", "To'langan"), ("over", "Ortiqcha olingan")],
        string="Holati", readonly=True)

    line_ids = fields.Many2many("cst.payroll.line", compute="_compute_line_ids", string="Qatorlar")
    accrual_line_ids = fields.Many2many("cst.payroll.line", compute="_compute_line_ids",
                                        string="Hisoblangan komponentlar")
    money_line_ids = fields.Many2many("cst.payroll.line", compute="_compute_line_ids",
                                      string="Avans va to'lovlar")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        codes = ", ".join(f"'{code}'" for code in PAYOUT_CODES)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS
            WITH s AS (
                SELECT l.period_id, l.employee_id, l.company_id, l.currency_id,
                       min(l.id) AS id,
                       sum(CASE WHEN c.code = 'OYLIK' THEN l.amount ELSE 0 END) AS oklad,
                       sum(CASE WHEN l.kind = 'accrual' AND c.code <> 'OYLIK' THEN l.amount ELSE 0 END) AS kpi,
                       sum(CASE WHEN l.kind = 'accrual' THEN l.amount ELSE 0 END) AS accrued,
                       sum(CASE WHEN l.kind = 'deduction' AND c.code IN ({codes}) AND l.date <= p.date_to
                                THEN l.amount ELSE 0 END) AS advance,
                       sum(CASE WHEN l.kind = 'deduction' AND c.code NOT IN ({codes})
                                THEN l.amount ELSE 0 END) AS withheld,
                       sum(CASE WHEN l.kind = 'deduction' AND c.code IN ({codes}) AND l.date > p.date_to
                                THEN l.amount ELSE 0 END) AS paid,
                       bool_or(l.is_official AND l.kind = 'accrual') AS has_official
                  FROM cst_payroll_line l
                  JOIN cst_payroll_component c ON c.id = l.component_id
                  JOIN cst_payroll_period p ON p.id = l.period_id
                 WHERE l.state != 'cancel'
                 GROUP BY l.period_id, l.employee_id, l.company_id, l.currency_id
            )
            SELECT s.id, s.period_id, s.employee_id, e.name AS employee_name, v.department_id,
                   s.company_id, s.currency_id, s.oklad, s.kpi, s.accrued, s.advance, s.withheld,
                   s.accrued - s.advance - s.withheld AS to_pay,
                   s.paid,
                   s.accrued - s.advance - s.withheld - s.paid AS balance,
                   coalesce(s.has_official, false) AS has_official,
                   s.advance > 0 AS has_advance,
                   CASE WHEN s.accrued - s.advance - s.withheld - s.paid < 0 THEN 'over'
                        WHEN s.accrued - s.advance - s.withheld - s.paid = 0 THEN 'paid'
                        WHEN s.paid > 0 THEN 'partial'
                        ELSE 'unpaid' END AS pay_state
              FROM s
              JOIN hr_employee e ON e.id = s.employee_id
              LEFT JOIN hr_version v ON v.id = e.current_version_id
        """)

    def _compute_line_ids(self):
        Line = self.env["cst.payroll.line"]
        for row in self:
            lines = Line.search([
                ("period_id", "=", row.period_id.id),
                ("employee_id", "=", row.employee_id.id),
                ("state", "!=", "cancel"),
            ], order="date, id")
            row.line_ids = lines
            row.accrual_line_ids = lines.filtered(lambda l: l.kind == "accrual")
            row.money_line_ids = lines.filtered(lambda l: l.kind == "deduction")

    def action_open_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("%(employee)s — %(period)s", employee=self.employee_id.name, period=self.period_id.name),
            "res_model": "cst.payroll.line",
            "view_mode": "list,form",
            "domain": [("period_id", "=", self.period_id.id), ("employee_id", "=", self.employee_id.id)],
            "context": {"default_period_id": self.period_id.id, "default_employee_id": self.employee_id.id,
                        "default_company_id": self.company_id.id},
        }
