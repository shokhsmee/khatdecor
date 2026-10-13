"""Filters on the on-screen sheet itself.

Every «Ekranda ko'rish» sheet is rendered from one wizard record, so the
wizard's own form — flattened into a single row — is the filter bar: change a
date or a partner, press «Ko'rsatish», the record is saved and the iframe
reloads the same URL, now reading the new values.  No per-report code.
"""
from copy import deepcopy

from lxml import etree

from odoo import api, models

TRUE_VALUES = ("1", "True", "true")


class CstReportFilterBar(models.AbstractModel):
    _name = "cst.report.filter.bar"
    _description = "Hisobot ekranidagi filtrlar"

    @api.model
    def get_filter_bar(self, report_name, res_id):
        report = self.env["ir.actions.report"].sudo().search(
            [("report_name", "=", report_name)], limit=1)
        model_name = report.model
        if not (model_name and model_name.startswith("cst.") and model_name in self.env):
            return False
        Wizard = self.env[model_name]
        if not Wizard._transient or not Wizard.browse(int(res_id)).exists():
            return False
        views = Wizard.get_views([(False, "form")])
        return {
            "model": model_name,
            "arch": self._flatten_arch(views["views"]["form"]["arch"]),
            "fields": views["models"][model_name]["fields"],
            "relatedModels": views["models"],
        }

    @api.model
    def _flatten_arch(self, arch):
        source = etree.fromstring(arch)
        form = etree.Element("form", {"class": "cst_rf_form"})
        row = etree.SubElement(form, "div", {"class": "cst_rf_row"})
        for node in source.iter("field"):
            ancestors = list(node.iterancestors())
            if any(a.tag in ("field", "footer") for a in ancestors):
                continue  # sub-view fields and dialog buttons stay out
            field = deepcopy(node)
            field.tail = None
            for attr in ("nolabel", "colspan"):
                field.attrib.pop(attr, None)
            conditions = [a.get("invisible") for a in ancestors if a.get("invisible")]
            if field.get("invisible"):
                conditions.append(field.get("invisible"))
            if any(c in TRUE_VALUES for c in conditions):
                field.set("invisible", "1")
                row.append(field)
                continue
            item = etree.SubElement(row, "div", {"class": "cst_rf_item"})
            if conditions:
                item.set("invisible", " or ".join("(%s)" % c for c in conditions))
            label = etree.SubElement(item, "label", {"for": field.get("name")})
            if field.get("string"):
                label.set("string", field.get("string"))
            item.append(field)
        actions = etree.SubElement(row, "div", {"class": "cst_rf_actions"})
        etree.SubElement(actions, "button", {
            "special": "save", "string": "Ko'rsatish",
            "class": "btn-primary", "icon": "fa-refresh"})
        return etree.tostring(form, encoding="unicode")
