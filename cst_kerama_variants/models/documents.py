"""The characteristic on every document a product travels through.

A storekeeper reading a sale order, a bill of materials or a manufacturing
order has to see *which* variant the line is about without opening it, so each
of those models carries the product's characteristic as its own column. They
are all plain related fields: the value lives once, on the variant.
"""

from odoo import fields, models

_HELP = "Variant characteristic of the product on this line."


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    cst_characteristic = fields.Char(
        related="product_id.cst_characteristic", string="Xarakteristika", help=_HELP)


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    cst_characteristic = fields.Char(
        related="product_id.cst_characteristic", string="Xarakteristika", help=_HELP)


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    cst_characteristic = fields.Char(
        related="product_id.cst_characteristic", string="Xarakteristika", help=_HELP)


class MrpBomLine(models.Model):
    _inherit = "mrp.bom.line"

    cst_characteristic = fields.Char(
        related="product_id.cst_characteristic", string="Xarakteristika", help=_HELP)


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    cst_characteristic = fields.Char(
        related="product_id.cst_characteristic", string="Xarakteristika",
        help="Characteristic this bill of materials is written for. Empty means "
             "it serves every variant of the product.")


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    cst_characteristic = fields.Char(
        related="product_id.cst_characteristic", string="Xarakteristika",
        help="Variant characteristic of the product being manufactured.")


class StockMove(models.Model):
    _inherit = "stock.move"

    cst_characteristic = fields.Char(
        related="product_id.cst_characteristic", string="Xarakteristika", help=_HELP)
