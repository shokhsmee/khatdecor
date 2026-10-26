import base64
import csv
import io
import logging
from decimal import Decimal, InvalidOperation

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round
from odoo.tools.misc import format_amount

_logger = logging.getLogger(__name__)

# Header labels accepted for the two columns we actually read back.  Matching is
# done on a normalised (lower-case, letters only) form so "Shtrix-kod",
# "SHTRIX KOD" and "Штрих-код" all resolve to the same column.
_BARCODE_ALIASES = ("shtrixkod", "shtrix", "barcode", "kod", "shtrixkodi",
                    "shtrihkod", "штрихкод", "штрих", "код")
_NEW_PRICE_ALIASES = ("yanginarx", "yangi", "yanginarxi", "newprice", "new",
                      "новаяцена", "нов", "цена")
_CURRENCY_ALIASES = ("valyuta", "валюта", "currency")
# What people write in the currency column.
_CURRENCY_WORDS = {"som": "UZS", "сум": "UZS", "сўм": "UZS", "so'm": "UZS", "sum": "UZS", "uzs": "UZS",
                   "dollar": "USD", "доллар": "USD", "$": "USD", "usd": "USD"}
# Rows scanned while looking for the header line.
_HEADER_SCAN_ROWS = 10
# How many offending products / rows an error or report message names.
_REPORT_LIMIT = 15


def _normalise_header(value):
    """Return *value* reduced to its lower-case letters and digits."""
    if value is None:
        return ""
    return "".join(c for c in str(value).strip().lower() if c.isalnum())


def _normalise_barcode(value):
    """Return *value* as the plain string a barcode is stored as.

    Spreadsheets happily turn a numeric barcode into a float
    (``4780012345678.0``) or into scientific notation (``4.78001e+12``); both
    are brought back to their integer form so they match what is in Odoo.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if not text:
        return ""
    if "e" in text.lower() or text.endswith(".0"):
        try:
            number = Decimal(text)
        except InvalidOperation:
            return text
        if number == number.to_integral_value():
            return str(int(number))
    return text


def _normalise_number(value):
    """Return *value* as a float, or ``None`` when it is not a number.

    Accepts what people actually type: ``1 234 567,89``, ``1,234,567.89``,
    ``503625`` and empty cells.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        # Whichever separator comes last is the decimal one.
        if text.rindex(".") > text.rindex(","):
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


class ProductPriceUpdate(models.TransientModel):
    _name = "cst.product.price.update"
    _description = "Maxsulot narxlarini yangilash"

    state = fields.Selection(
        [("draft", "Draft"), ("preview", "Preview"), ("done", "Done")],
        default="draft",
    )

    company_id = fields.Many2one(
        "res.company",
        string="Kompaniya",
        required=True,
        default=lambda self: self.env.company,
        help="Tannarx shu kompaniya uchun yangilanadi (tannarx har bir "
             "kompaniyada alohida saqlanadi). Sotish narxi barcha "
             "kompaniyalar uchun umumiy.",
    )
    company_currency_id = fields.Many2one(
        related="company_id.currency_id", string="Kompaniya valyutasi"
    )

    product_ids = fields.Many2many(
        "product.product",
        string="Mahsulotlar",
        domain="[('active', '=', True)]",
        help="Shablonga chiqadigan va ommaviy o'zgartirish qo'llanadigan "
             "mahsulotlar.",
    )
    product_count = fields.Integer(compute="_compute_product_count")

    target = fields.Selection(
        [("price", "Sotish narxi"), ("cost", "Tannarx")],
        string="Qaysi narx",
        default="price",
        required=True,
    )
    categ_ids = fields.Many2many(
        "product.category", string="Mahsulot guruhlari",
        help="Guruh tanlansa, shu guruh (va ichki guruhlari)dagi barcha sotiladigan mahsulotlar har bir "
             "xarakteristikasi bilan alohida qator bo'lib chiqadi.")
    currency_id = fields.Many2one(
        "res.currency", string="Valyuta", required=True,
        default=lambda self: self.env.company.currency_id,
        domain="[('active', '=', True)]",
        help="Narxlar shu valyutada kiritiladi. Sotish narxi xarakteristikaga shu valyutada yoziladi; "
             "tannarx kurs bo'yicha kompaniya valyutasiga aylantiriladi.")
    rate_date = fields.Date(
        string="Kurs sanasi",
        default=fields.Date.context_today,
    )
    rate = fields.Float(
        string="Kurs",
        digits=(16, 6),
        help="1 kompaniya valyutasi (dollar) necha tanlangan valyutaga teng — so'm uchun kunning dollar kursi. "
             "Tizim kursidan olinadi, qo'lda o'zgartirish mumkin.",
    )
    is_company_currency = fields.Boolean(compute="_compute_is_company_currency")

    # --- Excel ---------------------------------------------------------
    template_file = fields.Binary(string="Shablon", readonly=True, attachment=False)
    template_filename = fields.Char(readonly=True)
    upload_file = fields.Binary(string="Excel fayl")
    upload_filename = fields.Char()

    # --- Bulk adjustment ------------------------------------------------
    adjust_type = fields.Selection(
        [("percent", "Foiz (%)"), ("amount", "Summa")],
        string="O'zgartirish turi",
        default="percent",
        required=True,
    )
    adjust_sign = fields.Selection(
        [("add", "Qo'shish (+)"), ("subtract", "Ayirish (-)")],
        string="Amal",
        default="add",
        required=True,
    )
    adjust_value = fields.Float(string="Qiymat", digits=(16, 2))
    adjust_unit = fields.Char(compute="_compute_adjust_unit")
    line_ids = fields.One2many(
        "cst.product.price.update.line", "wizard_id", string="Ko'rish", readonly=True
    )

    result_html = fields.Html(string="Natija", readonly=True, sanitize=False)

    # ------------------------------------------------------------------
    # Defaults / computes
    # ------------------------------------------------------------------
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "product_ids" in fields_list and not res.get("product_ids"):
            products = self._products_from_context()
            if products:
                res["product_ids"] = [Command.set(products.ids)]
        if "rate" in fields_list and not res.get("rate"):
            company = self.env["res.company"].browse(res.get("company_id")) or self.env.company
            currency = self.env["res.currency"].browse(res.get("currency_id")) or company.currency_id
            res["rate"] = self._get_rate(company, currency, res.get("rate_date"))
        return res

    @api.model
    def _products_from_context(self):
        """Return the products the action was launched on."""
        ctx = self.env.context
        active_ids = ctx.get("active_ids") or (
            [ctx["active_id"]] if ctx.get("active_id") else []
        )
        if not active_ids:
            return self.env["product.product"]
        active_model = ctx.get("active_model")
        if active_model == "product.template":
            return self.env["product.template"].browse(active_ids).product_variant_ids
        if active_model == "product.product":
            return self.env["product.product"].browse(active_ids)
        return self.env["product.product"]

    @api.model
    def _get_rate(self, company, currency, date=None):
        """How much ``currency`` one unit of the company currency is worth."""
        company = company or self.env.company
        if not currency or currency == company.currency_id:
            return 1.0
        return self.env["res.currency"]._get_conversion_rate(
            company.currency_id, currency, company, date or fields.Date.context_today(self))

    @api.depends("currency_id", "company_currency_id")
    def _compute_is_company_currency(self):
        for wizard in self:
            wizard.is_company_currency = wizard.currency_id == wizard.company_currency_id

    def _products(self):
        """What the sheet and the bulk change cover: the picked products plus
        every saleable variant of the picked groups."""
        self.ensure_one()
        products = self.product_ids
        if self.categ_ids:
            products |= self.env["product.product"].search([
                ("categ_id", "child_of", self.categ_ids.ids), ("sale_ok", "=", True)])
        return products

    @api.depends("product_ids", "categ_ids")
    def _compute_product_count(self):
        for wizard in self:
            wizard.product_count = len(wizard._products())

    @api.depends("adjust_type", "currency_id", "company_currency_id")
    def _compute_adjust_unit(self):
        """The unit shown next to the bulk change value."""
        for wizard in self:
            if wizard.adjust_type == "percent":
                wizard.adjust_unit = "%"
            else:
                currency = wizard._entry_currency()
                wizard.adjust_unit = currency.name if currency else ""

    @api.onchange("rate_date", "company_id", "currency_id")
    def _onchange_rate_date(self):
        for wizard in self:
            wizard.rate = wizard._get_rate(wizard.company_id, wizard.currency_id, wizard.rate_date)

    @api.onchange("target", "currency_id", "adjust_type", "adjust_sign",
                  "adjust_value", "rate", "product_ids", "categ_ids")
    def _onchange_reset_preview(self):
        """A changed setting invalidates the preview that was computed for it."""
        for wizard in self:
            if wizard.line_ids:
                wizard.line_ids = [Command.clear()]
            if wizard.state != "draft":
                wizard.state = "draft"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _price_digits(self):
        return self.env["decimal.precision"].precision_get("Product Price")

    def _check_rate(self):
        """Refuse to convert with a rate that would zero every price out."""
        self.ensure_one()
        if float_compare(self.rate, 0.0, precision_digits=6) <= 0:
            raise UserError(_("Kursni kiriting - kurs noldan katta bo'lishi kerak."))

    def _to_company_currency(self, amount, currency=None):
        """Convert *amount*, typed in *currency* (default: the wizard's), into company currency."""
        self.ensure_one()
        if amount is None:
            return None
        currency = currency or self.currency_id
        if currency != self.company_currency_id:
            if currency == self.currency_id:
                amount /= self.rate
            else:
                amount = currency._convert(amount, self.company_currency_id, self.company_id,
                                           self.rate_date or fields.Date.context_today(self), round=False)
        return float_round(amount, precision_digits=self._price_digits())

    def _from_company_currency(self, amount):
        """Convert a company-currency *amount* into the wizard's currency."""
        self.ensure_one()
        if self.currency_id != self.company_currency_id:
            amount *= self.rate
        return float_round(amount, precision_digits=self._price_digits())

    def _entry_currency(self):
        """The currency the user types figures in."""
        self.ensure_one()
        return self.currency_id or self.company_currency_id

    def _current_price(self, product, currency=None):
        """The targeted price of *product*, in *currency* (default: the wizard's)."""
        self.ensure_one()
        currency = currency or self.currency_id
        if self.target == "price":
            own = product.cst_sale_currency_id or product.currency_id
            if product.cst_sale_price and own == currency:
                return product.cst_sale_price
            value = product.lst_price
        else:
            value = product.with_company(self.company_id).standard_price
        if currency == self.company_currency_id:
            return value
        if currency == self.currency_id:
            return self._from_company_currency(value)
        return self.company_currency_id._convert(value, currency, self.company_id,
                                                 self.rate_date or fields.Date.context_today(self))

    def _write_price(self, product, value, currency=None):
        """Write *value* (in *currency*, default the wizard's) into the targeted price.

        Sales price: a product of a single variant priced in the company
        currency keeps Odoo's own sales price; otherwise the price goes on the
        variant -- its characteristic -- in the currency it was given in.
        """
        self.ensure_one()
        currency = currency or self.currency_id
        if self.target == "price":
            single = product.product_tmpl_id.product_variant_count <= 1
            if single and currency == self.company_currency_id:
                product.write({"cst_sale_price": 0.0, "cst_sale_currency_id": False})
                product.lst_price = value
            else:
                product.write({"cst_sale_price": value, "cst_sale_currency_id": currency.id})
        else:
            # standard_price is company dependent and kept in company currency.
            product.with_company(self.company_id).standard_price = self._to_company_currency(value, currency)

    def _target_label(self):
        self.ensure_one()
        return dict(self._fields["target"]._description_selection(self.env))[self.target]

    def _reload(self):
        """Reopen the wizard so the result stays on screen."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Maxsulot narxlarini yangilash"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": dict(self.env.context),
        }

    # ------------------------------------------------------------------
    # Excel template
    # ------------------------------------------------------------------
    def action_download_template(self):
        """Export the products to an xlsx price sheet, one row per
        characteristic, grouped under their product group."""
        self.ensure_one()
        products = self._products()
        if not products:
            raise UserError(_("Shablon uchun mahsulot yoki mahsulot guruhini tanlang."))
        self._check_rate()
        try:
            import xlsxwriter  # noqa: PLC0415
        except ImportError as exc:
            raise UserError(
                _("Excel shablonini yaratish uchun 'xlsxwriter' kutubxonasi kerak.")
            ) from exc

        currency = self._entry_currency()
        ccy_name = currency.name if currency else ""
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet(self._target_label()[:31])

        header_fmt = workbook.add_format({
            "bold": True, "bg_color": "#714B67", "font_color": "#FFFFFF",
            "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True,
        })
        group_fmt = workbook.add_format({"bold": True, "bg_color": "#FFE699", "border": 1})
        text_fmt = workbook.add_format({"border": 1})
        locked_fmt = workbook.add_format({"border": 1, "bg_color": "#F5F5F5"})
        money_fmt = workbook.add_format({
            "border": 1, "bg_color": "#F5F5F5", "num_format": "#,##0.00",
        })
        input_fmt = workbook.add_format({
            "border": 1, "bg_color": "#FFF9E6", "num_format": "#,##0.00",
        })
        input_text_fmt = workbook.add_format({"border": 1, "bg_color": "#FFF9E6", "align": "center"})

        headers = [
            ("Shtrix-kod", 18),
            ("Mahsulot", 45),
            ("Xarakteristika", 26),
            ("Birlik", 10),
            ("Valyuta", 10),
            ("Joriy narx", 16),
            ("Yangi narx", 16),
        ]
        for col, (label, width) in enumerate(headers):
            sheet.set_column(col, col, width)
            sheet.write(0, col, label, header_fmt)
        sheet.freeze_panes(1, 0)

        def sort_key(product):
            return (product.categ_id.complete_name or "", product.product_tmpl_id.name or "",
                    product.cst_characteristic or "", product.id)

        row = 1
        group = None
        for product in products.sorted(sort_key):
            if product.categ_id != group:
                group = product.categ_id
                # a group line: no barcode, no price -- the upload skips it
                sheet.write_blank(row, 0, None, group_fmt)
                sheet.merge_range(row, 1, row, len(headers) - 1,
                                  group.complete_name or _("Kategoriyasiz"), group_fmt)
                row += 1
            own = product.cst_sale_currency_id if (self.target == "price" and product.cst_sale_price) else False
            row_currency = own or currency
            price = self._current_price(product, row_currency)
            # Barcode as text so long numbers keep every digit.
            sheet.write_string(row, 0, product.barcode or "", text_fmt)
            sheet.write_string(row, 1, product.product_tmpl_id.name or "", locked_fmt)
            sheet.write_string(row, 2, product.cst_characteristic or "", locked_fmt)
            sheet.write_string(row, 3, product.uom_id.name or "", locked_fmt)
            sheet.write_string(row, 4, row_currency.name or ccy_name, input_text_fmt)
            sheet.write_number(row, 5, price, money_fmt)
            sheet.write_number(row, 6, price, input_fmt)
            row += 1
        sheet.autofilter(0, 0, row - 1, len(headers) - 1)

        workbook.close()
        content = output.getvalue()
        output.close()

        filename = "narxlar_%s_%s.xlsx" % (
            "tannarx" if self.target == "cost" else "sotish_narxi",
            fields.Date.context_today(self).strftime("%Y%m%d"),
        )
        self.write({
            "template_file": base64.b64encode(content),
            "template_filename": filename,
        })
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s/%s/template_file/%s?download=true"
                   % (self._name, self.id, filename),
            "target": "self",
        }

    # ------------------------------------------------------------------
    # Excel upload
    # ------------------------------------------------------------------
    def action_upload_prices(self):
        """Read the uploaded sheet and write the prices it holds."""
        self.ensure_one()
        if not self.upload_file:
            raise UserError(_("Avval Excel faylni tanlang."))
        self._check_rate()

        rows = self._read_uploaded_rows()
        barcode_col, price_col, currency_col = self._locate_columns(rows)
        digits = self._price_digits()

        updates = {}          # barcode -> (row number, new price, currency)
        skipped = []          # human readable reasons
        seen = {}

        for row_number, row in rows:
            barcode = _normalise_barcode(
                row[barcode_col] if barcode_col < len(row) else None
            )
            raw_price = row[price_col] if price_col < len(row) else None
            if not barcode:
                if _normalise_number(raw_price) is not None:
                    skipped.append(_("%(row)s-satr: shtrix-kod ko'rsatilmagan.",
                                     row=row_number))
                continue
            if barcode in seen:
                skipped.append(_(
                    "%(row)s-satr: shtrix-kod \"%(barcode)s\" %(first)s-satrda "
                    "allaqachon bor, e'tiborga olinmadi.",
                    row=row_number, barcode=barcode, first=seen[barcode],
                ))
                continue
            price = _normalise_number(raw_price)
            if price is None:
                skipped.append(_(
                    "%(row)s-satr (%(barcode)s): yangi narx bo'sh yoki son emas.",
                    row=row_number, barcode=barcode,
                ))
                continue
            if float_compare(price, 0.0, precision_digits=digits) < 0:
                skipped.append(_(
                    "%(row)s-satr (%(barcode)s): narx manfiy bo'lishi mumkin emas.",
                    row=row_number, barcode=barcode,
                ))
                continue
            row_currency = self.currency_id
            if currency_col is not None and currency_col < len(row) and row[currency_col] not in (None, ""):
                row_currency = self._parse_currency(row[currency_col])
                if not row_currency:
                    skipped.append(_(
                        "%(row)s-satr (%(barcode)s): valyuta \"%(value)s\" tanilmadi (USD yoki UZS yozing).",
                        row=row_number, barcode=barcode, value=row[currency_col]))
                    continue
            seen[barcode] = row_number
            updates[barcode] = (row_number, float_round(price, precision_digits=digits), row_currency)

        if not updates:
            raise UserError(
                _("Faylda yangilash uchun yaroqli satr topilmadi.\n\n%s")
                % "\n".join(skipped[:_REPORT_LIMIT])
            )

        products = self.env["product.product"].search(
            [("barcode", "in", list(updates))]
        )
        by_barcode = {p.barcode: p for p in products}

        updated = self.env["product.product"]
        unchanged = 0
        for barcode, (row_number, new_price, row_currency) in updates.items():
            product = by_barcode.get(barcode)
            if not product:
                skipped.append(_(
                    "%(row)s-satr: shtrix-kod \"%(barcode)s\" bo'yicha mahsulot "
                    "topilmadi.", row=row_number, barcode=barcode,
                ))
                continue
            if float_compare(self._current_price(product, row_currency), new_price,
                             precision_digits=digits) == 0 and (
                    self.target != "price" or not product.cst_sale_price
                    or product.cst_sale_currency_id == row_currency):
                unchanged += 1
                continue
            self._write_price(product, new_price, row_currency)
            updated |= product

        self._store_result(
            updated_count=len(updated),
            unchanged=unchanged,
            skipped=skipped,
            source=_("Excel fayl: %s", self.upload_filename or ""),
        )
        return self._reload()

    def _read_uploaded_rows(self):
        """Return ``[(row number, [cell, ...]), ...]`` from the uploaded file."""
        self.ensure_one()
        data = base64.b64decode(self.upload_file)
        name = (self.upload_filename or "").lower()

        if name.endswith(".csv") or name.endswith(".txt"):
            return self._read_csv_rows(data)
        if name and not name.endswith((".xlsx", ".xlsm")):
            raise UserError(_(
                "Faqat .xlsx va .csv fayllar qabul qilinadi. Eski .xls faylni "
                "Excelda \"Excel Workbook (.xlsx)\" sifatida saqlab, qayta "
                "yuklang."
            ))
        try:
            from openpyxl import load_workbook  # noqa: PLC0415
        except ImportError as exc:
            raise UserError(
                _("Excel faylni o'qish uchun 'openpyxl' kutubxonasi kerak.")
            ) from exc
        try:
            workbook = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        except Exception as exc:
            _logger.warning("Could not read the uploaded price sheet: %s", exc)
            raise UserError(_(
                "Faylni o'qib bo'lmadi. Uni .xlsx formatida saqlanganiga "
                "ishonch hosil qiling."
            )) from exc
        sheet = workbook[workbook.sheetnames[0]]
        rows = [
            (number, list(row))
            for number, row in enumerate(sheet.iter_rows(values_only=True), start=1)
        ]
        workbook.close()
        return rows

    def _read_csv_rows(self, data):
        for encoding in ("utf-8-sig", "utf-8", "cp1251"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise UserError(_("CSV faylning kodlashini aniqlab bo'lmadi."))
        sample = text[:4096]
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        return [(number, row) for number, row in enumerate(reader, start=1)]

    def _locate_columns(self, rows):
        """Find the barcode, new-price and (optional) currency columns from the
        header row.

        Falls back to the template layout (first column / last column) when no
        recognisable header is present, so a stripped-down file still imports.
        """
        for index, (_number, row) in enumerate(rows[:_HEADER_SCAN_ROWS]):
            barcode_col = price_col = currency_col = None
            for col, cell in enumerate(row):
                header = _normalise_header(cell)
                if not header:
                    continue
                if barcode_col is None and header.startswith(_BARCODE_ALIASES):
                    barcode_col = col
                elif currency_col is None and header.startswith(_CURRENCY_ALIASES):
                    currency_col = col
                elif header.startswith(_NEW_PRICE_ALIASES):
                    # «Joriy narx» / «Цена» come first; «Yangi narx» wins over a bare «narx»
                    if price_col is None or header.startswith(("yangi", "нов", "new")):
                        price_col = col
            if barcode_col is not None and price_col is not None:
                del rows[: index + 1]
                return barcode_col, price_col, currency_col

        width = max((len(row) for _number, row in rows), default=0)
        if width < 2:
            raise UserError(_(
                "Faylda \"Shtrix-kod\" va \"Yangi narx\" ustunlari topilmadi. "
                "Shablonni yuklab olib, undan foydalaning."
            ))
        # Drop a header-looking first row so it is not read as data.
        if rows and _normalise_barcode(rows[0][1][0]) and not any(
            _normalise_number(cell) is not None for cell in rows[0][1][1:]
        ):
            del rows[0]
        return 0, width - 1, None

    def _parse_currency(self, value):
        """«USD», «so'm», «$», «UZS» → a currency, or an empty recordset."""
        text = str(value).strip()
        key = _CURRENCY_WORDS.get(text.lower(), text.upper())
        # exact name: a plain search on res.currency matched «EURX» to EUR here
        return self.env["res.currency"].search([("name", "=", key)]).filtered(lambda c: c.name == key)[:1]

    # ------------------------------------------------------------------
    # Bulk adjustment
    # ------------------------------------------------------------------
    def _adjusted_price(self, current):
        """Return *current* (company currency) after the configured change."""
        self.ensure_one()
        sign = -1.0 if self.adjust_sign == "subtract" else 1.0
        if self.adjust_type == "percent":
            new_price = current * (1.0 + sign * self.adjust_value / 100.0)
        else:
            new_price = current + sign * self.adjust_value
        return float_round(new_price, precision_digits=self._price_digits())

    def _prepare_adjustment(self):
        """Validate the settings and return ``[(product, new price), ...]``."""
        self.ensure_one()
        if not self._products():
            raise UserError(_("Kamida bitta mahsulot yoki mahsulot guruhini tanlang."))
        if float_compare(self.adjust_value, 0.0, precision_digits=6) <= 0:
            raise UserError(_("O'zgartirish qiymatini kiriting (noldan katta)."))
        if self.adjust_type == "percent" and self.adjust_sign == "subtract" \
                and float_compare(self.adjust_value, 100.0, precision_digits=2) > 0:
            raise UserError(_("Foiz 100 dan katta bo'lishi mumkin emas."))
        self._check_rate()

        digits = self._price_digits()
        changes = []
        negative = []
        for product in self._products():
            current = self._current_price(product)
            new_price = self._adjusted_price(current)
            if float_compare(new_price, 0.0, precision_digits=digits) < 0:
                negative.append(product.display_name)
                continue
            changes.append((product, current, new_price))
        if negative:
            raise UserError(_(
                "Bu o'zgartirish quyidagi mahsulotlarning narxini manfiy "
                "qiladi:\n\n%(products)s\n\nQiymatni kamaytiring yoki bu "
                "mahsulotlarni ro'yxatdan chiqaring.",
                products="\n".join("- %s" % name for name in negative[:_REPORT_LIMIT]),
            ))
        return changes

    def action_preview_adjustment(self):
        """Show what the bulk change would do, without writing anything."""
        self.ensure_one()
        changes = self._prepare_adjustment()
        self.line_ids = [Command.clear()] + [
            Command.create({
                "product_id": product.id,
                "current_price": current,
                "new_price": new_price,
            })
            for product, current, new_price in changes
        ]
        self.state = "preview"
        return self._reload()

    def action_apply_adjustment(self):
        """Write the bulk change on every selected product."""
        self.ensure_one()
        changes = self._prepare_adjustment()
        digits = self._price_digits()
        updated = 0
        unchanged = 0
        for product, current, new_price in changes:
            if float_compare(current, new_price, precision_digits=digits) == 0:
                unchanged += 1
                continue
            self._write_price(product, new_price)
            updated += 1

        sign = "+" if self.adjust_sign == "add" else "-"
        if self.adjust_type == "percent":
            change = "%s%g%%" % (sign, self.adjust_value)
        else:
            change = "%s%s" % (sign, format_amount(
                self.env, self.adjust_value, self._entry_currency()
            ))
        self._store_result(
            updated_count=updated,
            unchanged=unchanged,
            skipped=[],
            source=_("Ommaviy o'zgartirish: %s", change),
        )
        return self._reload()

    # ------------------------------------------------------------------
    # Result report
    # ------------------------------------------------------------------
    def _store_result(self, updated_count, unchanged, skipped, source):
        self.ensure_one()
        currency = self._entry_currency()
        parts = [
            "<p><b>%s</b> - %s" % (self._target_label(), source),
        ]
        if currency != self.company_currency_id:
            parts.append(_(
                "<br/>Valyuta: %(ccy)s, kurs: 1 %(company)s = %(rate)s",
                ccy=currency.name, company=self.company_currency_id.name,
                rate=format_amount(self.env, self.rate, currency),
            ))
        parts.append("</p>")
        parts.append("<ul>")
        parts.append(_("<li>Yangilandi: <b>%s</b> mahsulot</li>", updated_count))
        if unchanged:
            parts.append(_("<li>O'zgarmadi (narx bir xil): %s</li>", unchanged))
        if skipped:
            parts.append(_("<li>O'tkazib yuborildi: <b>%s</b> satr</li>",
                           len(skipped)))
        parts.append("</ul>")
        if skipped:
            shown = skipped[:_REPORT_LIMIT]
            parts.append("<ul>")
            parts.extend("<li>%s</li>" % reason for reason in shown)
            if len(skipped) > len(shown):
                parts.append(_("<li>... va yana %s satr</li>",
                               len(skipped) - len(shown)))
            parts.append("</ul>")
        self.write({
            "result_html": "".join(parts),
            "state": "done",
            "line_ids": [Command.clear()],
        })

    def action_close(self):
        return {"type": "ir.actions.act_window_close"}

    def action_back(self):
        """Return to the settings after a run, keeping the selection."""
        self.ensure_one()
        self.write({"state": "draft", "result_html": False, "upload_file": False,
                    "upload_filename": False})
        return self._reload()


class ProductPriceUpdateLine(models.TransientModel):
    _name = "cst.product.price.update.line"
    _description = "Narx o'zgarishini ko'rish"
    _rec_name = "product_id"

    wizard_id = fields.Many2one(
        "cst.product.price.update", required=True, ondelete="cascade", index=True
    )
    product_id = fields.Many2one("product.product", string="Mahsulot", required=True)
    barcode = fields.Char(related="product_id.barcode", string="Shtrix-kod")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    cst_characteristic = fields.Char(related="product_id.cst_characteristic", string="Xarakteristika")
    current_price = fields.Monetary(string="Joriy narx", currency_field="currency_id")
    new_price = fields.Monetary(string="Yangi narx", currency_field="currency_id")
    difference = fields.Monetary(
        string="O'zgarish", currency_field="currency_id",
        compute="_compute_difference",
    )

    @api.depends("current_price", "new_price")
    def _compute_difference(self):
        for line in self:
            line.difference = line.new_price - line.current_price
