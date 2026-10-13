from odoo import api, fields, models

# Default tag names per role — only used once, to pre-fill Kassa settings.
_DEFAULT_TAGS = {
    "cst_kassa_client_tag_ids": ["Розничные клиенты", "Оптовые клиенты", "Дилеры"],
    "cst_kassa_supplier_tag_ids": ["Поставщики", "Kommunal xizmatlar"],
    "cst_kassa_employee_tag_ids": ["Сотрудники"],
}


class ResCompany(models.Model):
    _inherit = "res.company"

    cst_kassa_allow_reopen = fields.Boolean(
        string="Reopen closed cash days", default=True,
        help="On: a cashier can reopen the kassa's last closed day, a kassa manager also a confirmed "
             "one (its difference entry is reversed). Off: a closed day stays closed.")
    cst_kassa_client_tag_ids = fields.Many2many(
        "res.partner.category", "cst_kassa_company_client_tag_rel", "company_id", "category_id",
        string="Client tags",
        help="Client payments and refunds offer only contacts with one of these tags. Empty: every contact.")
    cst_kassa_supplier_tag_ids = fields.Many2many(
        "res.partner.category", "cst_kassa_company_supplier_tag_rel", "company_id", "category_id",
        string="Supplier tags",
        help="Supplier payments and refunds offer only contacts with one of these tags. Empty: every contact.")
    cst_kassa_employee_tag_ids = fields.Many2many(
        "res.partner.category", "cst_kassa_company_employee_tag_rel", "company_id", "category_id",
        string="Employee tags",
        help="Employee advances offer only employees whose work contact has one of these tags. Empty: every employee.")

    @api.model
    def _cst_kassa_seed_partner_tags(self):
        """Fill the role tags once from the tags that already exist; later the
        settings belong to the user (an emptied list stays empty)."""
        ICP = self.env["ir.config_parameter"].sudo()
        if ICP.get_param("cst_kerama_kassa.partner_tags_seeded"):
            return
        Tag = self.env["res.partner.category"].sudo().with_context(active_test=False)
        vals = {}
        for field, names in _DEFAULT_TAGS.items():
            tags = Tag.browse()
            for name in names:
                tags |= Tag.search([("name", "=", name)])
            if tags:
                vals[field] = [(6, 0, tags.ids)]
        if vals:
            self.sudo().search([]).write(vals)
        ICP.set_param("cst_kerama_kassa.partner_tags_seeded", "1")
