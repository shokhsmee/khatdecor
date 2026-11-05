import io
import json

from odoo import http
from odoo.http import content_disposition, request

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class FinanceSheetsController(http.Controller):
    """Excel twins of «Foyda va zarar» and «Balans» (Excel shakli), same options."""

    @http.route("/cst_reports/pl_sheet/xlsx", type="http", auth="user", methods=["GET"])
    def pl_sheet_xlsx(self, options="{}", detail="1", **kwargs):
        data = request.env["cst.pl.sheet"].get_data(json.loads(options))
        content = self._build_pl(data, detail == "1")
        return self._send(content, "foyda_zarar_%s_%s.xlsx" % (data["date_from"], data["date_to"]))

    @http.route("/cst_reports/balance_sheet/xlsx", type="http", auth="user", methods=["GET"])
    def balance_sheet_xlsx(self, options="{}", detail="0", **kwargs):
        data = request.env["cst.balance.sheet"].get_data(json.loads(options))
        content = self._build_balance(data, detail == "1")
        return self._send(content, "balans_%s_%s.xlsx" % (data["date_from"], data["date_to"]))

    def _send(self, content, filename):
        return request.make_response(content, headers=[
            ("Content-Type", XLSX), ("Content-Disposition", content_disposition(filename))])

    def _formats(self, book):
        base = {"border": 1, "valign": "vcenter"}
        money = dict(base, num_format="#,##0.00;-#,##0.00;\"\"")
        return {
            "title": book.add_format({"bold": True, "font_size": 14}),
            "head": book.add_format(dict(base, bold=True, align="center", text_wrap=True, bg_color="#F2F2F2")),
            "text": book.add_format(base),
            "money": book.add_format(money),
            "red": book.add_format(dict(money, font_color="#C00000")),
            "band": book.add_format(dict(base, bold=True, bg_color="#FFCC00")),
            "band_money": book.add_format(dict(money, bold=True, bg_color="#FFCC00")),
            "band_red": book.add_format(dict(money, bold=True, bg_color="#FFCC00", font_color="#C00000")),
            "sub": book.add_format(dict(base, font_color="#555555", indent=1)),
            "sub_money": book.add_format(dict(money, font_color="#555555")),
            "total": book.add_format(dict(base, bold=True, bg_color="#E2EFDA")),
            "total_money": book.add_format(dict(money, bold=True, bg_color="#E2EFDA")),
        }

    def _build_pl(self, data, detail):
        import xlsxwriter
        buf = io.BytesIO()
        book = xlsxwriter.Workbook(buf, {"in_memory": True})
        sheet = book.add_worksheet("Foyda va zarar")
        f = self._formats(book)
        sheet.write(0, 0, "Foyda va zarar: %s — %s (%s)" % (data["date_from"], data["date_to"], data["currency"]),
                    f["title"])
        sheet.merge_range(2, 0, 3, 0, "№", f["head"])
        sheet.merge_range(2, 1, 3, 1, "Sana", f["head"])
        sheet.merge_range(2, 2, 3, 2, "Mazmuni", f["head"])
        sheet.merge_range(2, 3, 3, 3, "Valyuta", f["head"])
        sheet.merge_range(2, 4, 2, 5, "Daromad", f["head"])
        sheet.merge_range(2, 6, 2, 7, "Xarajat", f["head"])
        sheet.merge_range(2, 8, 3, 8, "Qoldiq foyda", f["head"])
        for col, label in ((4, "Summa"), (5, "Dollarda"), (6, "Summa"), (7, "Dollarda")):
            sheet.write(3, col, label, f["head"])
        sheet.set_column(0, 0, 5)
        sheet.set_column(1, 1, 11)
        sheet.set_column(2, 2, 52)
        sheet.set_column(3, 3, 8)
        sheet.set_column(4, 8, 15)
        row = 4
        for block in data["companies"]:
            sheet.write(row, 0, block["name"], f["band"])
            for col in (1, 2, 3, 4, 6):
                sheet.write(row, col, "", f["band"])
            sheet.write(row, 5, block["income"], f["band_money"])
            sheet.write(row, 7, block["expense"], f["band_red"])
            sheet.write(row, 8, block["profit"], f["band_money"])
            row += 1
            for line in block["rows"]:
                sheet.write(row, 0, line["no"], f["text"])
                sheet.write(row, 1, "", f["text"])
                sheet.write(row, 2, line["name"], f["text"])
                sheet.write(row, 3, "", f["text"])
                sheet.write(row, 4, "", f["text"])
                sheet.write(row, 5, line["income"], f["money"])
                sheet.write(row, 6, "", f["text"])
                sheet.write(row, 7, line["expense"], f["red"])
                sheet.write(row, 8, "", f["text"])
                row += 1
                if not detail:
                    continue
                for d in line["details"]:
                    sheet.write(row, 0, "", f["sub"])
                    sheet.write(row, 1, d["date"], f["sub"])
                    sheet.write(row, 2, " · ".join(b for b in (d["label"], d["partner"]) if b), f["sub"])
                    sheet.write(row, 3, d["currency"], f["sub"])
                    income = bool(d["income"])
                    sheet.write(row, 4, d["amount"] if income else "", f["sub_money"])
                    sheet.write(row, 5, d["income"] if income else "", f["sub_money"])
                    sheet.write(row, 6, "" if income else d["amount"], f["sub_money"])
                    sheet.write(row, 7, "" if income else d["expense"], f["sub_money"])
                    sheet.write(row, 8, "", f["sub"])
                    sheet.set_row(row, None, None, {"level": 1, "hidden": False})
                    row += 1
        if len(data["companies"]) > 1:
            sheet.write(row, 2, "Jami", f["total"])
            sheet.write(row, 5, data["income"], f["total_money"])
            sheet.write(row, 7, data["expense"], f["total_money"])
            sheet.write(row, 8, data["profit"], f["total_money"])
        sheet.freeze_panes(4, 3)
        book.close()
        return buf.getvalue()

    def _build_balance(self, data, detail):
        import xlsxwriter
        buf = io.BytesIO()
        book = xlsxwriter.Workbook(buf, {"in_memory": True})
        sheet = book.add_worksheet("Balans")
        f = self._formats(book)
        sheet.write(0, 0, "%s — %s davr oralig'i balans hisoboti · %s (%s)" % (
            data["date_from"], data["date_to"], data["company"]["name"], data["currency"]), f["title"])
        sheet.merge_range(2, 0, 3, 0, "№", f["head"])
        sheet.merge_range(2, 1, 3, 1, "Ko'rsatkich nomi", f["head"])
        sheet.merge_range(2, 2, 2, 3, "%s kun boshiga qoldiq" % data["date_from"], f["head"])
        sheet.merge_range(2, 4, 2, 5, "Aylanma", f["head"])
        sheet.merge_range(2, 6, 2, 7, "%s kun oxiriga qoldiq" % data["date_to"], f["head"])
        for col, label in enumerate(("Haqqimiz", "Qarzimiz", "Kirim", "Chiqim", "Haqqimiz", "Qarzimiz"), 2):
            sheet.write(3, col, label, f["head"])
        sheet.set_column(0, 0, 5)
        sheet.set_column(1, 1, 46)
        sheet.set_column(2, 7, 16)
        keys = ("open_dr", "open_cr", "debit", "credit", "close_dr", "close_cr")
        row = 4
        for line in data["rows"]:
            sheet.write(row, 0, line["no"], f["text"])
            sheet.write(row, 1, line["name"], f["text"])
            for col, key in enumerate(keys, 2):
                sheet.write(row, col, line[key], f["money"])
            row += 1
            if not detail:
                continue
            for d in line["details"]:
                close = d["close"]
                opening = d["open"]
                values = (max(opening, 0), max(-opening, 0), d["debit"], d["credit"], max(close, 0), max(-close, 0))
                sheet.write(row, 0, "", f["sub"])
                sheet.write(row, 1, d["label"], f["sub"])
                for col, value in enumerate(values, 2):
                    sheet.write(row, col, value, f["sub_money"])
                sheet.set_row(row, None, None, {"level": 1})
                row += 1
        sheet.write(row, 0, "", f["total"])
        sheet.write(row, 1, "JAMI", f["total"])
        for col, key in enumerate(keys, 2):
            sheet.write(row, col, data["totals"][key], f["total_money"])
        sheet.freeze_panes(4, 2)
        book.close()
        return buf.getvalue()
