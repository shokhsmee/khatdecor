import io
import json

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import content_disposition, request


class PayrollReportController(http.Controller):
    """Excel of the running-account report.

    The accounting department has read this as a workbook for years; the
    dashboard replaces the reading, not the sending it to someone.
    """

    @http.route("/cst_payroll/report/xlsx", type="http", auth="user",
                methods=["POST"], csrf=True)
    def payroll_report_xlsx(self, filters=None, **kwargs):
        if not request.env.user.has_group("cst_kerama_payroll.group_payroll_user"):
            raise AccessError(_("You are not allowed to read the payroll report."))
        try:
            filters = json.loads(filters or "{}")
        except ValueError:
            filters = {}

        data = request.env["cst.payroll.report"].get_report_data(filters)
        content = self._build_workbook(data)
        filename = "oylik_hisobot_%s_%s.xlsx" % (data["date_from"], data["date_to"])
        return request.make_response(content, headers=[
            ("Content-Type", "application/vnd.openxmlformats-officedocument."
                             "spreadsheetml.sheet"),
            ("Content-Disposition", content_disposition(filename)),
        ])

    @staticmethod
    def _day(value):
        """ISO date to the dd.mm.yyyy the workbook's readers expect."""
        year, month, day = value.split("-")
        return f"{day}.{month}.{year}"

    def _build_workbook(self, data):
        import xlsxwriter

        accruals = data["columns"]["accruals"]
        deductions = data["columns"]["deductions"]
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {"in_memory": True})
        sheet = book.add_worksheet("Hisobot")

        base = {"font_size": 9, "border": 1}
        f_title = book.add_format({"bold": True, "font_size": 12, "align": "center"})
        f_sub = book.add_format({"font_size": 10, "align": "center"})
        f_head = book.add_format({
            **base, "bold": True, "align": "center", "valign": "vcenter",
            "text_wrap": True, "bg_color": "#F1F3F5"})
        f_text = book.add_format({**base})
        f_num = book.add_format({**base, "num_format": "# ##0;-# ##0;"})
        f_num_bold = book.add_format({
            **base, "bold": True, "num_format": "# ##0;-# ##0;", "bg_color": "#F7F7F7"})
        f_company = book.add_format({**base, "bold": True, "bg_color": "#E9ECEF"})
        f_company_num = book.add_format({
            **base, "bold": True, "num_format": "# ##0;-# ##0;", "bg_color": "#E9ECEF"})
        f_total = book.add_format({**base, "bold": True, "bg_color": "#DEE2E6"})
        f_total_num = book.add_format({
            **base, "bold": True, "num_format": "# ##0;-# ##0;", "bg_color": "#DEE2E6"})

        width = 3 + len(accruals) + 1 + len(deductions) + 1 + 1
        sheet.merge_range(0, 0, 0, width - 1,
                          "Ходимларга хисобланган иш хаки, бонуслар, жарималар "
                          "ва берилган пуллар буйича хисобот", f_title)
        sheet.merge_range(1, 0, 1, width - 1,
                          "%s - %s давр оралиги учун" % (
                              self._day(data["date_from"]),
                              self._day(data["date_to"])), f_sub)

        # Two-row header, mirroring the workbook it replaces.
        row = 3
        first_accrual = 3
        last_accrual = first_accrual + len(accruals)
        first_deduction = last_accrual + 1
        last_deduction = first_deduction + len(deductions)
        sheet.merge_range(row, 0, row + 1, 0, "№", f_head)
        sheet.merge_range(row, 1, row + 1, 1, "Ходим", f_head)
        sheet.merge_range(row, 2, row + 1, 2, "Бошлангич колдик", f_head)
        sheet.merge_range(row, first_accrual, row, last_accrual, "Хисобланди", f_head)
        sheet.merge_range(row, first_deduction, row, last_deduction, "Ушланмалар", f_head)
        sheet.merge_range(row, last_deduction + 1, row + 1, last_deduction + 1,
                          "Охирги колдик", f_head)
        for offset, column in enumerate(accruals):
            sheet.write(row + 1, first_accrual + offset, column["name"], f_head)
        sheet.write(row + 1, last_accrual, "Жами", f_head)
        for offset, column in enumerate(deductions):
            sheet.write(row + 1, first_deduction + offset, column["name"], f_head)
        sheet.write(row + 1, last_deduction, "Жами ушланди", f_head)

        sheet.set_column(0, 0, 5)
        sheet.set_column(1, 1, 38)
        sheet.set_column(2, width - 1, 15)
        sheet.set_row(row, 20)
        sheet.set_row(row + 1, 42)
        sheet.freeze_panes(row + 2, 2)

        row += 2
        for company in data["companies"]:
            totals = company["totals"]
            sheet.write(row, 0, "", f_company)
            sheet.write(row, 1, company["name"], f_company)
            sheet.write_number(row, 2, totals["opening"], f_company_num)
            for offset, column in enumerate(accruals):
                sheet.write_number(row, first_accrual + offset,
                                   totals["accruals"][str(column["id"])], f_company_num)
            sheet.write_number(row, last_accrual, totals["accrued_total"], f_company_num)
            for offset, column in enumerate(deductions):
                sheet.write_number(row, first_deduction + offset,
                                   totals["deductions"][str(column["id"])], f_company_num)
            sheet.write_number(row, last_deduction, totals["deducted_total"], f_company_num)
            sheet.write_number(row, last_deduction + 1, totals["closing"], f_company_num)
            row += 1

            for number, line in enumerate(company["rows"], start=1):
                sheet.write_number(row, 0, number, f_text)
                sheet.write(row, 1, line["name"], f_text)
                sheet.write_number(row, 2, line["opening"], f_num)
                for offset, column in enumerate(accruals):
                    sheet.write_number(row, first_accrual + offset,
                                       line["accruals"][str(column["id"])], f_num)
                sheet.write_number(row, last_accrual, line["accrued_total"], f_num_bold)
                for offset, column in enumerate(deductions):
                    sheet.write_number(row, first_deduction + offset,
                                       line["deductions"][str(column["id"])], f_num)
                sheet.write_number(row, last_deduction, line["deducted_total"], f_num_bold)
                sheet.write_number(row, last_deduction + 1, line["closing"], f_num_bold)
                row += 1

        if len(data["companies"]) > 1:
            totals = data["totals"]
            sheet.write(row, 0, "", f_total)
            sheet.write(row, 1, "ЖАМИ", f_total)
            sheet.write_number(row, 2, totals["opening"], f_total_num)
            for offset, column in enumerate(accruals):
                sheet.write_number(row, first_accrual + offset,
                                   totals["accruals"][str(column["id"])], f_total_num)
            sheet.write_number(row, last_accrual, totals["accrued_total"], f_total_num)
            for offset, column in enumerate(deductions):
                sheet.write_number(row, first_deduction + offset,
                                   totals["deductions"][str(column["id"])], f_total_num)
            sheet.write_number(row, last_deduction, totals["deducted_total"], f_total_num)
            sheet.write_number(row, last_deduction + 1, totals["closing"], f_total_num)

        book.close()
        return stream.getvalue()
