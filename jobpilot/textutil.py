"""Small text helpers shared by the connectors and the renderers."""

from __future__ import annotations

import html
import re
import unicodedata

_TAG = re.compile(r"<[^>]+>")
_BLOCK_END = re.compile(r"</(p|div|li|ul|ol|h[1-6]|tr|table|section)>", re.IGNORECASE)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_LI = re.compile(r"<li[^>]*>", re.IGNORECASE)
_WS = re.compile(r"[ \t\r\f\v]+")
_BLANKS = re.compile(r"\n{3,}")


def strip_html(raw: str) -> str:
    """HTML job descriptions -> readable plain text with bullets preserved."""
    if not raw:
        return ""
    text = _BR.sub("\n", raw)
    text = _LI.sub("\n- ", text)
    text = _BLOCK_END.sub("\n", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    text = "\n".join(_WS.sub(" ", line).strip() for line in text.splitlines())
    return _BLANKS.sub("\n\n", text).strip()


def slugify(text: str) -> str:
    out = [c.lower() if c.isalnum() else "-" for c in (text or "")]
    return re.sub(r"-{2,}", "-", "".join(out)).strip("-") or "item"


def truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def first_sentence(text: str, limit: int = 220) -> str:
    text = " ".join((text or "").split())
    if not text:
        return ""
    m = re.search(r"(?<=[.!?])\s", text)
    return truncate(text[: m.start() + 1] if m else text, limit)
