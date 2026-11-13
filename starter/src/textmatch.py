"""Text normalization shared by benchmark verification and retrieval evaluation."""
import re
import unicodedata

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalize_for_match(text: str) -> str:
    """Lowercase, NFKC, keep only [a-z0-9].

    PDF extraction keeps line-break hyphenation ("regula- tory"), curly quotes and
    irregular spaces ("AI RMF,risk"). Dropping every non-alphanumeric character makes
    an evidence quote match its source regardless of those artefacts.
    """
    text = unicodedata.normalize("NFKC", text).lower()
    return _NON_ALNUM.sub("", text)


def contains_evidence(chunk_text: str, evidence_quote: str) -> bool:
    """True when the whole evidence quote appears in the chunk (after normalization)."""
    needle = normalize_for_match(evidence_quote)
    return bool(needle) and needle in normalize_for_match(chunk_text)
