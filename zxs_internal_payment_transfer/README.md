# Internal Payment Transfer

Odoo 19 module to restore the classic internal liquidity transfer workflow:
paired Send/Receive payments between bank and cash journals with automatic
journal entries and liquidity transfer account reconciliation.

## Supported scenarios

- Bank → Bank
- Bank → Cash
- Cash → Bank
- Cash → Cash and any other bank/cash journal pair in the same company

## Installation

1. Copy this module into your Odoo `addons` path.
2. Update the apps list and install **Internal Payment Transfer**.
3. Configure the company **Internal Transfer** account under
   *Accounting → Configuration → Settings*.
4. Set **Outstanding Payments** and **Outstanding Receipts** on the Manual
   payment method for each bank and cash journal.

## Dependencies

- `account` (Invoicing)

## Availability

| Platform     | Supported |
|--------------|-----------|
| Odoo Online  | No        |
| Odoo.sh      | Yes       |
| On Premise   | Yes       |

Free open-source module (LGPL-3). Compatible with Odoo Community and Enterprise
when using standard Accounting dependencies only.

## License

LGPL-3. See [LICENSE](LICENSE) for details.

## Author

[Zarixsol](https://www.zarixsol.com) — info@zarixsol.com

## Local changes (Khatdecor, 2026-09-18)

Patched on site; re-apply after any upgrade of this addon from the vendor.

* **Cross-currency transfers crashed.** The paired payment was created in the
  *source* payment's currency. A journal tied to a currency (here the USD cash
  box) holds an account that forces that currency, so the destination line was
  refused with *"The account selected on your journal entry forces to provide a
  secondary currency."* The paired payment is now created in the destination
  journal's own currency.
* **New field `destination_amount` ("Amount Received").** Shown only when the two
  journals are held in different currencies. Filled in at the rate of the payment
  date and editable, so the rate actually obtained can be entered.
* The auto-filled payment method line in `action_post` now applies to internal
  transfers only, instead of every payment being posted.
* The paired payment is created with `with_company(payment.company_id)`.
