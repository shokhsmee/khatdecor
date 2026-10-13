from markupsafe import Markup

from odoo import _, api, fields, models


class CstMoveLineComment(models.Model):
    """A comment written about one transfer line.

    Kept on the line itself so it can be read back there, and echoed to the
    transfer's chatter so the whole team sees it in one place.
    """

    _name = "cst.move.line.comment"
    _description = "Transfer Line Comment"
    _order = "id desc"

    line_id = fields.Many2one(
        "stock.move.line", string="Line", required=True,
        ondelete="cascade", index=True)
    picking_id = fields.Many2one(
        related="line_id.picking_id", store=True, index=True, string="Transfer")
    product_id = fields.Many2one(related="line_id.product_id", store=True)
    company_id = fields.Many2one(related="line_id.company_id", store=True)
    body = fields.Text(string="Comment", required=True)
    user_id = fields.Many2one(
        "res.users", string="Written by", default=lambda self: self.env.user,
        required=True)

    @api.model_create_multi
    def create(self, vals_list):
        comments = super().create(vals_list)
        for comment in comments:
            comment._cst_post_to_chatter()
        return comments

    def _cst_post_to_chatter(self):
        self.ensure_one()
        picking = self.picking_id
        if not picking:
            return
        picking.message_post(
            body=Markup("<p><b>%s</b><br/>%s</p>") % (
                _("Comment on %s", self.line_id._cst_line_label()), self.body),
            author_id=self.user_id.partner_id.id or None,
        )
