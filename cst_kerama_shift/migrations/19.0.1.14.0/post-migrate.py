"""KPI by plan: every closed shift gets its sheet.

A shift whose KPI or penalty already reached payroll stays as it was --
confirmed, every row kept as a hand-entered one; the rest become draft sheets
counted from the plan (there are no KPI prices yet, so their KPI stays 0)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Shift = env["cst.production.shift"]
    closed = Shift.search([("state", "=", "closed")])
    paid = closed.filtered(lambda s: s.payroll_line_ids or any(
        w.kpi_amount or w.penalty_amount for w in s.worker_ids))
    paid.write({"kpi_state": "confirmed"})
    paid.worker_ids.with_context(cst_no_sync=True).write({"kpi_manual": True})
    # presence, shares and the plan for every sheet; the paid ones keep their money
    paid._cst_kpi_recompute(refresh_presence=True, keep_amounts=True)
    (closed - paid)._cst_kpi_recompute(refresh_presence=True)

    # renamed in this version: an upgrade keeps old translations, so set them
    register = {"en_US": "Smena registri", "uz_UZ": "Smena registri", "ru_RU": "Реестр смен"}
    env.ref("cst_kerama_shift.menu_shift_workers").update_field_translations("name", register)
    env.ref("cst_kerama_shift.action_shift_workers").update_field_translations("name", register)
    field = env["ir.model.fields"]._get("cst.production.shift.worker", "kpi_suggested")
    help_text = "KPI narxi × bajarilish foizi."
    field.update_field_translations("help", {"uz_UZ": help_text, "ru_RU": "Цена KPI × процент выполнения."})
    mode = env["ir.model.fields.selection"].search([
        ("field_id.model", "=", "cst.shift.kpi.mass.wizard"), ("field_id.name", "=", "mode"),
        ("value", "=", "suggested")])
    mode.update_field_translations("name", {
        "uz_UZ": "Reja bo'yicha (KPI narxi × bajarilish foizi)",
        "ru_RU": "По плану (цена KPI × процент выполнения)"})
