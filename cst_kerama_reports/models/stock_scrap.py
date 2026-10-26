from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockScrap(models.Model):
    """A fuel write-off names the machine that took it.

    Fuel is normally issued through «Yoqilg'i harakati», but it is also an
    ordinary stocked product the warehouse can write off; without the machine
    that write-off said nothing about where the diesel went. The machine is
    required for fuel, and a done write-off leaves a fuel log behind (pointing
    at the write-off's own stock move, so no second move) — the fuel sheet and
    the machine's consumption then see it like any other issue.
    """

    _inherit = "stock.scrap"

    cst_is_fuel = fields.Boolean(related="product_id.product_tmpl_id.cst_is_fuel", string="Yoqilg'i")
    cst_fuel_machine_id = fields.Many2one(
        "cst.fuel.machine", string="Mashina", check_company=True,
        help="Yoqilg'i qaysi mashina/texnikaga berildi (davlat raqami bilan).")
    cst_fuel_odometer_km = fields.Float(string="Spidometr (km)")
    cst_fuel_worked_hours = fields.Float(string="Ishlagan vaqt")

    def do_scrap(self):
        for scrap in self:
            if scrap.cst_is_fuel and not scrap.cst_fuel_machine_id:
                raise UserError(_("%s yoqilg'i: qaysi mashinaga berilganini (davlat raqami) tanlang.",
                                  scrap.product_id.display_name))
        result = super().do_scrap()
        self._cst_fuel_logs()
        return result

    def _cst_fuel_logs(self):
        Log = self.env["cst.fuel.log"].sudo()
        for scrap in self.filtered(lambda s: s.state == "done" and s.cst_is_fuel and s.cst_fuel_machine_id):
            move = scrap.move_ids.filtered(lambda m: m.state == "done")[:1]
            if not move or Log.search_count([("stock_move_id", "=", move.id)]):
                continue
            Log.create({
                "name": scrap.name,
                "date": scrap.date_done or fields.Datetime.now(),
                "kind": "out",
                "product_id": scrap.product_id.id,
                "machine_id": scrap.cst_fuel_machine_id.id,
                "quantity": scrap.product_uom_id._compute_quantity(scrap.scrap_qty, scrap.product_id.uom_id),
                "odometer_km": scrap.cst_fuel_odometer_km,
                "worked_hours": scrap.cst_fuel_worked_hours,
                "location_id": scrap.location_id.id,
                "company_id": scrap.company_id.id,
                "stock_move_id": move.id,
                "state": "done",
                "note": _("Hisobdan chiqarish %s", scrap.name),
            })
