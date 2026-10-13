import io

from odoo import _, http
from odoo.exceptions import AccessError, MissingError
from odoo.http import content_disposition, request


class ShiftRegisterController(http.Controller):
    """The shift register as a workbook -- the sheet the shop used to keep by hand."""

    @http.route("/cst_shift/register/xlsx/<int:wizard_id>", type="http", auth="user")
    def register_xlsx(self, wizard_id, **kwargs):
        wizard = request.env["cst.production.shift.report"].browse(wizard_id).exists()
        if not wizard:
            raise MissingError(_("Hisobot topilmadi."))
        try:
            wizard.check_access("read")
        except AccessError:
            return request.not_found()
        import xlsxwriter
        rows = wizard._rows()
        output = io.BytesIO()
        book = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = book.add_worksheet("Smena registri")
        base = {"font_name": "Arial", "font_size": 9, "border": 1, "valign": "vcenter"}
        f_title = book.add_format({"font_name": "Arial", "font_size": 12, "bold": True})
        f_head = book.add_format({**base, "bold": True, "align": "center", "text_wrap": True, "bg_color": "#D9D9D9"})
        f_text = book.add_format({**base, "text_wrap": True})
        f_num = book.add_format({**base, "num_format": "# ##0.###;-# ##0.###;"})
        f_money = book.add_format({**base, "num_format": "# ##0;-# ##0;"})
        f_red = book.add_format({**base, "num_format": "# ##0;-# ##0;", "font_color": "#B3362B"})
        f_tot = book.add_format({**base, "bold": True, "bg_color": "#E8E8E8", "num_format": "# ##0.###;-# ##0.###;"})
        f_tot_money = book.add_format({**base, "bold": True, "bg_color": "#E8E8E8", "num_format": "# ##0;-# ##0;"})
        f_tot_text = book.add_format({**base, "bold": True, "bg_color": "#E8E8E8"})

        heads = [("Sana", 11), ("Bo'lim", 20), ("Smena", 9), ("Menejer", 18), ("Xodimlar", 34), ("Xodim soni", 7),
                 ("Buyurtma", 8), ("Reja", 9), ("1-sort", 9), ("2-sort", 8), ("Brak", 8), ("Jarima", 11),
                 ("KPI fondi", 12), ("Har xodimga", 11), ("Mahsulotlar (1-sort / 2-sort / brak)", 46), ("Holat", 10)]
        sheet.merge_range(0, 0, 0, len(heads) - 1, "Smena registri  %s – %s" % (
            wizard.date_from.strftime("%d.%m.%Y"), wizard.date_to.strftime("%d.%m.%Y")), f_title)
        for col, (name, width) in enumerate(heads):
            sheet.set_column(col, col, width)
            sheet.write(2, col, name, f_head)
        sheet.set_row(2, 28)
        r = 3
        totals = {"planned": 0.0, "good": 0.0, "second": 0.0, "scrap": 0.0, "penalty": 0.0, "kpi": 0.0}
        for row in rows:
            sheet.write(r, 0, row["date"].strftime("%d.%m.%Y"), f_text)
            sheet.write(r, 1, row["department"], f_text)
            sheet.write(r, 2, row["template"], f_text)
            sheet.write(r, 3, row["manager"], f_text)
            sheet.write(r, 4, row["employees"], f_text)
            sheet.write_number(r, 5, row["employee_count"], f_num)
            sheet.write_number(r, 6, row["orders"], f_num)
            sheet.write_number(r, 7, row["planned"], f_num)
            sheet.write_number(r, 8, row["good"], f_num)
            sheet.write_number(r, 9, row["second"], f_num)
            sheet.write_number(r, 10, row["scrap"], f_red)
            sheet.write_number(r, 11, -row["penalty"] if row["penalty"] else 0, f_red)
            sheet.write_number(r, 12, row["kpi"], f_money)
            sheet.write_number(r, 13, row["per_employee"], f_money)
            sheet.write(r, 14, row["products"], f_text)
            sheet.write(r, 15, row["state"], f_text)
            for key in totals:
                totals[key] += row[key]
            r += 1
        sheet.write(r, 0, "Jami", f_tot_text)
        for col in (1, 2, 3, 4, 5, 6, 14, 15):
            sheet.write(r, col, "", f_tot_text)
        sheet.write_number(r, 7, totals["planned"], f_tot)
        sheet.write_number(r, 8, totals["good"], f_tot)
        sheet.write_number(r, 9, totals["second"], f_tot)
        sheet.write_number(r, 10, totals["scrap"], f_tot)
        sheet.write_number(r, 11, -totals["penalty"] if totals["penalty"] else 0, f_tot_money)
        sheet.write_number(r, 12, totals["kpi"], f_tot_money)
        sheet.write(r, 13, "", f_tot_text)
        sheet.freeze_panes(3, 2)
        book.close()
        data = output.getvalue()
        filename = "smena_registri_%s_%s.xlsx" % (wizard.date_from.strftime("%Y%m%d"), wizard.date_to.strftime("%Y%m%d"))
        return request.make_response(data, headers=[
            ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("Content-Disposition", content_disposition(filename)),
        ])
