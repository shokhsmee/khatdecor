from odoo import SUPERUSER_ID, api

# The roles app's root menu and its sub-folder get new English names in this
# version («Roles», «Advanced»). Odoo keeps the old uz/ru names of a record
# whose English name changes and never overwrites them on upgrade, so they
# are set here.
NAMES = {
    "access_roles.access_role_menu_root": {"uz_UZ": "Rollar", "ru_RU": "Роли"},
    "access_roles.access_role_menu": {"uz_UZ": "Kengaytirilgan", "ru_RU": "Расширенные"},
}

# Odoo's Russian names of three accounting levels describe menus
# («Показать все функции учета»), which reads badly as a level of the role
# builder. Replaced only while they still hold that stock text.
RU_LEVELS = {
    "account.group_account_readonly": ("Показать функции учета — только чтение", "Только просмотр"),
    "account.group_account_basic": ("Базовый", "Счета и банк"),
    "account.group_account_user": ("Показать все функции учета", "Бухгалтер"),
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    installed = set(env["res.lang"].search([]).mapped("code"))
    for xmlid, names in NAMES.items():
        menu = env.ref(xmlid, raise_if_not_found=False)
        if menu:
            menu.update_field_translations(
                "name", {lang: name for lang, name in names.items() if lang in installed})
    if "ru_RU" in installed:
        for xmlid, (stock, name) in RU_LEVELS.items():
            group = env.ref(xmlid, raise_if_not_found=False)
            if group and group.with_context(lang="ru_RU").name == stock:
                group.update_field_translations("name", {"ru_RU": name})
