import io
import json

from odoo import http
from odoo.http import content_disposition, request

COLUMNS = {
    "product": [("name", "Mahsulot"), ("char", "Xarakteristika"), ("code", "Kod"), ("uom", "Birlik")],
    "partner": [("name", "Mijoz")],
    "user": [("name", "Sotuvchi")],
    "category": [("name", "Kategoriya")],
}
FIGURES = [
    # (key, title, kind) — kind: int / qty / money / pct
    ("docs", "Hujjatlar", "int"), ("qty", "Miqdor", "qty"), ("price", "O'rtacha narx", "money"),
    ("unit_cost", "Tannarx (dona)", "money"), ("amount", "Summa", "money"), ("cost", "Tannarx summasi", "money"),
    ("ret_docs", "Hujjatlar", "int"), ("ret_qty", "Miqdor", "qty"), ("ret_price", "Narx", "money"),
    ("ret_amount", "Summa", "money"), ("ret_cost", "Tannarx summasi", "money"),
    ("markup", "Ustama %", "pct"), ("margin", "Marja %", "pct"), ("profit", "Foyda", "money"),
]
BANDS = [("Sotuv", 6), ("Qaytarish (vozvrat)", 5), ("Foydalilik", 3)]


class ProfitabilityController(http.Controller):
    """Excel twin of the «Mahsulot foyda/zarari» screen, same filters."""

    @http.route("/cst_reports/profitability/xlsx", type="http", auth="user", methods=["GET"])
    def profitability_xlsx(self, options="{}", **kwargs):
        engine = request.env["cst.profitability.report"]
        data = engine.get_data(json.loads(options))
        content = self._build(data)
        filename = "foyda_%s_%s.xlsx" % (data["date_from"], data["date_to"])
        return request.make_response(content, headers=[
            ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("Content-Disposition", content_disposition(filename)),
        ])

    def _build(self, data):
        import xlsxwriter
        buf = io.BytesIO()
        book = xlsxwriter.Workbook(buf, {"in_memory": True})
        sheet = book.add_worksheet("Foyda")
        title = book.add_format({"bold": True, "font_size": 14})
        band = book.add_format({"bold": True, "align": "center", "bg_color": "#E8EEF5", "border": 1})
        head = book.add_format({"bold": True, "text_wrap": True, "valign": "vcenter", "bg_color": "#F4F6F9",
                                "border": 1})
        fmt = {
            "int": book.add_format({"num_format": "0", "border": 1}),
            "qty": book.add_format({"num_format": "#,##0.###", "border": 1}),
            "money": book.add_format({"num_format": "#,##0.00", "border": 1}),
            "pct": book.add_format({"num_format": "0.00\"%\"", "border": 1}),
            "text": book.add_format({"border": 1}),
        }
        tot = {k: book.add_format(dict(f, bold=True, top=2)) for k, f in (
            ("int", {"num_format": "0"}), ("qty", {"num_format": "#,##0.###"}),
            ("money", {"num_format": "#,##0.00"}), ("pct", {"num_format": "0.00\"%\""}), ("text", {}))}
        labels = COLUMNS[data["group_by"]]
        sheet.write(0, 0, "Foydalilik: %s — %s (%s)" % (data["date_from"], data["date_to"], data["currency"]), title)
        col = len(labels)
        for name, span in BANDS:
            sheet.merge_range(2, col, 2, col + span - 1, name, band)
            col += span
        for c, (_key, label) in enumerate(labels):
            sheet.write(3, c, label, head)
            sheet.set_column(c, c, 40 if c == 0 else 14)
        for i, (_key, label, _kind) in enumerate(FIGURES):
            sheet.write(3, len(labels) + i, label, head)
            sheet.set_column(len(labels) + i, len(labels) + i, 14)
        row = 4
        for rec in data["rows"]:
            for c, (key, _label) in enumerate(labels):
                sheet.write(row, c, rec.get(key) or "", fmt["text"])
            for i, (key, _label, kind) in enumerate(FIGURES):
                value = rec.get(key)
                sheet.write(row, len(labels) + i, value if value is not None else "", fmt[kind])
            row += 1
        sheet.write(row, 0, "Jami", tot["text"])
        for c in range(1, len(labels)):
            sheet.write(row, c, "", tot["text"])
        for i, (key, _label, kind) in enumerate(FIGURES):
            value = data["total"].get(key)
            if key in ("price", "unit_cost", "ret_price"):
                value = None  # an average over different products means nothing
            sheet.write(row, len(labels) + i, value if value is not None else "", tot[kind])
        sheet.freeze_panes(4, 1)
        book.close()
        return buf.getvalue()
