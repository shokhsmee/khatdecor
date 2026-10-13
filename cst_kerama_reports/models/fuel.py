from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CstFuelMachine(models.Model):
    """A vehicle or a machine that burns fuel."""

    _name = "cst.fuel.machine"
    _description = "Mashina"
    _order = "name"

    name = fields.Char(string="Mashina", required=True,
                       help="Hisobotda ko'rinadigan nom, masalan «Kara 001».")
    model_name = fields.Char(string="Rusumi")
    plate = fields.Char(string="Davlat raqami")
    driver_id = fields.Many2one("res.partner", string="Haydovchi")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", string="Kompaniya", required=True,
                                 default=lambda self: self.env.company)
    note = fields.Text(string="Izoh")

    odometer = fields.Float(string="Oxirgi km", compute="_compute_odometer")
    worked_hours = fields.Float(string="Jami ishlagan vaqt", compute="_compute_odometer",
                                help="Barcha tasdiqlangan chiqimlarda yozilgan soatlar yig'indisi.")
    log_count = fields.Integer(string="Yozuvlar", compute="_compute_odometer")

    @api.depends("name")
    def _compute_odometer(self):
        Log = self.env["cst.fuel.log"]
        grouped = {
            machine.id: (count, top, hours)
            for machine, count, top, hours in Log._read_group(
                [("machine_id", "in", self.ids), ("state", "=", "done")],
                groupby=["machine_id"],
                aggregates=["__count", "odometer_km:max", "worked_hours:sum"])
        }
        for machine in self:
            count, top, hours = grouped.get(machine.id, (0, 0.0, 0.0))
            machine.log_count = count
            machine.odometer = top or 0.0
            machine.worked_hours = hours or 0.0

    def action_open_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Yoqilg'i harakati: %s", self.name),
            "res_model": "cst.fuel.log",
            "view_mode": "list,form",
            "domain": [("machine_id", "=", self.id)],
            "context": {"default_machine_id": self.id, "default_kind": "out"},
        }


class CstFuelLog(models.Model):
    """Fuel in and fuel out, each one a real stock move.

    Issuing fuel is the product write-off the warehouse already knows, with
    two things added that a write-off has no room for: which machine took it
    and what the odometer read at that moment. The odometer is what turns a
    pile of litres into a consumption figure.

    Confirming a line moves actual stock — in from the vendor location, out to
    the company's inventory-loss location — so the fuel tank in Odoo and the
    fuel tank in the yard hold the same number, and the negative-balance guard
    refuses an issue the store cannot cover.
    """

    _name = "cst.fuel.log"
    _description = "Yoqilg'i harakati"
    _order = "date desc, id desc"
    _inherit = ["mail.thread"]

    name = fields.Char(string="Raqami", copy=False, readonly=True, default="/")
    date = fields.Datetime(string="Sana", required=True,
                           default=fields.Datetime.now, tracking=True)
    kind = fields.Selection(
        [("in", "Kirim"), ("out", "Chiqim")],
        string="Turi", required=True, default="out", tracking=True)
    product_id = fields.Many2one(
        "product.product", string="Yoqilg'i", required=True,
        domain="[('cst_is_fuel', '=', True), ('is_storable', '=', True)]",
        default=lambda self: self._default_product(), tracking=True)
    machine_id = fields.Many2one("cst.fuel.machine", string="Qaysi mashinaga",
                                 tracking=True)
    quantity = fields.Float(string="Miqdori", required=True, tracking=True)
    cst_characteristic = fields.Char(
        related="product_id.cst_characteristic", string="Xarakteristika")
    uom_id = fields.Many2one(related="product_id.uom_id", string="O'lchov")
    odometer_km = fields.Float(
        string="Spidometr (km)",
        help="Yoqilg'i quyilgan paytdagi umumiy km. Davr ichida yurgan "
             "kilometr shu ko'rsatkichlar farqidan hisoblanadi.")
    worked_hours = fields.Float(
        string="Ishlagan vaqt", tracking=True,
        help="Shu yoqilg'i bilan mashina necha soat ishlagani. Spidometri "
             "yo'q texnika (kara, generator, press) uchun sarf shu soatlarga "
             "nisbatan hisoblanadi.")
    partner_id = fields.Many2one("res.partner", string="Ta'minotchi")
    location_id = fields.Many2one(
        "stock.location", string="Ombor joyi", required=True,
        domain="[('usage', '=', 'internal')]",
        default=lambda self: self._default_location(),
        help="Yoqilg'i saqlanadigan joy: kirimda shu joyga tushadi, "
             "chiqimda shu joydan hisobdan chiqadi.")
    stock_move_id = fields.Many2one("stock.move", string="Ombor harakati",
                                    readonly=True, copy=False)
    state = fields.Selection(
        [("draft", "Qoralama"), ("done", "Bajarilgan")],
        string="Holati", default="draft", required=True, readonly=True, tracking=True)
    company_id = fields.Many2one("res.company", string="Kompaniya", required=True,
                                 default=lambda self: self.env.company)
    note = fields.Char(string="Izoh")

    # ------------------------------------------------------------------
    @api.model
    def _default_product(self):
        return self.env["product.product"].search(
            [("cst_is_fuel", "=", True), ("is_storable", "=", True)], limit=1)

    @api.model
    def _default_location(self):
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1)
        return warehouse.lot_stock_id

    @api.constrains("kind", "machine_id")
    def _check_machine(self):
        for log in self:
            if log.kind == "out" and not log.machine_id:
                raise ValidationError(_("Chiqimda mashinani ko'rsatish shart."))

    @api.constrains("quantity")
    def _check_quantity(self):
        for log in self:
            if log.quantity <= 0:
                raise ValidationError(_("Miqdor noldan katta bo'lishi kerak."))

    @api.constrains("worked_hours")
    def _check_worked_hours(self):
        for log in self:
            if log.worked_hours < 0:
                raise ValidationError(_("Ishlagan vaqt manfiy bo'lishi mumkin emas."))

    # ------------------------------------------------------------------
    def action_confirm(self):
        for log in self.filtered(lambda l: l.state == "draft"):
            log.stock_move_id = log._create_move()
            log.name = log.stock_move_id.reference or log.name
            log.state = "done"
        return True

    def _counterpart_location(self):
        """Where the fuel comes from, or where it disappears to.

        Odoo's own choice for both ends: the vendor location for a receipt and
        the company's inventory-loss location for a write-off, the same one
        ``stock.scrap`` picks.
        """
        self.ensure_one()
        if self.kind == "in":
            supplier = self.env.ref("stock.stock_location_suppliers",
                                    raise_if_not_found=False)
            return supplier or self.env["stock.location"].search(
                [("usage", "=", "supplier")], limit=1)
        loss = self.env["stock.location"].search(
            [("company_id", "in", (self.company_id.id, False)),
             ("usage", "=", "inventory")], order="id", limit=1)
        if not loss:
            raise UserError(_(
                "«%s» kompaniyasi uchun hisobdan chiqarish joyi (inventory) "
                "topilmadi.", self.company_id.display_name))
        return loss

    def _create_move(self):
        self.ensure_one()
        counterpart = self._counterpart_location()
        source, dest = (counterpart, self.location_id) if self.kind == "in" \
            else (self.location_id, counterpart)
        move = self.env["stock.move"].create({
            "reference": self._move_label(),
            "origin": self._move_label(),
            "description_picking": self.note or self._move_label(),
            "product_id": self.product_id.id,
            "product_uom_qty": self.quantity,
            "product_uom": self.product_id.uom_id.id,
            "location_id": source.id,
            "location_dest_id": dest.id,
            "date": self.date,
            "company_id": self.company_id.id,
            "partner_id": self.partner_id.id or False,
        })
        move._action_confirm()
        move._action_assign()
        move.quantity = self.quantity
        move.picked = True
        move._action_done()
        return move

    def _move_label(self):
        self.ensure_one()
        if self.kind == "in":
            return _("Yoqilg'i kirimi: %s", self.product_id.display_name)
        return _("Yoqilg'i: %(product)s → %(machine)s",
                 product=self.product_id.display_name,
                 machine=self.machine_id.display_name)

    def unlink(self):
        if any(log.state == "done" for log in self):
            raise UserError(_(
                "Bajarilgan yozuvni o'chirib bo'lmaydi — u ombor harakatini "
                "yaratgan. Teskari yozuv kiriting."))
        return super().unlink()


class CstFuelReport(models.AbstractModel):
    """«Salyarka (yoqilg'i) hisoboti» — the two tables of the paper sheet."""

    _name = "cst.fuel.report"
    _description = "Yoqilg'i hisoboti"

    @api.model
    def build(self, date_from, date_to, product_ids=None, machine_ids=None,
              company_ids=None):
        Log = self.env["cst.fuel.log"]
        companies = self.env.companies
        if company_ids:
            companies = companies.filtered(lambda c: c.id in company_ids) or companies

        domain = [("state", "=", "done"), ("company_id", "in", companies.ids)]
        if product_ids:
            domain.append(("product_id", "in", product_ids))
        if machine_ids:
            domain.append(("machine_id", "in", machine_ids))

        opening = 0.0
        for log in Log.search(domain + [("date", "<", fields.Datetime.to_datetime(date_from))]):
            opening += log.quantity if log.kind == "in" else -log.quantity

        logs = Log.search(domain + [
            ("date", ">=", fields.Datetime.to_datetime(date_from)),
            # whole last day, as in the other sheets
            ("date", "<=", fields.Datetime.to_datetime(date_to).replace(
                hour=23, minute=59, second=59)),
        ], order="date, id")

        movements = []
        balance = opening
        total_in = total_out = 0.0
        for log in logs:
            signed = log.quantity if log.kind == "in" else -log.quantity
            balance += signed
            if log.kind == "in":
                total_in += log.quantity
            else:
                total_out += log.quantity
            movements.append({
                "log": log,
                "date": log.date,
                "target": log.machine_id.display_name if log.kind == "out"
                          else (log.partner_id.display_name or _("Sotib olindi")),
                "inflow": log.quantity if log.kind == "in" else 0.0,
                "outflow": log.quantity if log.kind == "out" else 0.0,
                "balance": balance,
            })

        return {
            "opening": opening,
            "movements": movements,
            "total_in": total_in,
            "total_out": total_out,
            "closing": balance,
            "machines": self._machine_rows(logs),
            "total_hours": sum(log.worked_hours for log in logs
                               if log.kind == "out" and log.machine_id),
            "uom": logs[:1].uom_id or self.env["product.product"].browse(
                product_ids or []).uom_id[:1],
        }

    @api.model
    def _machine_rows(self, logs):
        """Per machine: what it burned, how far it drove, how long it ran.

        The kilometres of the period are the spread of the odometer readings
        the fillings left behind — the first and the last one inside the
        range. The ratio is the one the company's own sheet prints:
        ``km / miqdor * 100``.

        Hours are not a reading but a plain sum: a machine with no odometer
        (kara, generator, press) has its worked time written on each issue,
        so one filling is already enough to get a litres-per-hour figure,
        which the odometer spread can never give.
        """
        consumed = defaultdict(float)
        readings = defaultdict(list)
        worked = defaultdict(float)
        for log in logs.filtered(lambda l: l.kind == "out" and l.machine_id):
            consumed[log.machine_id] += log.quantity
            worked[log.machine_id] += log.worked_hours
            if log.odometer_km:
                readings[log.machine_id].append(log.odometer_km)

        rows = []
        for machine, quantity in consumed.items():
            marks = sorted(readings.get(machine, []))
            distance = (marks[-1] - marks[0]) if len(marks) > 1 else 0.0
            hours = worked.get(machine, 0.0)
            rows.append({
                "machine": machine,
                "quantity": quantity,
                "distance": distance,
                "ratio": (distance / quantity * 100) if quantity else 0.0,
                "hours": hours,
                "per_hour": (quantity / hours) if hours else 0.0,
            })
        return sorted(rows, key=lambda row: row["machine"].display_name)
