from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockMoveLine(models.Model):
    """Per-line photo proof and comments, so a warehouse worker can document
    each product separately from the Barcode app."""

    _inherit = "stock.move.line"

    cst_photo_ids = fields.Many2many(
        "ir.attachment", "cst_move_line_photo_rel", "line_id", "attachment_id",
        string="Photos", copy=False,
        help="Photos taken for this line only.")
    cst_photo_count = fields.Integer(compute="_compute_cst_photo_count")
    cst_photo_html = fields.Html(
        string="Photos", compute="_compute_cst_photo_html", sanitize=False)
    cst_comment_ids = fields.One2many(
        "cst.move.line.comment", "line_id", string="Comments", copy=False)
    cst_comment_count = fields.Integer(compute="_compute_cst_comment_count")
    cst_note = fields.Text(
        string="Comment", copy=False,
        help="Explanation about this line. Saved automatically; every change is "
             "kept in the comment history and posted on the transfer.")

    @api.depends("cst_photo_ids")
    def _compute_cst_photo_count(self):
        for line in self:
            line.cst_photo_count = len(line.cst_photo_ids)

    @api.depends("cst_comment_ids")
    def _compute_cst_comment_count(self):
        for line in self:
            line.cst_comment_count = len(line.cst_comment_ids)

    @api.depends("cst_photo_ids")
    def _compute_cst_photo_html(self):
        for line in self:
            if not line.cst_photo_ids:
                line.cst_photo_html = False
                continue
            thumbs = Markup("").join(
                Markup(
                    '<a href="/web/image/%(id)s" target="_blank" title="%(name)s">'
                    '<img src="/web/image/%(id)s/200x200" alt="%(name)s" '
                    'style="height:110px;width:auto;border-radius:6px;'
                    'margin:0 6px 6px 0;object-fit:cover;'
                    'border:1px solid rgba(128,128,128,.35)"/></a>'
                ) % {"id": attachment.id, "name": attachment.name or ""}
                for attachment in line.cst_photo_ids)
            line.cst_photo_html = Markup('<div class="d-flex flex-wrap">%s</div>') % thumbs

    def _get_fields_stock_barcode(self):
        """Expose the per-line counters to the Barcode client."""
        return super()._get_fields_stock_barcode() + [
            "cst_photo_count", "cst_comment_count"]

    def _cst_line_label(self):
        self.ensure_one()
        qty = self.quantity or self.quantity_product_uom or 0.0
        return "%s — %g %s" % (
            self.product_id.display_name, qty,
            self.product_uom_id.name or self.product_id.uom_id.name or "")

    # ------------------------------------------------------------------
    #  Called from the Barcode client
    # ------------------------------------------------------------------
    def cst_line_extras(self):
        """Everything documented on this line, for the Barcode line screen."""
        self.ensure_one()
        return {
            "note": self.cst_note or "",
            "photos": [{
                "id": attachment.id,
                "name": attachment.name or "",
            } for attachment in self.cst_photo_ids],
            "comments": [{
                "id": comment.id,
                "body": comment.body or "",
                "user": comment.user_id.name or "",
                "date": fields.Datetime.to_string(comment.create_date) or "",
            } for comment in self.cst_comment_ids],
        }

    def cst_barcode_add_photo(self, datas, filename=None):
        """Attach one photo to THIS line and log it on the transfer's chatter."""
        self.ensure_one()
        picking = self.picking_id
        if not picking:
            raise UserError(_("This line does not belong to a transfer yet."))
        attachment = self.env["ir.attachment"].create({
            "name": filename or ("%s.jpg" % (self.product_id.default_code or "photo")),
            "datas": datas,
            # owned by the transfer so chatter access rules apply as usual;
            # the m2m below is what ties it to this one line
            "res_model": "stock.picking",
            "res_id": picking.id,
        })
        self.cst_photo_ids = [(4, attachment.id)]
        picking.message_post(
            body=Markup("<p>%s</p>") % _("Photo added for %s", self._cst_line_label()),
            attachment_ids=attachment.ids,
        )
        self.invalidate_recordset(["cst_photo_ids", "cst_photo_count"])
        return self.cst_line_extras()

    def cst_barcode_set_note(self, body):
        """Save this line's comment (called automatically as the user types).

        Nothing happens when the text is unchanged, so the history and the
        chatter only get an entry per real edit — not per keystroke.
        """
        self.ensure_one()
        body = (body or "").strip()
        if body == (self.cst_note or "").strip():
            return self.cst_line_extras()
        if not self.picking_id:
            raise UserError(_("This line does not belong to a transfer yet."))
        self.cst_note = body
        if body:
            # the history entry posts it on the transfer's chatter
            self.env["cst.move.line.comment"].create({"line_id": self.id, "body": body})
        self.invalidate_recordset(["cst_comment_ids", "cst_comment_count"])
        return self.cst_line_extras()

    def cst_barcode_add_note(self, body):
        """Kept for the quick comment button on the barcode line row."""
        self.ensure_one()
        body = (body or "").strip()
        if not body:
            raise UserError(_("Write something before sending the comment."))
        if not self.picking_id:
            raise UserError(_("This line does not belong to a transfer yet."))
        self.env["cst.move.line.comment"].create({"line_id": self.id, "body": body})
        self.invalidate_recordset(["cst_comment_ids", "cst_comment_count"])
        return self.cst_line_extras()
