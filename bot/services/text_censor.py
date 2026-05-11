"""
Service for censoring racist or hateful strings on web surfaces.
"""

from __future__ import annotations

import re


class TextCensorService:
    """Replace matched hateful strings with a safe placeholder."""

    CENSORED_TEXT = "******"

    _LEETSPEAK_TRANSLATION = str.maketrans(
        {
            "0": "o",
            "1": "i",
            "3": "e",
            "4": "a",
            "5": "s",
            "7": "t",
            "@": "a",
            "$": "s",
        }
    )

    _RAW_PATTERNS = (
        re.compile(r"\bjews?\s+did\s+9\s*/?\s*11\b", re.IGNORECASE),
        re.compile(
            r"\b(?:i\s+hate|hate|kill)\s+(?:all\s+)?"
            r"(?:jews?|blacks?|black\s+people|mexicans?|muslims?|asians?|arabs?|indians?)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\bnig[\W_]+[a-z0-9][\w-]*", re.IGNORECASE),
        re.compile(r"\bn[e3]gr[o0](?:e?s)?\b", re.IGNORECASE),
    )

    _NORMALIZED_SUBSTRINGS = (
        "nigga",
        "nigger",
        "niggas",
        "niggers",
        "chink",
        "gook",
        "kike",
        "spic",
        "wetback",
        "jewsdid911",
        "ihatejew",
        "killalljew",
        "killjew",
    )

    def censor_text(self, text: str | None) -> str | None:
        """
        Return a placeholder when the text matches hateful content rules.

        Args:
            text: Candidate text to inspect.

        Returns:
            The original text when it is allowed, otherwise `******`.
        """
        if text is None:
            return None

        candidate = str(text)
        if self._matches_hateful_content(candidate):
            return self.CENSORED_TEXT
        return text

    def censor_username(self, username: str | None) -> str | None:
        """
        Return a placeholder for any username shown on web surfaces.

        Args:
            username: Candidate username to mask.

        Returns:
            The shared placeholder when a username exists, otherwise None.
        """
        if username is None:
            return None
        if not str(username).strip():
            return username
        return self.CENSORED_TEXT

    def _matches_hateful_content(self, text: str) -> bool:
        """Check whether a string should be censored."""
        if not text.strip():
            return False

        if any(pattern.search(text) for pattern in self._RAW_PATTERNS):
            return True

        normalized = self._normalize_text(text)
        return any(token in normalized for token in self._NORMALIZED_SUBSTRINGS)

    def _normalize_text(self, text: str) -> str:
        """Normalize text for forgiving hateful-content matching."""
        lowered = text.lower().translate(self._LEETSPEAK_TRANSLATION)
        return re.sub(r"[^a-z0-9]+", "", lowered)
