# -*- coding: utf-8 -*-
# Copyright (C) 2026 Zarixsol
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    is_internal_transfer = fields.Boolean(
        string='Internal Transfer',
        tracking=True,
    )
    destination_journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Destination Journal',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id), ('id', '!=', journal_id)]",
        check_company=True,
        tracking=True,
    )
    destination_currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Destination Currency',
        compute='_compute_destination_currency_id',
        help="The currency the destination journal is held in.  A journal tied "
             "to one currency can only receive that currency.",
    )
    destination_amount = fields.Monetary(
        string='Amount Received',
        currency_field='destination_currency_id',
        compute='_compute_destination_amount', store=True, readonly=False,
        tracking=True,
        help="What lands in the destination journal.  Filled in at the rate of "
             "the payment date; type over it to use the rate you actually got.",
    )

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if self.env.context.get('default_is_internal_transfer'):
            company = self.env.company
            vals.update({
                'is_internal_transfer': True,
                'partner_id': company.partner_id.id,
                'partner_type': 'customer',
                'payment_type': vals.get('payment_type') or 'outbound',
            })
        return vals

    @api.depends('destination_journal_id', 'currency_id', 'company_id')
    def _compute_destination_currency_id(self):
        for payment in self:
            payment.destination_currency_id = (
                payment.destination_journal_id.currency_id
                or payment.currency_id
                or (payment.company_id or self.env.company).currency_id
            )

    @api.depends('amount', 'currency_id', 'destination_currency_id', 'date',
                 'company_id', 'is_internal_transfer')
    def _compute_destination_amount(self):
        for payment in self:
            payment.destination_amount = payment._convert_to_destination(payment.amount)

    def _convert_to_destination(self, amount):
        """`amount`, expressed in the currency the destination journal is held in."""
        self.ensure_one()
        target = self.destination_currency_id
        if not target or target == self.currency_id:
            return amount
        return self.currency_id._convert(
            amount, target,
            self.company_id or self.env.company,
            self.date or fields.Date.context_today(self),
        )

    @api.constrains('is_internal_transfer', 'destination_journal_id', 'journal_id', 'company_id')
    def _check_internal_transfer_configuration(self):
        for payment in self.filtered('is_internal_transfer'):
            if not payment.destination_journal_id:
                raise ValidationError(_("Destination journal is required for internal transfers."))
            if payment.destination_journal_id == payment.journal_id:
                raise ValidationError(_("Source and destination journals must be different."))
            if not payment.company_id.transfer_account_id:
                raise ValidationError(_(
                    "Configure an Internal Transfer account under "
                    "Accounting -> Configuration -> Settings."
                ))

    @api.onchange('is_internal_transfer', 'destination_journal_id')
    def _onchange_internal_transfer_partner(self):
        for payment in self:
            if payment.is_internal_transfer:
                payment.partner_id = payment.company_id.partner_id
                if not payment.paired_internal_transfer_payment_id:
                    payment.payment_type = 'outbound'
                payment._set_default_payment_method_line()
            elif payment.partner_id == payment.company_id.partner_id:
                payment.partner_id = False

    @api.onchange('journal_id', 'payment_type')
    def _onchange_journal_payment_method_line(self):
        for payment in self:
            if payment.journal_id:
                payment._set_default_payment_method_line()

    def _set_default_payment_method_line(self):
        for payment in self:
            available_lines = payment.journal_id._get_available_payment_method_lines(
                payment.payment_type,
            )
            if payment.payment_method_line_id in available_lines:
                continue
            if available_lines:
                payment.payment_method_line_id = available_lines[0]
            else:
                payment.payment_method_line_id = False

    def _get_internal_transfer_payment_method_line(self, journal, payment_type):
        method_lines = journal._get_available_payment_method_lines(payment_type)
        if not method_lines:
            raise UserError(_(
                "No %(payment_type)s payment method is configured on journal %(journal)s. "
                "Configure Outstanding Payments/Receipts on the journal payment methods.",
                payment_type=dict(self._fields['payment_type'].selection).get(payment_type, payment_type),
                journal=journal.display_name,
            ))
        manual_line = method_lines.filtered(lambda line: line.code == 'manual')[:1]
        return manual_line or method_lines[0]

    @api.depends(
        'journal_id',
        'partner_id',
        'partner_type',
        'is_internal_transfer',
        'destination_journal_id',
        'company_id',
    )
    def _compute_destination_account_id(self):
        transfers = self.filtered('is_internal_transfer')
        others = self - transfers
        for payment in transfers:
            payment.destination_account_id = payment.company_id.transfer_account_id
        if others:
            super(AccountPayment, others)._compute_destination_account_id()

    @api.depends('partner_id', 'company_id', 'payment_type', 'destination_journal_id', 'is_internal_transfer')
    def _compute_available_partner_bank_ids(self):
        super()._compute_available_partner_bank_ids()
        for payment in self.filtered(lambda p: p.is_internal_transfer and p.destination_journal_id):
            payment.available_partner_bank_ids = payment.destination_journal_id.bank_account_id

    def _get_aml_default_display_name_list(self):
        self.ensure_one()
        if self.is_internal_transfer:
            if self.payment_type == 'inbound':
                label = _('Transfer to %s', self.journal_id.display_name)
            else:
                label = _('Transfer from %s', self.journal_id.display_name)
            if self.memo:
                return [
                    ('label', label),
                    ('sep', ': '),
                    ('memo', self.memo),
                ]
            return [('label', label)]
        return super()._get_aml_default_display_name_list()

    @api.model
    def _get_trigger_fields_to_synchronize(self):
        return super()._get_trigger_fields_to_synchronize() + (
            'is_internal_transfer',
            'destination_journal_id',
        )

    def action_post(self):
        for payment in self.filtered(
                lambda p: p.is_internal_transfer and not p.payment_method_line_id):
            method_line = payment._get_internal_transfer_payment_method_line(
                payment.journal_id,
                payment.payment_type,
            )
            payment.write({'payment_method_line_id': method_line.id})

        transfers = self.filtered(
            lambda p: p.is_internal_transfer
            and p.destination_journal_id
            and not p.paired_internal_transfer_payment_id
        )
        for payment in transfers:
            if payment.amount <= 0:
                raise UserError(_("Internal transfer amount must be greater than zero."))
            if payment.payment_type != 'outbound':
                raise UserError(_(
                    "Internal transfers must be confirmed as Send payments. "
                    "The matching Receive payment is created automatically on %(journal)s.",
                    journal=payment.destination_journal_id.display_name,
                ))

        res = super().action_post()

        transfers._create_paired_internal_transfer_payment()
        return res

    def _prepare_paired_internal_transfer_vals(self):
        self.ensure_one()
        payment_type = 'inbound' if self.payment_type == 'outbound' else 'outbound'
        journal = self.destination_journal_id
        method_line = self._get_internal_transfer_payment_method_line(journal, payment_type)
        # A journal tied to a currency can only hold that currency: its account
        # refuses a line in anything else.  So the paired payment is made in the
        # destination journal's own currency, for the converted amount.
        currency = journal.currency_id or self.currency_id
        amount = self.amount
        if currency != self.currency_id:
            amount = self.destination_amount or self._convert_to_destination(self.amount)
        return {
            'company_id': self.company_id.id,
            'is_internal_transfer': True,
            'payment_type': payment_type,
            'partner_type': self.partner_type,
            'partner_id': self.partner_id.id,
            'amount': amount,
            'date': self.date,
            'memo': self.memo,
            'journal_id': journal.id,
            'destination_journal_id': self.journal_id.id,
            'payment_method_line_id': method_line.id,
            'currency_id': currency.id,
            'paired_internal_transfer_payment_id': self.id,
        }

    def _create_paired_internal_transfer_payment(self):
        for payment in self:
            transfer_account = payment.company_id.transfer_account_id
            if not transfer_account:
                raise UserError(_(
                    "Configure an Internal Transfer account under "
                    "Accounting -> Configuration -> Settings."
                ))

            paired_payment = self.env['account.payment'].with_company(
                payment.company_id,
            ).create(payment._prepare_paired_internal_transfer_vals())
            paired_payment.action_post()
            payment.paired_internal_transfer_payment_id = paired_payment

            payment.message_post(
                body=_(
                    "A paired internal transfer payment was created: %(link)s",
                    link=paired_payment._get_html_link(),
                ),
            )
            paired_payment.message_post(
                body=_(
                    "This payment was created from: %(link)s",
                    link=payment._get_html_link(),
                ),
            )

            if payment.move_id and paired_payment.move_id:
                lines = (payment.move_id.line_ids + paired_payment.move_id.line_ids).filtered(
                    lambda line: line.account_id == transfer_account and not line.reconciled
                )
                if len(lines) >= 2:
                    lines.reconcile()
                    payment._book_internal_transfer_exchange_difference(lines)

    def _book_internal_transfer_exchange_difference(self, lines):
        """Send whatever the two sides differ by to the exchange gain/loss account.

        A transfer between two currencies never balances to the cent: the
        receiving journal rounds to its own decimals, and the rate actually
        obtained is rarely the one in the rate table.  Reconciling lines held in
        two different currencies leaves that remainder sitting on the liquidity
        transfer account, which is meant to end every transfer at zero - so it
        is booked as a currency result instead.
        """
        self.ensure_one()
        company = self.company_id
        transfer_account = company.transfer_account_id
        residual = sum(lines.mapped('amount_residual'))
        if company.currency_id.is_zero(residual):
            return self.env['account.move']

        journal = company.currency_exchange_journal_id
        if not journal:
            raise UserError(_(
                "This transfer converts %(source)s into %(destination)s, and the "
                "two sides differ by %(amount)s. Set an Exchange Gain or Loss "
                "Journal under Accounting -> Configuration -> Settings so the "
                "difference can be booked.",
                source=self.currency_id.name,
                destination=self.destination_currency_id.name,
                amount=company.currency_id.format(abs(residual)),
            ))
        account = (
            company.expense_currency_exchange_account_id if residual > 0
            else company.income_currency_exchange_account_id
        )
        if not account:
            raise UserError(_(
                "No Exchange %(kind)s account is configured, so the "
                "%(amount)s this transfer differs by cannot be booked. Set it "
                "under Accounting -> Configuration -> Settings.",
                kind=_("Loss") if residual > 0 else _("Gain"),
                amount=company.currency_id.format(abs(residual)),
            ))

        label = _("Exchange difference on %s", self.name or self.display_name)
        amount = abs(residual)
        # residual > 0: a debit is left on the transfer account, so credit it
        # back and charge the loss; the other way round for a gain.
        move = self.env['account.move'].with_company(company).create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': self.date,
            'ref': label,
            'line_ids': [
                fields.Command.create({
                    'name': label,
                    'account_id': transfer_account.id,
                    'debit': 0.0 if residual > 0 else amount,
                    'credit': amount if residual > 0 else 0.0,
                }),
                fields.Command.create({
                    'name': label,
                    'account_id': account.id,
                    'debit': amount if residual > 0 else 0.0,
                    'credit': 0.0 if residual > 0 else amount,
                }),
            ],
        })
        move.action_post()
        (lines + move.line_ids).filtered(
            lambda line: line.account_id == transfer_account and not line.reconciled
        ).reconcile()
        return move

    def action_open_paired_payment(self):
        self.ensure_one()
        if not self.paired_internal_transfer_payment_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Paired Internal Transfer'),
            'res_model': 'account.payment',
            'view_mode': 'form',
            'res_id': self.paired_internal_transfer_payment_id.id,
        }

    def action_open_destination_journal(self):
        self.ensure_one()
        if not self.destination_journal_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Destination Journal'),
            'res_model': 'account.journal',
            'view_mode': 'form',
            'target': 'new',
            'res_id': self.destination_journal_id.id,
        }
