import io

from odoo import _, http
from odoo.exceptions import AccessError, MissingError
from odoo.http import content_disposition, request

from odoo.addons.cst_kerama_reports.models.stock_ledger import IN_FLOWS, OUT_FLOWS


class StockLedgerController(http.Controller):
    """Excel of «Ombor batafsil hisoboti» — the same workbook the storekeepers
    read today, 31 columns wide, one row per product per warehouse."""

    @http.route("/cst_reports/stock_ledger/xlsx/<int:wizard_id>", type="http",
                auth="user", methods=["GET"])
    def stock_ledger_xlsx(self, wizard_id, **kwargs):
        if not request.env.user.has_group("stock.group_stock_user"):
            raise AccessError(_("Ombor hisobotini o'qishga ruxsatingiz yo'q."))
        wizard = request.env["cst.stock.ledger.wizard"].browse(wizard_id).exists()
        if not wizard:
            raise MissingError(_("Hisobot parametrlari topilmadi — qaytadan oching."))
        values = wizard._report_values()
        content = self._build_workbook(values)
        filename = "ombor_batafsil_%s_%s.xlsx" % (wizard.date_from, wizard.date_to)
        return request.make_response(content, headers=[
            ("Content-Type", "application/vnd.openxmlformats-officedocument."
                             "spreadsheetml.sheet"),
            ("Content-Disposition", content_disposition(filename)),
        ])

    @staticmethod
    def _day(value):
        return value.strftime("%d.%m.%y")

    def _build_workbook(self, values):
        # product_label() prints the product without its characteristic,
        # which this workbook already gives a column of its own
        engine = request.env["cst.warehouse.report"]
        import xlsxwriter

        data = values["data"]
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {"in_memory": True})
        sheet = book.add_worksheet("Ombor")
        base = {"font_size": 9, "border": 1, "valign": "vcenter"}
        f_title = book.add_format({"bold": True, "font_size": 12, "align": "center"})
        f_head = book.add_format({**base, "bold": True, "align": "center", "text_wrap": True,
                                  "bg_color": "#D9D9D9"})
        f_text = book.add_format({**base})
        f_num = book.add_format({**base, "num_format": "# ##0.###;-# ##0.###;"})
        f_money = book.add_format({**base, "num_format": "# ##0.00;-# ##0.00;"})
        f_wh = book.add_format({**base, "bold": True, "bg_color": "#D7F0D7"})
        f_wh_num = book.add_format({**base, "bold": True, "bg_color": "#D7F0D7",
                                    "num_format": "# ##0.00;-# ##0.00;"})
        f_grp = book.add_format({**base, "bold": True, "bg_color": "#FFF2CC"})
        f_grp_num = book.add_format({**base, "bold": True, "bg_color": "#FFF2CC",
                                     "num_format": "# ##0.00;-# ##0.00;"})
        f_cat = book.add_format({**base, "bold": True, "bg_color": "#FDF6E3"})
        f_cat_num = book.add_format({**base, "bold": True, "bg_color": "#FDF6E3",
                                     "num_format": "# ##0.00;-# ##0.00;"})
        f_tot = book.add_format({**base, "bold": True, "bg_color": "#E8E8E8"})
        f_tot_num = book.add_format({**base, "bold": True, "bg_color": "#E8E8E8",
                                     "num_format": "# ##0.00;-# ##0.00;"})

        in_flows, out_flows = data["in_flows"], data["out_flows"]
        # column layout: №, Nomi, Xarakteristika, O'lchov, open(qty,cost,value),
        # each in flow (qty,value), reval(in,out), each out flow (qty,value), close(qty,cost,value)
        headers = [("№", 4), ("Nomi", 34), ("Xarakteristika", 14), ("O'lchov birligi", 8)]
        sheet.set_row(1, 22)
        sheet.merge_range(1, 1, 1, 6, values["title"], f_title)
        sheet.write(2, 1, "%s – %s davr oralig'i uchun" % (
            self._day(values["date_from"]), self._day(values["date_to"])), f_text)

        col = 0
        for name, width in headers:
            sheet.set_column(col, col, width)
            sheet.merge_range(4, col, 5, col, name, f_head)
            col += 1
        groups = []  # (title, [(subtitle, kind)])
        groups.append(("%s kun boshiga qoldiq" % self._day(values["date_from"]),
                       [("Soni", "num"), ("Tannarxi", "money"), ("Summasi", "money")]))
        for _key, label in in_flows:
            groups.append((label, [("Soni", "num"), ("Summasi", "money")]))
        groups.append(("Qayta baholandi", [("Kirim summa", "money"), ("Chiqim summa", "money")]))
        for _key, label in out_flows:
            groups.append((label, [("Soni", "num"), ("Summasi", "money")]))
        groups.append(("%s kun oxiriga qoldiq" % self._day(values["date_to"]),
                       [("Soni", "num"), ("Tannarxi", "money"), ("Summasi", "money")]))
        kinds = []
        for title, subs in groups:
            sheet.merge_range(4, col, 4, col + len(subs) - 1, title, f_head)
            for sub, kind in subs:
                sheet.set_column(col, col, 11)
                sheet.write(5, col, sub, f_head)
                kinds.append(kind)
                col += 1
        sheet.freeze_panes(6, 4)

        def figures(row):
            out = [row["open_qty"], row.get("open_cost", None), row["open_value"]]
            for key, _l in in_flows:
                out += list(row["flows"][key])
            out += [row["reval_in"], row["reval_out"]]
            for key, _l in out_flows:
                out += list(row["flows"][key])
            out += [row["close_qty"], row.get("close_cost", None), row["close_value"]]
            return out

        def write_figures(r, row, f_n, f_m):
            for i, value in enumerate(figures(row)):
                if value is None or (isinstance(value, float) and abs(value) < 1e-9):
                    sheet.write_blank(r, 4 + i, None, f_n)
                else:
                    sheet.write_number(r, 4 + i, value, f_m if kinds[i] == "money" else f_n)

        r = 6
        for wh in data["warehouses"]:
            sheet.merge_range(r, 0, r, 3, "%s — %s" % (wh["company"].name, wh["warehouse"].name), f_wh)
            write_figures(r, wh["totals"], f_wh_num, f_wh_num)
            r += 1
            for group in wh["groups"]:
                sheet.merge_range(r, 0, r, 3, group["category"].name if group["category"] else "Kategoriyasiz", f_grp)
                write_figures(r, group["totals"], f_grp_num, f_grp_num)
                r += 1
                for cat in group["leaves"]:
                    if cat["category"] != group["category"]:
                        sheet.merge_range(r, 0, r, 3, cat["category"].name or "", f_cat)
                        write_figures(r, cat["totals"], f_cat_num, f_cat_num)
                        r += 1
                    for i, row in enumerate(cat["products"], 1):
                        sheet.write_number(r, 0, i, f_text)
                        sheet.write(r, 1, engine.product_label(row["product"]), f_text)
                        sheet.write(r, 2, row["characteristic"] or "", f_text)
                        sheet.write(r, 3, row["uom"] or "", f_text)
                        write_figures(r, row, f_num, f_money)
                        r += 1
        sheet.merge_range(r, 0, r, 3, "JAMI", f_tot)
        write_figures(r, data["totals"], f_tot_num, f_tot_num)
        book.close()
        return stream.getvalue()


class MinMaxController(http.Controller):
    """Excel of «Kam yoki ko'p miqdorda turgan mahsulot va xomashyo»."""

    @http.route("/cst_reports/minmax/xlsx/<int:wizard_id>", type="http", auth="user", methods=["GET"])
    def minmax_xlsx(self, wizard_id, **kwargs):
        if not request.env.user.has_group("stock.group_stock_user"):
            raise AccessError(_("Ombor hisobotini o'qishga ruxsatingiz yo'q."))
        wizard = request.env["cst.minmax.report.wizard"].browse(wizard_id).exists()
        if not wizard:
            raise MissingError(_("Hisobot parametrlari topilmadi — qaytadan oching."))
        values = wizard._report_values()
        content = self._build_workbook(values)
        return request.make_response(content, headers=[
            ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("Content-Disposition", content_disposition("min_max_qoldiqlar_%s.xlsx" % wizard.date_to)),
        ])

    def _build_workbook(self, values):
        import xlsxwriter

        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {"in_memory": True})
        sheet = book.add_worksheet("Min-max")
        base = {"font_size": 9, "border": 1, "valign": "vcenter"}
        f_title = book.add_format({"bold": True, "font_size": 12, "align": "center"})
        f_head = book.add_format({**base, "bold": True, "align": "center", "text_wrap": True, "bg_color": "#D9D9D9"})
        f_text = book.add_format(base)
        f_num = book.add_format({**base, "num_format": "# ##0.###;-# ##0.###;"})
        f_low = book.add_format({**base, "num_format": "-# ##0.###;-# ##0.###;", "font_color": "#C0392B", "bold": True})
        f_high = book.add_format({**base, "num_format": "+# ##0.###;-# ##0.###;", "font_color": "#1C5CAB", "bold": True})
        f_wh = book.add_format({**base, "bold": True, "bg_color": "#D7F0D7"})
        f_grp = book.add_format({**base, "bold": True, "bg_color": "#FFF2CC"})
        f_cat = book.add_format({**base, "bold": True, "bg_color": "#FDF6E3"})
        engine = request.env["cst.warehouse.report"]

        heads = [("№", 4), ("Mahsulot (xomashyo)", 40), ("Xarakteristika", 16), ("O'lchov", 8), ("Min", 9),
                 ("Max", 9), ("Qoldiq", 10), ("Kutilayotgan", 11), ("Kam (min dan)", 11),
                 ("Ko'p (max dan)", 11), ("Buyurtma kerak", 11)]
        sheet.merge_range(0, 0, 0, len(heads) - 1, values["title"], f_title)
        sheet.write(1, 0, "%s holatiga" % values["date_to"].strftime("%d.%m.%Y"), f_text)
        for col, (name, width) in enumerate(heads):
            sheet.set_column(col, col, width)
            sheet.write(3, col, name, f_head)
        sheet.freeze_panes(4, 2)
        r = 4
        for wh in values["warehouses"]:
            sheet.merge_range(r, 0, r, len(heads) - 1, "%s — %s  (%d ta kam, %d ta ko'p)" % (
                wh["company"].name, wh["warehouse"].name, wh["low_count"], wh["high_count"]), f_wh)
            r += 1
            for g in wh["groups"]:
                sheet.merge_range(r, 0, r, len(heads) - 1, engine.category_label(g["category"]), f_grp)
                r += 1
                for c in g["leaves"]:
                    if c["category"] != g["category"]:
                        sheet.merge_range(r, 0, r, len(heads) - 1, c["category"].name or "", f_cat)
                        r += 1
                    for i, row in enumerate(c["products"], 1):
                        sheet.write_number(r, 0, i, f_text)
                        sheet.write(r, 1, engine.product_label(row["product"]), f_text)
                        sheet.write(r, 2, row["characteristic"] or "", f_text)
                        sheet.write(r, 3, row["uom"] or "", f_text)
                        if row["has_rule"]:
                            sheet.write_number(r, 4, row["min"] or 0, f_num)
                            sheet.write_number(r, 5, row["max"] or 0, f_num)
                        else:
                            sheet.write(r, 4, "—", f_text)
                            sheet.write(r, 5, "—", f_text)
                        sheet.write_number(r, 6, row["on_hand"] or 0, f_num)
                        sheet.write_number(r, 7, row["forecast"] or 0, f_num)
                        if row["low"]:
                            sheet.write_number(r, 8, -row["low"], f_low)
                        else:
                            sheet.write_blank(r, 8, None, f_num)
                        if row["high"]:
                            sheet.write_number(r, 9, row["high"], f_high)
                        else:
                            sheet.write_blank(r, 9, None, f_num)
                        if row["has_rule"]:
                            sheet.write_number(r, 10, row["to_order"] or 0, f_num)
                        else:
                            sheet.write(r, 10, "qoida yo'q", f_text)
                        r += 1
        book.close()
        return stream.getvalue()
