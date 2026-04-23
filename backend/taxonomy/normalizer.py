"""
Text normalization utilities for taxonomy matching.
Preserves deterministic behavior and Vietnamese diacritic handling.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict


# =========================
# Vietnamese Mojibake Map
# =========================
# Legacy compatibility: maps common mojibake sequences to ASCII.
# This preserves behavior from the historical VIETNAMESE_MAP.

MOJIBAKE_MAP: Dict[str, str] = {
    # a
    "Ã ": "a", "Ã¡": "a", "áº£": "a", "Ã£": "a", "áº¡": "a",
    "Äƒ": "a", "áº±": "a", "áº¯": "a", "áº³": "a", "áºµ": "a", "áº·": "a",
    "Ã¢": "a", "áº§": "a", "áº¥": "a", "áº©": "a", "áº«": "a", "áº­": "a",
    # e
    "Ã¨": "e", "Ã©": "e", "áº»": "e", "áº½": "e", "áº¹": "e",
    "Ãª": "e", "á»": "e", "áº¿": "e", "á»ƒ": "e", "á»…": "e", "á»‡": "e",
    # i
    "Ã¬": "i", "Ã­": "i", "á»‰": "i", "Ä©": "i", "á»‹": "i",
    # o
    "Ã²": "o", "Ã³": "o", "á»": "o", "Ãµ": "o", "á»": "o",
    "Ã´": "o", "á»“": "o", "á»‘": "o", "á»•": "o", "á»—": "o", "á»™": "o",
    "Æ¡": "o", "á»": "o", "á»›": "o", "á»Ÿ": "o", "á»¡": "o", "á»£": "o",
    # u
    "Ã¹": "u", "Ãº": "u", "á»§": "u", "Å©": "u", "á»¥": "u",
    "Æ°": "u", "á»«": "u", "á»©": "u", "á»­": "u", "á»¯": "u", "á»±": "u",
    # y
    "á»³": "y", "Ã½": "y", "á»·": "y", "á»¹": "y", "á»µ": "y",
    # d
    "Ä‘": "d",
    # Uppercase
    "Ã€": "A", "Ã": "A", "áº¢": "A", "Ãƒ": "A", "áº ": "A",
    "Ä‚": "A", "áº°": "A", "áº®": "A", "áº²": "A", "áº´": "A", "áº¶": "A",
    "Ã‚": "A", "áº¦": "A", "áº¤": "A", "áº¨": "A", "áºª": "A", "áº¬": "A",
    "Ãˆ": "E", "Ã‰": "E", "áºº": "E", "áº¼": "E", "áº¸": "E",
    "ÃŠ": "E", "á»€": "E", "áº¾": "E", "á»‚": "E", "á»„": "E", "á»†": "E",
    "ÃŒ": "I", "Ã": "I", "á»ˆ": "I", "Ä¨": "I", "á»Š": "I",
    "Ã’": "O", "Ã“": "O", "á»Ž": "O", "Ã•": "O", "á»Œ": "O",
    "Ã”": "O", "á»’": "O", "á»": "O", "á»”": "O", "á»–": "O", "á»˜": "O",
    "Æ ": "O", "á»œ": "O", "á»š": "O", "á»ž": "O", "á» ": "O", "á»¢": "O",
    "Ã™": "U", "Ãš": "U", "á»¦": "U", "Å¨": "U", "á»¤": "U",
    "Æ¯": "U", "á»ª": "U", "á»¨": "U", "á»¬": "U", "á»®": "U", "á»°": "U",
    "á»²": "Y", "Ã": "Y", "á»¶": "Y", "á»¸": "Y", "á»´": "Y",
    "Ä": "D",
}


class TextNormalizer:
    """Normalization toolkit for matching."""

    _re_invalid = re.compile(r"[^0-9a-zA-Z\s\u00C0-\u1EF9]")
    _re_spaces = re.compile(r"\s+")

    def clean_text(self, text: str) -> str:
        if not text:
            return ""

        text = str(text).strip().lower()
        text = self._re_invalid.sub(" ", text)
        text = self._re_spaces.sub(" ", text)
        return text.strip()

    def _apply_mojibake_map(self, text: str) -> str:
        if not text:
            return ""

        out = []
        for ch in text:
            out.append(MOJIBAKE_MAP.get(ch, ch))
        return "".join(out)

    def strip_diacritics(self, text: str) -> str:
        if not text:
            return ""

        # Handle legacy mojibake before unicode normalization
        text = self._apply_mojibake_map(text)
        normalized = unicodedata.normalize("NFD", text)
        stripped = "".join(
            ch for ch in normalized
            if unicodedata.category(ch) != "Mn"
        )
        return stripped

    def normalize(self, text: str) -> str:
        """Normalize for matching: clean + remove diacritics."""
        cleaned = self.clean_text(text)
        return self.strip_diacritics(cleaned).lower()
