"""Amount in words for Uzbek (num2words has no Uzbek)."""

_ONES = ["", "bir", "ikki", "uch", "to'rt", "besh", "olti", "yetti", "sakkiz", "to'qqiz"]
_TENS = ["", "o'n", "yigirma", "o'ttiz", "qirq", "ellik", "oltmish", "yetmish", "sakson", "to'qson"]
_SCALES = ["", "ming", "million", "milliard", "trillion"]
_UNITS = {
    "USD": ("AQSH dollari", "sent"),
    "UZS": ("so'm", "tiyin"),
    "RUB": ("rubl", "kopeyka"),
    "CNY": ("yuan", "fen"),
    "EUR": ("yevro", "sent"),
}


def _triplet(n):
    hundreds, rest = divmod(n, 100)
    tens, ones = divmod(rest, 10)
    words = []
    if hundreds:
        words += [_ONES[hundreds], "yuz"]
    if tens:
        words.append(_TENS[tens])
    if ones:
        words.append(_ONES[ones])
    return words


def uz_number_words(n):
    n = int(n)
    if n == 0:
        return "nol"
    parts, scale = [], 0
    while n and scale < len(_SCALES):
        n, tri = divmod(n, 1000)
        if tri:
            words = _triplet(tri)
            if _SCALES[scale]:
                words.append(_SCALES[scale])
            parts.insert(0, " ".join(words))
        scale += 1
    return " ".join(parts)


def uz_amount_words(amount, currency):
    """«O'n ming AQSH dollari 50 sent»."""
    integral, _sep, fractional = f"{abs(amount):.{currency.decimal_places}f}".partition(".")
    unit, subunit = _UNITS.get(currency.name, (currency.currency_unit_label or currency.name,
                                               currency.currency_subunit_label or ""))
    text = f"{uz_number_words(int(integral))} {unit}"
    if fractional and int(fractional):
        text += f" {int(fractional):02d} {subunit}".rstrip()
    return text[:1].upper() + text[1:]
