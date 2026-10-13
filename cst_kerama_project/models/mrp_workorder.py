from odoo import fields, models


class MrpWorkorder(models.Model):
    """Work orders raised by the *Start Manufacturing* wizard.

    One operation can be shared between several work centers -- 30 boards
    printed as 15 on Linya 1 and 15 on Linya 2 -- so each work order carries
    the slice of the order it is responsible for.
    """

    _inherit = "mrp.workorder"

    cst_manager_id = fields.Many2one(
        "res.users", string="Operation Manager", domain=[("share", "=", False)],
        help="Who answers for this operation on this work center.")
    cst_split_qty = fields.Float(
        string="Assigned Qty", digits="Product Unit",
        help="Share of the manufacturing order this work center takes on for "
             "this operation. Empty means the whole quantity.")
