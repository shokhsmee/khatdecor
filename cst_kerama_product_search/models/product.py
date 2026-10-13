"""Word-by-word product search.

Odoo matches the typed text as one contiguous string: «бел лдсп» finds only a
name that contains «бел лдсп» as such, so «Белый Корона ЛДСП» never comes up.
Here the text is split into words, every word has to appear somewhere — in
the name, the internal reference, the barcode or the characteristic — and
the products whose name *starts* with the first word are listed first.

Two entry points need it.  Relational fields and list searches go through
``_search_display_name``; the autocomplete of a many2one on ``product.product``
does not — Odoo's ``name_search`` there queries ``name`` and ``default_code``
directly — so that one is overridden as well.
"""
import re

from odoo import api, models
from odoo.fields import Domain

WORD_OPERATORS = ("ilike", "like")
_WORD = re.compile(r"[^\s,;]+")


def _words(value):
    return _WORD.findall(value) if isinstance(value, str) else []


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _search_display_name(self, operator, value):
        words = _words(value)
        if operator not in WORD_OPERATORS or not words:
            return super()._search_display_name(operator, value)
        parent = super()
        # every word: Odoo's own criteria (name, code, barcode, supplier code)
        # OR the characteristic — so «кашмир глянц» reaches the Глянцевый variant
        return Domain.AND([
            Domain.OR([
                Domain(parent._search_display_name(operator, word)),
                Domain("cst_characteristic", operator, word),
            ])
            for word in words
        ])

    @api.model
    def name_search(self, name="", domain=None, operator="ilike", limit=100):
        if not name or operator not in WORD_OPERATORS or not isinstance(name, str):
            return super().name_search(name, domain, operator, limit)
        base = Domain(domain or Domain.TRUE)
        # an exact internal reference or barcode wins outright, as in Odoo
        products = (
            self.search_fetch(base & Domain("default_code", "=", name),
                              ["display_name"], limit=limit)
            or self.search_fetch(base & Domain("barcode", "=", name),
                                 ["display_name"], limit=limit)
        )
        if not products:
            products = self._cst_search_by_words(base, operator, name, limit)
        if not products:
            # Odoo's last resorts: «[CODE]» in the text, the supplier's own code
            return super().name_search(name, domain, operator, limit)
        return [(product.id, product.display_name) for product in products.sudo()]

    def _cst_search_by_words(self, base, operator, name, limit):
        """Words-match, names starting with the first word first."""
        match = base & Domain("display_name", operator, name)
        first = _words(name)[0]
        products = self.search_fetch(
            match & Domain("name", "=ilike", first + "%"), ["display_name"], limit=limit)
        rest = limit - len(products) if limit else None
        if rest is None or rest > 0:
            products |= self.search_fetch(
                match & Domain("id", "not in", products.ids), ["display_name"], limit=rest)
        return products


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _search_display_name(self, operator, value):
        words = _words(value)
        if operator not in WORD_OPERATORS or len(words) < 2:
            # one word: Odoo already unions the template's name with its
            # variants, and the variant side carries the characteristic
            return super()._search_display_name(operator, value)
        parent = super()
        return Domain.AND([parent._search_display_name(operator, word) for word in words])

    @api.model
    def name_search(self, name="", domain=None, operator="ilike", limit=100):
        if not name or operator not in WORD_OPERATORS or not isinstance(name, str):
            return super().name_search(name, domain, operator, limit)
        # same rule Odoo applies before searching variants from a template
        self_obj = self
        if ("search_product_product" not in self.env.context
                and any(term[0] == "id" for term in (domain or []))):
            self_obj = self.with_context(search_product_product=False)
        match = Domain(domain or Domain.TRUE) & Domain("display_name", operator, name)
        first = _words(name)[0]
        templates = self_obj.search_fetch(
            match & Domain("name", "=ilike", first + "%"), ["display_name"], limit=limit)
        rest = limit - len(templates) if limit else None
        if rest is None or rest > 0:
            templates |= self_obj.search_fetch(
                match & Domain("id", "not in", templates.ids), ["display_name"], limit=rest)
        return [(template.id, template.display_name) for template in templates.sudo()]
