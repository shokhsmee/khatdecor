from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare, float_is_zero, float_round, html2plaintext

GROUP_TRANSFER = "cst_kerama_dispatch.group_dispatch_transfer"
SUPERVISOR = "cst_kerama_wh_control.group_wh_supervisor"


class StockPicking(models.Model):
    _inherit = "stock.picking"

    cst_sent_at = fields.Datetime("Jo'natilgan vaqt", copy=False, readonly=True)
    cst_sent_by_id = fields.Many2one("res.users", string="Jo'natdi", copy=False, readonly=True)
    cst_received_at = fields.Datetime("Qabul qilingan vaqt", copy=False, readonly=True)
    cst_received_by_id = fields.Many2one("res.users", string="Qabul qildi", copy=False, readonly=True)
    cst_final_location_id = fields.Many2one(
        "stock.location", string="Yakuniy manzil (kompaniyalararo)", copy=False,
        help="Inter-company transfer: this picking only takes the goods to the transit "
             "location, the receipt in the other company brings them here.")
    cst_ic_receipt_id = fields.Many2one(
        "stock.picking", string="Qabul (boshqa kompaniya)", copy=False, readonly=True)
    cst_ic_origin_id = fields.Many2one(
        "stock.picking", string="Jo'natma (boshqa kompaniya)", copy=False, readonly=True, index=True)


class CstTransferUi(models.AbstractModel):
    """Data provider of the «Ichki o'tkazmalar» screens of the Jo'natish app.

    Every method checks the group and then works sudo, so the app's role needs no
    stock rights of its own. The receiver rule of cst_kerama_wh_control still
    applies: under sudo ``env.user`` is the real user."""

    _name = "cst.transfer.ui"
    _description = "Ichki o'tkazma (ilova)"

    # ------------------------------------------------------------------
    #  helpers
    # ------------------------------------------------------------------
    def _check(self):
        if not self.env.user.has_group(GROUP_TRANSFER):
            raise AccessError(_("Bu amal uchun huquqingiz yo'q."))

    def _cids(self):
        return self.env.companies.ids or self.env.company.ids

    @api.model
    def _fmt(self, qty):
        return float_round(qty or 0.0, precision_digits=3)

    def _picking(self, picking_id):
        p = self.env["stock.picking"].sudo().browse(int(picking_id)).exists()
        if not p or p.picking_type_code != "internal":
            raise UserError(_("Ichki o'tkazma topilmadi."))
        if p.cst_ic_origin_id:
            p = p.cst_ic_origin_id
        me = self.env.user
        receipt = p.cst_ic_receipt_id
        if not (p.company_id.id in self._cids()
                or me in (p.cst_receiver_id | receipt.cst_receiver_id | p.cst_sent_by_id | p.create_uid)
                or (p.cst_final_location_id.company_id.id in self._cids())):
            raise UserError(_("Ichki o'tkazma topilmadi."))
        return p

    def _transit(self):
        return self.env.ref("stock.stock_location_inter_company").sudo()

    def _dest(self, p):
        return p.cst_final_location_id or p.location_dest_id

    def _receiver(self, p):
        return (p.cst_ic_receipt_id.cst_receiver_id or p.cst_receiver_id)

    def _status(self, p):
        if p.state == "cancel":
            return "cancel"
        if p.cst_final_location_id:
            r = p.cst_ic_receipt_id
            if not r:
                return "new"
            if r.state == "done":
                return "done"
            if r.state == "cancel":
                return "cancel"
            return "sent"
        if p.state == "done":
            return "done"
        return "sent" if p.cst_sent_at else "new"

    def _when(self, dt):
        if not dt:
            return ""
        local = fields.Datetime.context_timestamp(self, dt)
        today = fields.Datetime.context_timestamp(self, fields.Datetime.now()).date()
        days = (today - local.date()).days
        if days <= 0:
            return _("bugun %s", local.strftime("%H:%M"))
        if days == 1:
            return _("kecha %s", local.strftime("%H:%M"))
        if days < 7:
            return _("%s kun oldin", days)
        return local.strftime("%d.%m.%Y")

    def _can_receive(self, p):
        me = self.env.user
        return self._status(p) == "sent" and (
            self._receiver(p) == me or me.has_group(SUPERVISOR))

    def _can_edit(self, p):
        return self._status(p) == "new" and p.company_id.id in self._cids()

    def _row(self, p):
        status = self._status(p)
        moves = p.move_ids.filtered(lambda m: m.state != "cancel") or p.move_ids
        names = moves.product_id.mapped("name")
        stamp = {"new": p.create_date, "sent": p.cst_sent_at,
                 "done": p.cst_ic_receipt_id.date_done or p.date_done}.get(status) or p.write_date
        overdue = status == "sent" and p.cst_sent_at and \
            fields.Datetime.now() - p.cst_sent_at > timedelta(hours=24)
        dest = self._dest(p)
        return {
            "id": p.id,
            "name": p.name,
            "src": p.location_id.warehouse_id.name or p.location_id.complete_name,
            "src_full": p.location_id.complete_name,
            "dest": dest.warehouse_id.name or dest.complete_name,
            "dest_full": dest.complete_name,
            "dest_company": dest.company_id.name if p.cst_final_location_id else "",
            "products": ", ".join(names[:3]),
            "count": len(moves.product_id),
            "when": self._when(stamp),
            "overdue": bool(overdue),
            "status": status,
            "ic": bool(p.cst_final_location_id),
            "sender": (p.cst_sent_by_id or p.create_uid).name or "",
            "receiver": self._receiver(p).name or "",
            "can_edit": self._can_edit(p),
            "can_receive": self._can_receive(p),
        }

    # ------------------------------------------------------------------
    #  list
    # ------------------------------------------------------------------
    def _base_domain(self):
        me = self.env.uid
        cids = self._cids()
        return [
            ("picking_type_code", "=", "internal"),
            ("cst_ic_origin_id", "=", False),
            "|", "|", "|",
            ("company_id", "in", cids),
            ("cst_receiver_id", "=", me),
            ("cst_ic_receipt_id.cst_receiver_id", "=", me),
            ("cst_final_location_id.company_id", "in", cids),
        ]

    def _to_me_domain(self):
        me = self.env.uid
        return [
            "|",
            "&", "&", ("cst_final_location_id", "=", False), ("cst_sent_at", "!=", False),
            "&", ("state", "not in", ("done", "cancel")), ("cst_receiver_id", "=", me),
            "&", ("cst_ic_receipt_id.state", "not in", ("done", "cancel")),
            ("cst_ic_receipt_id.cst_receiver_id", "=", me),
        ]

    def _status_domain(self, status):
        """The list's status chip as a domain (see ``_status``)."""
        if status == "cancel":
            return [("state", "=", "cancel")]
        if status == "done":
            return ["|", "&", ("cst_final_location_id", "=", False), ("state", "=", "done"),
                    ("cst_ic_receipt_id.state", "=", "done")]
        if status == "sent":
            return [("state", "!=", "cancel"), "|",
                    "&", "&", ("cst_final_location_id", "=", False), ("state", "!=", "done"), ("cst_sent_at", "!=", False),
                    "&", ("cst_ic_receipt_id", "!=", False), ("cst_ic_receipt_id.state", "not in", ("done", "cancel"))]
        if status == "new":
            return [("state", "not in", ("done", "cancel")), "|",
                    "&", ("cst_final_location_id", "=", False), ("cst_sent_at", "=", False),
                    "&", ("cst_final_location_id", "!=", False), ("cst_ic_receipt_id", "=", False)]
        return []

    @api.model
    def ui_list(self, filter="all", search=None, status=None, kind=None, src_wh=None, dest_wh=None,
                date_from=None, date_to=None):
        self._check()
        Picking = self.env["stock.picking"].sudo()
        domain = list(self._base_domain())
        me = self.env.uid
        domain += self._status_domain(status)
        has_kind = "cst_move_kind" in Picking._fields
        if kind and has_kind:
            domain.append(("cst_move_kind", "=", kind))
        if src_wh:
            domain.append(("location_id.warehouse_id", "=", int(src_wh)))
        if dest_wh:
            domain += ["|", ("location_dest_id.warehouse_id", "=", int(dest_wh)),
                       ("cst_final_location_id.warehouse_id", "=", int(dest_wh))]
        # the day the document was raised, in the user's own day
        tz_now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        offset = tz_now.utcoffset() or timedelta()
        if date_from:
            domain.append(("create_date", ">=", fields.Datetime.to_datetime(date_from) - offset))
        if date_to:
            domain.append(("create_date", "<", fields.Datetime.to_datetime(date_to) + timedelta(days=1) - offset))
        if filter == "mine":
            domain += ["|", ("cst_sent_by_id", "=", me),
                       "&", ("cst_sent_by_id", "=", False), ("create_uid", "=", me)]
        elif filter == "to_me":
            domain += self._to_me_domain()
        if search:
            domain += ["|", ("name", "ilike", search), ("move_ids.product_id.name", "ilike", search)]
        filtered = any([status, kind, src_wh, dest_wh, date_from, date_to])
        pickings = Picking.search(domain, order="id desc", limit=300 if filtered else 80)
        kinds = dict(Picking._fields["cst_move_kind"].selection) if has_kind else {}
        rows = []
        for p in pickings:
            row = self._row(p)
            row["kind"] = p.cst_move_kind if has_kind else False
            row["kind_label"] = kinds.get(row["kind"], "")
            row["date"] = fields.Datetime.context_timestamp(self, p.create_date).strftime("%d.%m.%Y %H:%M")
            rows.append(row)
        warehouses = self.env["stock.warehouse"].sudo().search(
            [("company_id", "in", self._cids())], order="sequence, id")
        return {
            "rows": rows,
            "count": len(rows),
            "limited": len(rows) >= (300 if filtered else 80),
            "to_me": Picking.search_count(self._base_domain() + self._to_me_domain()),
            "warehouses": [{"id": w.id, "name": w.name} for w in warehouses],
            "kinds": [{"code": k, "label": v} for k, v in kinds.items()],
        }

    @api.model
    def ui_count_to_me(self):
        if not self.env.user.has_group(GROUP_TRANSFER):
            return 0
        return self.env["stock.picking"].sudo().search_count(
            self._base_domain() + self._to_me_domain())

    # ------------------------------------------------------------------
    #  editor data
    # ------------------------------------------------------------------
    @api.model
    def ui_options(self):
        self._check()
        Location = self.env["stock.location"].sudo()
        locs = Location.search([
            ("usage", "=", "internal"), ("warehouse_id", "!=", False),
            ("warehouse_id.active", "=", True)], order="complete_name")
        cids = self._cids()
        locations = [{
            "id": l.id,
            "name": l.complete_name,
            "company_id": l.company_id.id,
            "company": l.company_id.name,
            "mine": l.company_id.id in cids,
            "receiver_id": l.warehouse_id.cst_receiver_id.id or False,
        } for l in locs]
        users = self.env["res.users"].sudo().search(
            [("share", "=", False), ("active", "=", True)], order="name")
        return {
            "locations": locations,
            "users": [{"id": u.id, "name": u.name, "company_ids": u.company_ids.ids} for u in users],
            "me": self.env.uid,
            "multi_company": len({l["company_id"] for l in locations}) > 1,
        }

    def _onhand(self, product, location):
        if not location:
            return 0.0
        return product.with_context(location=location.id).qty_available

    @api.model
    def ui_load(self, picking_id):
        self._check()
        p = self._picking(picking_id)
        status = self._status(p)
        receipt = p.cst_ic_receipt_id
        src_moves = {m.product_id.id: m for m in receipt.move_ids} if receipt else {}
        lines = []
        for m in p.move_ids.filtered(lambda m: m.state != "cancel" or status == "cancel"):
            target = src_moves.get(m.product_id.id) or m
            done = target.state == "done"
            lines.append({
                "move_id": target.id,
                "product_id": m.product_id.id,
                "product": m.product_id.display_name,
            "char": m.product_id.cst_characteristic or "",
                "barcode": m.product_id.barcode or "",
                "uom": m.product_uom.name,
                "qty": self._fmt(m.product_uom_qty),
                "received": self._fmt(target.quantity if done else m.product_uom_qty),
                "onhand": self._fmt(self._onhand(m.product_id, p.location_id)),
            })
        data = self._row(p)
        data.update({
            "src_id": p.location_id.id,
            "dest_id": self._dest(p).id,
            "receiver_id": self._receiver(p).id or False,
            "note": html2plaintext(p.note or "").strip(),
            "lines": lines,
            "sent_at": self._when(p.cst_sent_at),
            "received_by": (receipt.cst_received_by_id or p.cst_received_by_id).name or "",
            "received_at": self._when(receipt.cst_received_at or p.cst_received_at),
            "receipt_name": receipt.name or "",
            "can_cancel": status == "new" and p.company_id.id in self._cids(),
        })
        return data

    @api.model
    def ui_search_products(self, location_id, term):
        self._check()
        term = (term or "").strip()
        if len(term) < 2:
            return []
        location = self.env["stock.location"].sudo().browse(int(location_id or 0)).exists()
        Product = self.env["product.product"].sudo()
        domain = [("type", "=", "consu")]
        if location:
            domain += ["|", ("company_id", "=", False), ("company_id", "=", location.company_id.id)]
        found = Product.search(domain + ["|", ("barcode", "=", term), ("default_code", "=", term)], limit=1)
        if not found:
            ids = [r[0] for r in Product.name_search(term, domain, limit=30)]
            found = Product.browse(ids)
        return [{
            "id": pr.id,
            "name": pr.display_name,
            "char": pr.cst_characteristic or "",
            "barcode": pr.barcode or "",
            "uom": pr.uom_id.name,
            "onhand": self._fmt(self._onhand(pr, location)),
        } for pr in found]

    @api.model
    def ui_product_by_barcode(self, location_id, barcode):
        self._check()
        location = self.env["stock.location"].sudo().browse(int(location_id or 0)).exists()
        Product = self.env["product.product"].sudo()
        pr = Product.search([("barcode", "=", barcode)], limit=1) or \
            Product.search([("default_code", "=", barcode)], limit=1)
        if not pr:
            return False
        return {"id": pr.id, "name": pr.display_name, "char": pr.cst_characteristic or "", "barcode": pr.barcode or "",
                "uom": pr.uom_id.name, "onhand": self._fmt(self._onhand(pr, location))}

    @api.model
    def ui_onhand(self, location_id, product_ids):
        self._check()
        location = self.env["stock.location"].sudo().browse(int(location_id or 0)).exists()
        products = self.env["product.product"].sudo().browse([int(i) for i in product_ids or []])
        return {pr.id: self._fmt(self._onhand(pr, location)) for pr in products}

    @api.model
    def ui_recent(self, src_id=None, dest_id=None):
        """Products I moved lately, and the lines of my last transfer to repeat."""
        self._check()
        Picking = self.env["stock.picking"].sudo()
        mine = [("picking_type_code", "=", "internal"), ("create_uid", "=", self.env.uid),
                ("cst_ic_origin_id", "=", False), ("state", "!=", "cancel")]
        last = Picking.search(mine, order="id desc", limit=15)
        src = self.env["stock.location"].sudo().browse(int(src_id or 0)).exists()
        seen, chips = set(), []
        for p in last:
            for m in p.move_ids:
                if m.product_id.id not in seen and len(chips) < 8:
                    seen.add(m.product_id.id)
                    chips.append({
                        "id": m.product_id.id,
                        "name": m.product_id.name,
                        "product": m.product_id.display_name,
                        "char": m.product_id.cst_characteristic or "",
                        "barcode": m.product_id.barcode or "",
                        "uom": m.product_id.uom_id.name,
                        "onhand": self._fmt(self._onhand(m.product_id, src)),
                    })
        repeat = False
        if src_id and dest_id:
            repeat = Picking.search(mine + [
                ("location_id", "=", int(src_id)),
                "|", ("location_dest_id", "=", int(dest_id)),
                ("cst_final_location_id", "=", int(dest_id))], order="id desc", limit=1)
        repeat = repeat or last[:1]
        return {"chips": chips, "repeat_id": repeat.id if repeat else False,
                "repeat_name": repeat.name if repeat else ""}

    @api.model
    def ui_repeat_lines(self, picking_id, location_id=None):
        self._check()
        p = self._picking(picking_id)
        location = self.env["stock.location"].sudo().browse(int(location_id or 0)).exists() \
            or p.location_id
        return [{
            "product_id": m.product_id.id,
            "product": m.product_id.display_name,
            "char": m.product_id.cst_characteristic or "",
            "barcode": m.product_id.barcode or "",
            "uom": m.product_uom.name,
            "qty": self._fmt(m.product_uom_qty),
            "onhand": self._fmt(self._onhand(m.product_id, location)),
        } for m in p.move_ids.filtered(lambda m: m.state != "cancel")]

    # ------------------------------------------------------------------
    #  save / send / receive / cancel
    # ------------------------------------------------------------------
    @api.model
    def ui_save(self, picking_id, vals):
        """Create or update a «new» transfer (autosave of the editor)."""
        self._check()
        Location = self.env["stock.location"].sudo()
        src = Location.browse(int(vals.get("src_id") or 0)).exists()
        dest = Location.browse(int(vals.get("dest_id") or 0)).exists()
        if not src:
            raise UserError(_("«Qayerdan» omborini tanlang."))
        if src.company_id.id not in self._cids():
            raise UserError(_("Faqat o'z kompaniyangiz omboridan jo'nata olasiz."))
        if dest and dest == src:
            raise UserError(_("«Qayerdan» va «Qayerga» bir xil bo'lmasin."))
        ic = bool(dest) and dest.company_id != src.company_id
        ptype = src.warehouse_id.int_type_id or self.env["stock.picking.type"].sudo().search([
            ("code", "=", "internal"), ("company_id", "=", src.company_id.id)], limit=1)
        if not ptype:
            raise UserError(_("%s uchun ichki ko'chirish turi topilmadi.", src.complete_name))
        receiver = self.env["res.users"].sudo().browse(int(vals.get("receiver_id") or 0)).exists()
        header = {
            "picking_type_id": ptype.id,
            "location_id": src.id,
            "location_dest_id": (self._transit().id if ic else dest.id) if dest
            else ptype.default_location_dest_id.id or src.id,
            "cst_final_location_id": dest.id if ic else False,
            "cst_receiver_id": receiver.id or False,
            "company_id": src.company_id.id,
            "note": vals.get("note") or False,
        }
        Picking = self.env["stock.picking"].sudo().with_company(src.company_id)
        if picking_id:
            p = self._picking(picking_id)
            if not self._can_edit(p):
                raise UserError(_("Bu ichki o'tkazma endi o'zgartirilmaydi."))
            if p.state not in ("draft", "cancel"):
                p.do_unreserve()
            p.write(header)
        else:
            p = Picking.create(header)
        # lines: one move per product
        wanted = {}
        for line in vals.get("lines") or []:
            pid = int(line.get("product_id") or 0)
            if pid:
                wanted[pid] = wanted.get(pid, 0.0) + max(float(line.get("qty") or 0.0), 0.0)
        moves = p.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        for move in moves:
            qty = wanted.pop(move.product_id.id, None)
            if qty is None or float_is_zero(qty, precision_digits=4):
                if move.state == "draft":
                    move.unlink()
                else:
                    move._action_cancel()
            else:
                move.write({
                    "product_uom_qty": move.product_id.uom_id._compute_quantity(qty, move.product_uom),
                    "location_id": p.location_id.id,
                    "location_dest_id": p.location_dest_id.id,
                })
        Product = self.env["product.product"].sudo()
        for pid, qty in wanted.items():
            if float_is_zero(qty, precision_digits=4):
                continue
            product = Product.browse(pid)
            self.env["stock.move"].sudo().create({
                "picking_id": p.id,
                "product_id": product.id,
                "product_uom": product.uom_id.id,
                "product_uom_qty": qty,
                "location_id": p.location_id.id,
                "location_dest_id": p.location_dest_id.id,
                "company_id": p.company_id.id,
            })
        return p.id

    @api.model
    def ui_send(self, picking_id):
        self._check()
        p = self._picking(picking_id)
        if not self._can_edit(p):
            raise UserError(_("Bu ichki o'tkazma allaqachon jo'natilgan."))
        moves = p.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        if not moves:
            raise UserError(_("Kamida bitta mahsulot qo'shing."))
        dest = self._dest(p)
        if not dest or dest == p.location_id:
            raise UserError(_("«Qayerga» omborini tanlang."))
        if not p.cst_receiver_id:
            raise UserError(_("Qabul qiluvchini tanlang."))
        if p.cst_final_location_id and p.cst_receiver_id and \
                p.cst_final_location_id.company_id not in p.cst_receiver_id.company_ids:
            raise UserError(_("%(u)s «%(c)s» kompaniyasiga kira olmaydi — boshqa qabul qiluvchini tanlang.",
                              u=p.cst_receiver_id.name, c=p.cst_final_location_id.company_id.name))
        if p.state == "draft":
            p.action_confirm()
        p.action_assign()
        prec = self.env["decimal.precision"].precision_get("Product Unit")
        short = []
        for m in moves:
            if float_compare(m.quantity, m.product_uom_qty, precision_digits=prec) < 0:
                short.append(_("• %(p)s: kerak %(n)s, bor %(h)s %(u)s",
                               p=m.product_id.display_name, n=self._fmt(m.product_uom_qty),
                               h=self._fmt(m.quantity), u=m.product_uom.name))
        if short:
            raise UserError(_("%s omborida yetarli emas:\n%s",
                              p.location_id.complete_name, "\n".join(short)))
        moves.write({"picked": True})
        now = fields.Datetime.now()
        p.write({"cst_sent_at": now, "cst_sent_by_id": self.env.uid})
        if p.cst_final_location_id:
            self._send_intercompany(p)
        p.message_post(body=_("Jo'natildi → %(d)s, qabul qiluvchi: %(r)s",
                              d=dest.complete_name, r=p.cst_receiver_id.name))
        return True

    def _send_intercompany(self, p):
        """Goods leave company A for the transit location now; company B gets a
        receipt from transit that its receiver validates."""
        res = p.with_context(cst_skip_wh_control=True, skip_backorder=True,
                             picking_ids_not_to_backorder=p.ids).button_validate()
        if p.state != "done":
            raise UserError(_("%s jo'natmasini tasdiqlab bo'lmadi.", p.name))
        final = p.cst_final_location_id
        company = final.company_id
        ptype = final.warehouse_id.int_type_id or self.env["stock.picking.type"].sudo().search([
            ("code", "=", "internal"), ("company_id", "=", company.id)], limit=1)
        if not ptype:
            raise UserError(_("%s kompaniyasida ichki ko'chirish turi yo'q.", company.name))
        Picking = self.env["stock.picking"].sudo().with_company(company)
        transit = self._transit()
        receipt = Picking.create({
            "picking_type_id": ptype.id,
            "location_id": transit.id,
            "location_dest_id": final.id,
            "company_id": company.id,
            "origin": p.name,
            "cst_receiver_id": p.cst_receiver_id.id,
            "cst_ic_origin_id": p.id,
            "cst_sent_at": p.cst_sent_at,
            "cst_sent_by_id": p.cst_sent_by_id.id,
            "note": p.note,
            "move_ids": [fields.Command.create({
                "product_id": m.product_id.id,
                "product_uom": m.product_uom.id,
                "product_uom_qty": m.quantity,
                "location_id": transit.id,
                "location_dest_id": final.id,
                "company_id": company.id,
            }) for m in p.move_ids.filtered(lambda m: m.state == "done" and m.quantity)],
        })
        receipt.action_confirm()
        receipt.action_assign()
        p.cst_ic_receipt_id = receipt
        return res

    @api.model
    def ui_receive(self, picking_id, quantities=None):
        """Receiver accepts. ``quantities`` = {move_id: qty}; less than sent is
        allowed within a company (the rest stays where it came from)."""
        self._check()
        p = self._picking(picking_id)
        if self._status(p) != "sent":
            raise UserError(_("Bu ichki o'tkazma qabul qilish holatida emas."))
        if not self._can_receive(p):
            raise UserError(_("Faqat qabul qiluvchi (%s) qabul qila oladi.", self._receiver(p).name))
        target = p.cst_ic_receipt_id or p
        quantities = {int(k): float(v or 0.0) for k, v in (quantities or {}).items()}
        prec = self.env["decimal.precision"].precision_get("Product Unit")
        moves = target.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        if target.state != "assigned":
            target.action_assign()
        for m in moves:
            qty = quantities.get(m.id, m.product_uom_qty)
            qty = min(max(qty, 0.0), m.product_uom_qty)
            if target != p and float_compare(qty, m.product_uom_qty, precision_digits=prec) != 0:
                raise UserError(_(
                    "Kompaniyalararo ichki o'tkazma to'liq qabul qilinadi. Farq bo'lsa, "
                    "qabul qilgach qaytarib jo'nating."))
            m.quantity = qty
            m.picked = True
        if all(float_is_zero(m.quantity, precision_digits=prec) for m in moves):
            raise UserError(_("Hech narsa qabul qilinmadi. Kamida bitta miqdor kiriting."))
        target.with_context(skip_backorder=True, cancel_backorder=True,
                            picking_ids_not_to_backorder=target.ids).button_validate()
        if target.state != "done":
            raise UserError(_("%s ni tasdiqlab bo'lmadi.", target.name))
        now = fields.Datetime.now()
        target.write({"cst_received_at": now, "cst_received_by_id": self.env.uid})
        if target != p:
            p.write({"cst_received_at": now, "cst_received_by_id": self.env.uid})
        return True

    @api.model
    def ui_cancel(self, picking_id):
        self._check()
        p = self._picking(picking_id)
        if not self._can_edit(p):
            raise UserError(_("Faqat jo'natilmagan ichki o'tkazmani bekor qilish mumkin."))
        p.action_cancel()
        return True
