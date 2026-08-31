"""Kleine Template-Hilfen für die Web-Statistik."""

import json

from django.template import Library
from django.utils.safestring import mark_safe

register = Library()


@register.filter
def safe_json(wert):
    """Gibt Python-Daten als JSON für ein <script>-Element aus.

    json.dumps allein reicht nicht: Ein "</script>" in den Daten würde das
    Skript vorzeitig beenden. Deshalb werden die kritischen Zeichen maskiert.
    """
    text = json.dumps(wert, ensure_ascii=False)
    return mark_safe(text.replace("<", "\\u003c")
                         .replace(">", "\\u003e")
                         .replace("&", "\\u0026"))
