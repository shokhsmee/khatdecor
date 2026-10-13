# Khatdecor — Odoo 19 custom addons

Custom modules of the **Khatdecor** (ex-Kerama) ERP: Odoo **19.0 Enterprise**, database `kerama`. This file lists, for every module, what it needs from Odoo, from Odoo Enterprise, from third-party vendors (MuK, Cybrosys, OCA) and from other modules in this repo — so any module can be taken to another database.

> `bypass_expiry` is deployed on the server but deliberately **not** kept in this repository.

## Contents

1. [Server layout](#server-layout)
2. [Third-party addons](#third-party-addons)
3. [Odoo Enterprise modules needed](#odoo-enterprise-modules-needed)
4. [Python libraries](#python-libraries)
5. [Install order](#install-order)
6. [Modules](#modules)
7. [Integrations: configuration](#integrations-configuration)
8. [Install / upgrade](#install--upgrade)

## Server layout

| Path | What | Source / revision |
|---|---|---|
| `/opt/kerama/addons/community` | Odoo 19.0 Community | odoo/odoo `22d6534d` (2026-05-23) |
| `/opt/kerama/addons/enterprise` | Odoo 19.0 Enterprise | odoo/enterprise `c583e819` (2026-05-23) |
| `/opt/kerama/addons/oca/web` | OCA web | [OCA/web](https://github.com/OCA/web) `b51a408` — none installed |
| `/opt/kerama/addons/cybro` | Cybrosys addons | [CybroOdoo/CybroAddons](https://github.com/CybroOdoo/CybroAddons) 19.0 `c56ba936` |
| `/opt/odoo-modules` | MuK IT addons | [muk-it/odoo-modules](https://github.com/muk-it/odoo-modules) 19.0 `b494fea` |
| `/opt/kerama/addons/custom-addons` | **this repo** | |

`addons_path` order in `odoo.conf`: community → enterprise → oca/web → cybro → odoo-modules → custom-addons. Also set: `dbfilter = ^kerama$`, `proxy_mode = True`, `workers = 4`.

## Third-party addons

Installed on the database and needed by this repo or used alongside it. The *Needed by* column tells you which of our modules break without it.

| Vendor | Module | Version | Needed by |
|---|---|---|---|
| Cybrosys | `access_roles` | 19.0.1.0.0 | `cst_kerama_roles` |
| Cybrosys | `sale_mini_dashboard` | 19.0.1.0.0 | `cst_kerama_sale_dashboard_company` |
| Cybrosys | `invoice_mini_dashboard` | 19.0.1.0.0 | — (used directly) |
| Cybrosys | `order_line_sequences` | 19.0.1.0.1 | — (used directly) |
| Cybrosys | `mass_price_update` | 19.0.1.0.0 | — (used directly) |
| Cybrosys | `login_as_any_user` | 19.0.1.0.0 | — (used directly) |
| Cybrosys | `login_user_detail` | 19.0.1.0.0 | — (used directly) |
| MuK | `muk_ai` | 19.0.1.16.2 | `cst_kerama_ai_voice` |
| MuK | `muk_ai_chatter` | 19.0.1.0.2 | — (used directly) |
| MuK | `muk_ai_enterprise` | 19.0.1.1.1 | — (used directly) |
| MuK | `muk_ai_schedule` | 19.0.1.1.3 | — (used directly) |
| MuK | `muk_ai_skills` | 19.0.1.2.4 | — (used directly) |
| MuK | `muk_ai_automation` | 19.0.1.1.1 | — (used directly) |
| MuK | `muk_mcp` | 19.0.3.0.9 | — (used directly) |
| MuK | `muk_product` | 19.0.1.4.3 | `cst_kerama_roles` |
| MuK | `muk_contacts` | 19.0.1.1.17 | — (used directly) |
| MuK | `muk_web_appsbar` | 19.0.1.1.7 | `cst_kerama_appsbar` |
| MuK | `muk_web_enterprise_theme` | 19.0.1.4.6 | — (used directly) |
| MuK | `muk_web_chatter` | 19.0.1.4.4 | — (used directly) |
| MuK | `muk_web_dialog` | 19.0.1.0.6 | — (used directly) |
| MuK | `muk_web_colors` | 19.0.1.0.6 | — (used directly) |
| MuK | `muk_web_group` | 19.0.1.0.3 | — (used directly) |
| MuK | `muk_web_list_column` | 19.0.1.0.3 | — (used directly) |
| MuK | `muk_web_list_mode` | 19.0.1.0.7 | — (used directly) |
| MuK | `muk_web_refresh` | 19.0.1.1.5 | — (used directly) |
| MuK | `muk_web_actions` | 19.0.1.1.2 | — (used directly) |
| MuK | `muk_web_utils` | 19.0.1.1.11 | — (used directly) |

**Local additions to vendor folders (not in their git):** Uzbek translations — `i18n_extra/uz.po` in muk_ai, muk_ai_chatter, muk_ai_enterprise, muk_ai_schedule, muk_ai_skills, muk_mcp (masters + `restore.sh` in `/opt/kerama/i18n-uz/`), and `i18n/` in Cybrosys `sale_mini_dashboard` and `invoice_mini_dashboard`. Re-copy them after updating those vendors.

## Odoo Enterprise modules needed

Directly required by our modules (each pulls its own Enterprise dependencies):

- `account_asset` — `cst_kerama_reports`
- `account_bank_statement_import_csv` — `cst_kerama_finance`
- `account_reports` — `cst_kerama_reports`, `cst_kerama_telegram`
- `accountant` — `cst_kerama_reports`, `cst_kerama_roles`
- `mrp_account_enterprise` — `cst_kerama_reports`
- `mrp_workorder` — `cst_kerama_payroll`, `cst_kerama_project`, `cst_kerama_shift`, `cst_kerama_shopfloor`
- `quality` — `cst_kerama_roles`
- `stock_barcode` — `cst_kerama_wh_control`
- `stock_enterprise` — `cst_kerama_reports`

Without Enterprise, these will not install: `cst_kerama_finance`, `cst_kerama_payroll`, `cst_kerama_project`, `cst_kerama_reports`, `cst_kerama_roles`, `cst_kerama_shift`, `cst_kerama_shopfloor`, `cst_kerama_telegram`, `cst_kerama_wh_control`, and every module depending on them (see *Install order*).

## Python libraries

Already in Odoo's requirements unless noted. Install into the Odoo venv (`/opt/kerama/venv`).

| Library | Version on server | Used by |
|---|---|---|
| `openpyxl` | 3.1.2 | `cst_kerama_hr_docs`, `cst_kerama_payroll`, `cst_kerama_product_price` |
| `xlsxwriter` | 3.1.9 | `cst_kerama_payroll`, `cst_kerama_product_price`, `cst_kerama_reports`, `cst_kerama_shift` |
| `python-docx` | 1.2.0 — **extra, not in Odoo's requirements** | `cst_kerama_hr_docs` |
| `requests` | (Odoo requirement) | `cst_kerama_ai_voice`, `cst_kerama_telegram`, `hikvision_attendance`, `moizvonki_calls` |

## Install order

Custom modules, each after what it depends on — other modules of this repo, then `E:` Enterprise, `MuK:` / `Cybro:` vendor modules that must be on the addons path first (Odoo installs dependencies automatically, but only if it can find them):

```
 1. chatter_toggle                      
 2. cst_kerama_ai_voice                 ← MuK:muk_ai
 3. cst_kerama_appsbar                  ← MuK:muk_web_appsbar
 4. cst_kerama_payment_summary          
 5. cst_kerama_dashboard                ← cst_kerama_payment_summary
 6. cst_kerama_wh_control               ← E:stock_barcode
 7. cst_kerama_sale_receipt             
 8. cst_kerama_payroll                  ← E:mrp_workorder
 9. cst_kerama_kassa                    ← cst_kerama_payment_summary, cst_kerama_sale_receipt, cst_kerama_payroll
10. cst_kerama_variants                 
11. cst_kerama_reports                  ← cst_kerama_payroll, cst_kerama_dashboard, cst_kerama_variants, E:account_reports, E:accountant, E:stock_enterprise, E:mrp_account_enterprise, E:account_asset
12. cst_kerama_shift                    ← cst_kerama_variants, cst_kerama_payroll, cst_kerama_reports, E:mrp_workorder
13. cst_kerama_roles                    ← cst_kerama_kassa, cst_kerama_payroll, cst_kerama_wh_control, cst_kerama_dashboard, cst_kerama_reports, cst_kerama_shift, Cybro:access_roles, E:quality, E:accountant, MuK:muk_product
14. cst_kerama_dispatch                 ← cst_kerama_wh_control, cst_kerama_roles, cst_kerama_sale_receipt, cst_kerama_variants
15. cst_kerama_finance                  ← E:account_bank_statement_import_csv
16. cst_kerama_full_payment             
17. cst_kerama_hr_docs                  ← cst_kerama_payroll
18. cst_kerama_journal_balance          
19. cst_kerama_landed_cost              
20. cst_kerama_no_negative              
21. cst_kerama_product_display          
22. cst_kerama_product_price            
23. cst_kerama_product_search           ← cst_kerama_variants
24. cst_kerama_project                  ← cst_kerama_dashboard, cst_kerama_payment_summary, cst_kerama_variants, cst_kerama_shift, E:mrp_workorder
25. cst_kerama_purchase_ux              ← cst_kerama_wh_control, cst_kerama_landed_cost, cst_kerama_payroll, cst_kerama_project
26. cst_kerama_sale_dashboard_company   ← Cybro:sale_mini_dashboard
27. cst_kerama_sale_onhand              
28. cst_kerama_sale_production          ← cst_kerama_shift, cst_kerama_project
29. cst_kerama_sale_return              
30. cst_kerama_sales_team_company       
31. cst_kerama_shopfloor                ← cst_kerama_shift, E:mrp_workorder
32. cst_kerama_telegram                 ← E:account_reports
33. cst_kerama_wh_flow                  ← cst_kerama_shift, cst_kerama_wh_control, cst_kerama_shopfloor, cst_kerama_sale_production
34. hikvision_attendance                
35. moizvonki_calls                     
36. zxs_internal_payment_transfer       
```

## Modules

Legend for *Depends*: **E** = Odoo Enterprise, **MuK** / **Cybro** = third-party vendor, **C** = another module in this repo; plain names are Odoo Community.

### Production

| Module | Version | What it does | Depends | Notes |
|---|---|---|---|---|
| `cst_kerama_shift`<br>Khatdecor Smena boshqaruvi | 19.0.1.7.0 | Bo'limlar, smenalar, bo'lim oynasi: buyurtmani liniyaga qo'yish, natija (1-sort / 2-sort / brak), smena yopilganda KPI fondi va jarima. | `mrp`, **E** `mrp_workorder`, `stock`, `hr`, `hr_attendance`, **C** `cst_kerama_variants`, **C** `cst_kerama_payroll`, **C** `cst_kerama_reports` | Department floor screen (OWL client action). `post_init_hook` re-routes BoM operations to their department's workcenters — review before installing on a different database. |
| `cst_kerama_shopfloor`<br>Khatdecor Shop Floor | 19.0.1.1.0 | Odoo Shop Floor operatorlar uchun: o'z stanoklari va o'z buyurtmalari, Face ID holati va ish vaqti taymeri, yangi buyurtma (texkarta, xomashyo, operatsiya va stanok tanlash), kartada sotuv raqami, 2-sort va brak. | **E** `mrp_workorder`, `sale_mrp`, `hr_attendance`, **C** `cst_kerama_shift` | Patches the Enterprise Shop Floor (`mrp_workorder`) JS. |
| `cst_kerama_wh_flow`<br>Khatdecor Ombor oqimi | 19.0.1.3.0 | Har bo'lim o'z omborida ishlaydi: xomashyo so'rovi, tayyor mahsulotni keyingi omborga avtomatik ko'chirish, ombor qabul qiluvchisi. | **C** `cst_kerama_shift`, **C** `cst_kerama_wh_control`, **C** `cst_kerama_shopfloor`, **C** `cst_kerama_sale_production`, `sale_stock`, `purchase_stock` | Per department set: working warehouse, raw-material warehouses, output warehouse; `cst_auto_supply` (default off), `cst_auto_forward`. `post_init_hook` present. |
| `cst_kerama_sale_production`<br>Khatdecor Sales → Production | 19.0.1.0.1 | «Ishlab chiqarishga yuborish» on the sales order: stock check of the order's products, pick what to make, and raise the orders through the shared «Yangi buyurtma» dialog — they land in the department queue as new, not started. | `sale_stock`, `sale_mrp`, **C** `cst_kerama_shift`, **C** `cst_kerama_project` |  |
| `cst_kerama_project`<br>Khatdecor Project Hub | 19.0.5.0.0 | Make Project the hub: link sales, purchases and expenses to a project and see income (paid/due), purchases, expenses and margin on a dashboard. | `sale_project`, `purchase`, `hr_expense`, `stock`, `mrp`, **E** `mrp_workorder`, `project_mrp`, `account`, `analytic`, **C** `cst_kerama_dashboard`, **C** `cst_kerama_payment_summary`, **C** `cst_kerama_variants`, **C** `cst_kerama_shift` |  |
| `cst_kerama_variants`<br>Khatdecor Mahsulot xarakteristikalari | 19.0.3.2.0 | Ustki qismi, zichligi va o'lchami — mahsulot variantlari sifatida, 1C'dagi «характеристика» o'rnida. | `product`, `stock`, `mrp`, `sale_management`, `purchase`, `account` |  |

### Warehouse

| Module | Version | What it does | Depends | Notes |
|---|---|---|---|---|
| `cst_kerama_wh_control`<br>Khatdecor Warehouse Controls | 19.0.1.9.0 | Photo proof on receipts and scraps, a named receiver on internal transfers, driver and vehicle details on receipts and deliveries, and a ready-to-validate badge on the transfer cards. | `stock`, **E** `stock_barcode` | Needs Enterprise `stock_barcode`. |
| `cst_kerama_dispatch`<br>Khatdecor Jo'natish | 19.0.1.3.0 | Barcode-style dispatch app: the warehouse prepares a sales order, the gate checks it line by line, the differences go back to the order. | `sale_stock`, `hr`, `barcodes`, **C** `cst_kerama_wh_control`, **C** `cst_kerama_roles`, **C** `cst_kerama_sale_receipt`, **C** `cst_kerama_variants` |  |
| `cst_kerama_no_negative`<br>Khatdecor Negative Balance Guard | 19.0.1.0.0 | Never let warehouse stock or a cash box go negative. | `stock`, `mrp`, `account` | Blocks validation of any stock move / cash payment that would go below zero (group «Allow Negative Stock» bypasses). |
| `cst_kerama_landed_cost`<br>Khatdecor Receipt Expenses (Landed Costs) | 19.0.1.0.0 | Enter delivery, customs and other expenses straight on a receipt, bill each service provider and roll the cost into the goods. | `stock_landed_costs`, `purchase_stock`, `account` |  |
| `cst_kerama_purchase_ux`<br>Khatdecor Purchase & Receipt Layout | 19.0.1.2.0 | Xarid buyurtmasi: rasm, transport raqami, qabul xarajatlari; qabul sahifalari tartibi. | `purchase_stock`, **C** `cst_kerama_wh_control`, **C** `cst_kerama_landed_cost`, **C** `cst_kerama_payroll`, **C** `cst_kerama_project` |  |
| `cst_kerama_sale_onhand`<br>Khatdecor Sale Line On-hand | 19.0.1.0.0 | Sotuv buyurtma qatorida mahsulotning ombordagi haqiqiy qoldig'i. | `sale_stock` |  |

### Sales

| Module | Version | What it does | Depends | Notes |
|---|---|---|---|---|
| `cst_kerama_sale_receipt`<br>Khatdecor Sale Receipt | 19.0.2.1.0 | Print a POS-style receipt from a confirmed sales order. | `sale` |  |
| `cst_kerama_sale_return`<br>Kerama Sales Return | 19.0.1.0.0 | Return / refund (Qaytarish) from the sales order: credit note, refund payment and stock return back to inventory in one wizard. | `sale`, `account`, `stock`, `sale_stock`, `stock_delivery` |  |
| `cst_kerama_full_payment`<br>Kerama Sales Full Payment | 19.0.1.0.0 | One-click full payment from the sales order: create + post the invoice, register and confirm the payment, all linked together. | `sale`, `account` |  |
| `cst_kerama_payment_summary`<br>Kerama Sales Payment Summary | 19.0.1.0.0 | Show Invoiced Amount, Waiting-for-approval payments (per currency) and Amount Due on the sales order. | `sale`, `account` |  |
| `cst_kerama_sales_team_company`<br>Kerama Sales Team Company Scope | 19.0.1.0.0 | Make the Sales Teams dashboard 'Invoicing' figure respect the active company | `sale` |  |
| `cst_kerama_sale_dashboard_company`<br>Kerama Sale Mini Dashboard Company Scope | 19.0.1.0.0 | Scope the Sales mini-dashboard amount totals to the active company | **Cybro** `sale_mini_dashboard` | Patch for Cybrosys **sale_mini_dashboard** (company scope). |

### Finance & HR

| Module | Version | What it does | Depends | Notes |
|---|---|---|---|---|
| `cst_kerama_kassa`<br>Khatdecor Kassa | 19.0.1.6.0 | Cash desk app: open / close / confirm the cash day, cash in and out, client payments with or without a sales order, and settling client money against their sales order debts. | `mail`, `account`, `sale`, `hr`, `base_setup`, **C** `cst_kerama_payment_summary`, **C** `cst_kerama_sale_receipt`, **C** `cst_kerama_payroll` | Has `post_init_hook`. |
| `cst_kerama_finance`<br>Khatdecor Finance — cash, bank and statements | 19.0.1.0.0 | Keeps the cash and bank configuration honest so the standard P&L, balance sheet and cash flow statement have a real basis. | `account`, **E** `account_bank_statement_import_csv` | Needs Enterprise `account_bank_statement_import_csv` (xlsx import). |
| `cst_kerama_journal_balance`<br>Khatdecor Journal Balance on the Overview | 19.0.1.0.0 | Show what is left in every bank, cash, sale and purchase journal on the Accounting Overview card. | `account` | Overrides `_get_journal_dashboard_data_batched` on the Accounting overview. |
| `cst_kerama_payroll`<br>Khatdecor Payroll & KPI | 19.0.1.2.0 | Employee salary, bonuses, fines and KPI — posted to the ledger. | `hr`, `account`, `sale`, `mrp`, **E** `mrp_workorder`, `stock` |  |
| `cst_kerama_hr_docs`<br>Khatdecor HR Documents | 19.0.1.0.0 | Kadr hujjatlarini xodim kartasidan Word (.docx) qilib yaratish. | `hr`, **C** `cst_kerama_payroll` | Needs `python-docx`. Word templates in `static/templates/`. |
| `zxs_internal_payment_transfer`<br>Internal Payment Transfer | 19.0.1.0.3 | Transfer funds between bank and cash journals with paired Send/Receive payments. | `account` | Third-party (Zarixsol) module **patched in place** (v19.0.1.0.3: paired payment in the destination journal's currency, FX difference to 441000/641000). Re-apply the fix if the vendor version is ever replaced. |

### Products

| Module | Version | What it does | Depends | Notes |
|---|---|---|---|---|
| `cst_kerama_product_display`<br>Khatdecor Product Names Without Codes | 19.0.1.1.0 | Show products by name and variant only - no internal reference in front of them. | `product` |  |
| `cst_kerama_product_search`<br>Khatdecor Product Search | 19.0.1.0.0 | Mahsulotni bir necha so'z bilan, xarakteristikasi bilan qidirish. | `product`, **C** `cst_kerama_variants` |  |
| `cst_kerama_product_price`<br>Khatdecor Product Price Update | 19.0.1.0.0 | Mass price update from the product list: Excel template download and upload matched on barcode, prices entered in USD, and bulk +/- adjustment by percent or amount. | `product` |  |

### Reports, dashboards, access

| Module | Version | What it does | Depends | Notes |
|---|---|---|---|---|
| `cst_kerama_reports`<br>Khatdecor Xisobotlar | 19.0.2.9.0 | One Xisobotlar app that gathers every report the company reads — Odoo's own where they exist, purpose-built where they do not. | `base`, `account`, **E** `account_reports`, **E** `accountant`, `product`, `product_margin`, `sale`, `sale_management`, `purchase`, `stock`, `stock_account`, `sale_stock`, **E** `stock_enterprise`, `mrp`, **E** `mrp_account_enterprise`, `uom`, `hr`, **C** `cst_kerama_payroll`, **C** `cst_kerama_dashboard`, **C** `cst_kerama_variants`, **E** `account_asset` | Needs Enterprise `account_reports`, `accountant`, `stock_enterprise`, `mrp_account_enterprise`, `account_asset`. XLSX routes under `/cst_reports/...`. |
| `cst_kerama_dashboard`<br>Kerama Dynamic Dashboard | 19.0.1.2.0 | Dynamic Sales / Accounting / Debts / Inventory dashboards for Kerama. | `sale`, `account`, `stock`, `uom`, **C** `cst_kerama_payment_summary` |  |
| `cst_kerama_roles`<br>Khatdecor Access Roles | 19.0.1.4.0 | The eleven Khatdecor job roles for the Access Roles app, with their group matrix and the payroll/accounting menus hidden. | **Cybro** `access_roles`, **C** `cst_kerama_kassa`, `base`, `mail`, `product`, `analytic`, `sales_team`, `sale_management`, `purchase`, `stock`, `mrp`, **E** `quality`, `account`, **E** `accountant`, `hr`, `hr_attendance`, `hr_expense`, `project`, `spreadsheet_dashboard`, **C** `cst_kerama_payroll`, **C** `cst_kerama_wh_control`, **C** `cst_kerama_dashboard`, **C** `cst_kerama_reports`, **C** `cst_kerama_shift`, **MuK** `muk_product` | Data for Cybrosys **access_roles**: 11 job roles. Payroll and Accounting menus are *hidden* for operational roles, not revoked. |

### Integrations

| Module | Version | What it does | Depends | Notes |
|---|---|---|---|---|
| `hikvision_attendance`<br>Hikvision Attendance Webhook (DS-K1T320) | 19.0.2.2.0 | Hikvision DS-K1T320 webhook → hr.attendance, plus a Telegram bot that pushes employee check-in/out events with photos to admins. | `hr_attendance`, `hr` | Device posts to `/hikvision/attendance` (HTTP Listening). Matches employee by `hr.employee.face_id`, then `barcode`. Device ID containing «Kirish» = check-in, «Chiqish» = check-out. Telegram notifications: params `hikvision_attendance.bot_token / bot_username / webhook_secret / bot_invite_token / odoo_base_url`, webhook `/hikvision_attendance/telegram/webhook`. |
| `cst_kerama_telegram`<br>Khatdecor Telegram Bot | 19.0.1.1.0 | Customers and suppliers read their own balance and reconciliation statement in Telegram; the company can message them back. | `base`, `contacts`, `account`, **E** `account_reports`, `mail` | Bot lives inside Odoo: route `POST /telegram/webhook`. Params `cst_kerama_telegram.bot_token`, `cst_kerama_telegram.webhook_secret`. Requires `dbfilter` in odoo.conf (public route) and an HTTPS `web.base.url` with `web.base.url.freeze = True`. |
| `moizvonki_calls`<br>Moizvonki Calls History | 19.0.1.0.0 | Calls history + recordings from Moizvonki (REST + Webhook) | `base`, `web`, `hr` | Ported from 18.0 (CRM part removed). Params `moizvonki.domain / user_name / api_key / webhook_secret`; webhook `/moizvonki/webhook`. |
| `cst_kerama_ai_voice`<br>Khatdecor AI Voice Input | 19.0.1.0.0 | Speak to the MuK AI assistant: a microphone in the chat composer that turns Uzbek, Russian or English speech into text. | **MuK** `muk_ai`, `base_setup` | Needs an **OpenAI key in the MuK AI provider** (muk_ai). Model `gpt-4o-transcribe` (system param `cst_kerama_ai_voice.model`); `whisper-1` does not understand Uzbek. Route `/cst_ai_voice/transcribe`. |

### UI

| Module | Version | What it does | Depends | Notes |
|---|---|---|---|---|
| `cst_kerama_appsbar`<br>Khatdecor AppsBar Toggle | 19.0.1.0.0 | Collapse / expand the MuK apps sidebar to icons only. | **MuK** `muk_web_appsbar` | Patch for MuK **muk_web_appsbar** (collapse to icons). |
| `chatter_toggle`<br>Chatter Toggle | 19.0.1.0.0 | Toggle button to show/hide the Chatter panel in all form views | `mail` |  |

### Not installed

| Module | Version | What it does | Depends | Notes |
|---|---|---|---|---|
| `cst_kerama_tile_m2`<br>Kerama Tile m² (Kafel) | 19.0.1.0.0 | Compute a tile's surface area from its height and width and sell tiles by m². | `product`, `uom`, `sale` | **Not installed** (removed 2026-08-19). Uninstalling it once cascaded into dashboard/project — they no longer depend on it. |
| `cst_direct_login_pos`<br>POS Direct Screen Login | 19.0.1.0.0 | Allow users to log in directly to the POS screen without accessing the backend. | `point_of_sale` | **Not installed.** |
| `cst_pos_custom_login_background`<br>POS Custom Login Background | 19.0.1.0.0 | Set custom background image for POS login screen from settings | `point_of_sale` | **Not installed.** |
| `cst_show_pos_product_price`<br>POS Show Product Price / Display Price on POS Product Cards | 19.0.1.0.0 | Show product prices directly on the POS product grid for better visibility and faster selection. | `point_of_sale` | **Not installed.** |

## Integrations: configuration

Secrets are **not** in this repo — they live in *Settings → Technical → System Parameters* on the database.

| Integration | Module | System parameters | Endpoint (HTTPS, public) |
|---|---|---|---|
| Hikvision Face ID terminals | `hikvision_attendance` | `hikvision_attendance.*` (bot_token, bot_username, webhook_secret, bot_invite_token, odoo_base_url) | `/hikvision/attendance`, `/hikvision_attendance/telegram/webhook` |
| Telegram customer bot | `cst_kerama_telegram` | `cst_kerama_telegram.bot_token`, `cst_kerama_telegram.webhook_secret` | `/telegram/webhook` |
| Moizvonki telephony | `moizvonki_calls` | `moizvonki.domain`, `moizvonki.user_name`, `moizvonki.api_key`, `moizvonki.webhook_secret` | `/moizvonki/webhook` |
| OpenAI (AI chat + voice) | `muk_ai`, `cst_kerama_ai_voice` | provider key in MuK AI; `cst_kerama_ai_voice.model`, `.prompt` | `/cst_ai_voice/transcribe` |

Public routes need `dbfilter` set in `odoo.conf`, and `web.base.url` must be the HTTPS domain with `web.base.url.freeze = True`.

## Install / upgrade

```bash
systemctl stop odoo
cd /opt/kerama && sudo -u odoo venv/bin/python3 addons/community/odoo-bin \
  -c server/conf/odoo.conf -d kerama -u <module> --stop-after-init --no-http   # -i to install
systemctl start odoo
```

JS/SCSS/QWeb-only or Python-only changes (no new fields/views) need just `systemctl restart odoo`. On a test copy of the database always pass `--db-filter='^<copy>$'`, otherwise the `^kerama$` filter hides it.

