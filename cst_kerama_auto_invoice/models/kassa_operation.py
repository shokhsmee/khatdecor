import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class KassaOperation(models.Model):
    _inherit = "cst.kassa.operation"

    def _cst_post(self):
        result = super()._cst_post()
        if self.operation_type == "supplier_out" and self.payment_id \
                and self.company_id.cst_auto_invoice_purchase:
            # a payment to a supplier pays his bills, oldest first
            self.env["account.move"]._cst_match_payable(
                self.partner_id.commercial_partner_id, self.company_id)
        return result


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.model
    def _cst_match_payable(self, partners, company):
        """Supplier money and supplier bills that are both still open meet,
        oldest first: a prepayment closes the bill that follows it, a payment
        closes the oldest bill."""
        Line = self.env["account.move.line"].sudo()
        for partner in partners:
            domain = [
                ("partner_id", "child_of", partner.id), ("company_id", "=", company.id),
                ("account_id.account_type", "=", "liability_payable"),
                ("parent_state", "=", "posted"), ("reconciled", "=", False),
            ]
            bills = Line.search(domain + [("amount_residual", "<", 0),
                                          ("move_id.move_type", "=", "in_invoice")], order="date, id")
            money = Line.search(domain + [("amount_residual", ">", 0)], order="date, id")
            if not bills or not money:
                continue
            try:
                with self.env.cr.savepoint():
                    for bill in bills:
                        for paid in money:
                            if bill.reconciled:
                                break
                            if paid.reconciled:
                                continue
                            (bill + paid).with_context(cst_kassa_skip_guard=True).reconcile()
            except Exception as exc:  # noqa: BLE001
                self.env.invalidate_all()
                _logger.warning("supplier matching %s failed: %s", partner.display_name, exc)
