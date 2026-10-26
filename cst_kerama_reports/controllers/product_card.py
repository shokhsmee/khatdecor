import io

from odoo import _, http
from odoo.exceptions import MissingError
from odoo.http import content_disposition, request


class ProductCardController(http.Controller):
    """Excel of «Mahsulot kartochkasi»: one sheet, the products one under another."""

    @http.route("/cst_reports/product_card/xlsx/<int:wizard_id>", type="http", auth="user", methods=["GET"])
    def product_card_xlsx(self, wizard_id, **kwargs):
        wizard = request.env["cst.product.card.wizard"].browse(wizard_id).exists()
        if not wizard:
            raise MissingError(_("Hisobot parametrlari topilmadi — qaytadan oching."))
        wizard.check_access("read")
        content = self._workbook(wizard._report_values(), wizard.daily)
        return request.make_response(content, headers=[
            ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("Content-Disposition", content_disposition(
                "mahsulot_kartochkasi_%s_%s.xlsx" % (wizard.date_from, wizard.date_to))),
        ])

    def _workbook(self, values, daily):
        import xlsxwriter

        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {"in_memory": True})
        sheet = book.add_worksheet("Kartochka")
        base = {"font_size": 9, "border": 1, "valign": "vcenter"}
        number = "#,##0.###;-#,##0.###;0"
        f_title = book.add_format({"bold": True, "font_size": 12})
        f_head = book.add_format({**base, "bold": True, "align": "center", "text_wrap": True, "bg_color": "#D9D9D9"})
        f_text = book.add_format(base)
        f_num = book.add_format({**base, "num_format": number})
        f_prod = book.add_format({"bold": True, "font_size": 11})
        f_block = book.add_format({**base, "bold": True, "bg_color": "#D7F0D7"})
        f_block_num = book.add_format({**base, "bold": True, "bg_color": "#D7F0D7", "num_format": number})
        f_edge = book.add_format({**base, "italic": True, "bg_color": "#F2F2F2"})
        f_edge_num = book.add_format({**base, "italic": True, "bg_color": "#F2F2F2", "num_format": number})

        heads = [("№", 5), ("Sana", 16), ("Hujjat", 20), ("Operatsiya", 20)]
        if not daily:
            heads += [("Qayerdan", 28), ("Qayerga", 28), ("Kontragent / asos", 26)]
        heads += [("Kirim", 12), ("Chiqim", 12), ("Qoldiq", 13)]
        last = len(heads) - 1
        for col, (_name, width) in enumerate(heads):
            sheet.set_column(col, col, width)
        sheet.write(0, 0, values["title"], f_title)
        sheet.write(1, 0, "%s — %s" % (values["date_from"].strftime("%d.%m.%Y"), values["date_to"].strftime("%d.%m.%Y")))
        row = 3
        for product in values["products"]:
            title = product["label"] + (" — %s" % product["characteristic"] if product["characteristic"] else "")
            sheet.write(row, 0, "%s (%s)" % (title, product["uom"]), f_prod)
            row += 1
            sheet.merge_range(row, 0, row, 3, "Hozirgi qoldiq (ombor bo'yicha)", f_head)
            sheet.write_row(row, 4, ["Omborda", "Band qilingan", "Bo'sh"], f_head)
            row += 1
            for stock in product["on_hand"]:
                sheet.merge_range(row, 0, row, 3, stock["label"], f_text)
                sheet.write_row(row, 4, [stock["qty"], stock["reserved"], stock["free"]], f_num)
                row += 1
            row += 1
            if product["blocks"]:
                sheet.write_row(row, 0, [h for h, _w in heads], f_head)
                row += 1
            span = last - 3
            for block in product["blocks"]:
                sheet.merge_range(row, 0, row, last, block["label"], f_block)
                row += 1
                sheet.merge_range(row, 0, row, span, "Boshlang'ich qoldiq", f_edge)
                sheet.write_row(row, span + 1, ["", "", block["opening"]], f_edge_num)
                row += 1
                for index, line in enumerate(block["rows"], start=1):
                    date = line["date"].strftime("%d.%m.%Y" if daily else "%d.%m.%Y %H:%M")
                    cells = [index, date, line["document"], line["kind"]]
                    if not daily:
                        partner = " · ".join(x for x in (line["partner"], line["origin"]) if x)
                        cells += [line["source"], line["dest"], partner]
                    sheet.write_row(row, 0, cells, f_text)
                    sheet.write_row(row, len(cells), [line["in"] or "", line["out"] or "", line["balance"]], f_num)
                    row += 1
                sheet.merge_range(row, 0, row, span, "Davr yakuni", f_block)
                sheet.write_row(row, span + 1, [block["in"], block["out"], block["closing"]], f_block_num)
                row += 2
            row += 1
        book.close()
        return stream.getvalue()
