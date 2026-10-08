"""Texte pour un terminal ou une ligne d'erreur."""
from __future__ import annotations

import re

#: Caractères de contrôle C0, DEL et C1.
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def clean(text: str) -> str:
    """Caractères de contrôle (tabulation, fin de ligne, séquences ANSI/OSC) remplacés par leur
    échappement \\xNN."""
    return CONTROL_RE.sub(lambda m: "\\x%02x" % ord(m.group()), text)
