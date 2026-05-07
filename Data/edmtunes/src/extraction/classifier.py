from __future__ import annotations

import logging
import re

from src.models import ClassificationResult

LOGGER = logging.getLogger(__name__)

RELEASE_KEYWORDS = [
    "new single",
    "new track",
    "new ep",
    "new album",
    "new remix",
    "latest single",
    "latest album",
    "newest single",
    "newest album",
    "debut single",
    "debut album",
    "debut ep",
    "single",
    "track",
    "ep",
    "album",
    "remix",
    "rework",
    "release",
    "releases",
    "released",
    "drops",
    "delivers",
    "unveils",
    "reveals",
    "unleashes",
    "present",
    "presents",
    "shares",
    "returns with",
    "joins forces",
    "join forces",
    "joins",
    "teams up",
    "collaborates",
    "collide for",
    "collides for",
    "unite on",
    "unites on",
    "reunite for",
    "reunites for",
    "listen",
]

EXCLUDE_KEYWORDS = [
    "festival",
    "lineup",
    "line-up",
    "tour",
    "residency",
    "interview",
    "anniversary",
    "turns",
    "years old",
    "dies",
    "dead",
    "lawsuit",
    "legal",
    "announces",
    "ranking",
    "ranked",
    "best of",
    "gear",
    "plugin",
    "business",
    "industry",
    "classic",
    "playlist",
    "radio show",
    "live set",
    "livestream",
    "live stream",
    "watch",
    "teases",
]

CLEAR_DROP_PATTERNS = [
    r"\b(?:drops?|dropped|releases?|released|delivers?|unveils?|reveals?|unleash(?:es)?|presents?|shares?|returns with|unites? on|reunites? for|joins? .*? with)\b",
    r"\bnew\s+(?:single|track|ep|album|remix|rework)\b",
    r"\b(?:latest|newest)\s+(?:single|track|ep|album|remix|rework)\b",
    r"\b(?:single|track|ep|album|remix|rework)\s+[\"'‘“]",
]

CONCRETE_RELEASE_VERB_RE = re.compile(
    r"\b(?:drops?|dropped|releases?|released|delivers?|unveils?|reveals?|presents?|shares?|returns with)\b",
    re.IGNORECASE,
)

QUOTE_RE = re.compile(r"[\"'‘’“”][^\"'‘’“”]{2,120}[\"'‘’“”]")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def has_quoted_title(text: str) -> bool:
    return bool(QUOTE_RE.search(text))


def find_signals(text: str, keywords: list[str]) -> list[str]:
    normalized = normalize_text(text)
    signals = []
    for keyword in keywords:
        pattern = r"(?<!\w)" + re.escape(keyword.lower()) + r"(?!\w)"
        if re.search(pattern, normalized):
            signals.append(keyword)
    return signals


def is_clearly_dropped_release(text: str) -> bool:
    normalized = normalize_text(text)
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in CLEAR_DROP_PATTERNS)


def classify_article(title: str, snippet: str | None = None) -> ClassificationResult:
    combined = " ".join(part for part in [title, snippet or ""] if part)
    title_norm = normalize_text(title)
    include_signals = find_signals(combined, RELEASE_KEYWORDS)
    exclusion_signals = find_signals(combined, EXCLUDE_KEYWORDS)
    clearly_dropped = is_clearly_dropped_release(combined)
    has_concrete_release_verb = bool(CONCRETE_RELEASE_VERB_RE.search(combined))
    quoted = has_quoted_title(combined)

    score = 0.0
    if title_norm.startswith("[watch]") or title_norm.startswith("watch "):
        return ClassificationResult(
            release_article=False,
            confidence_score=0.0,
            include_signals=include_signals,
            exclusion_signals=list(dict.fromkeys(exclusion_signals + ["watch"])),
            clearly_dropped_release=clearly_dropped,
        )
    if ": listen" in title_norm or title_norm.endswith(" listen"):
        score += 0.25
    if include_signals:
        score += 0.25
    if quoted:
        score += 0.20
    if clearly_dropped:
        score += 0.15
    if exclusion_signals and not clearly_dropped:
        score -= 0.30

    score = max(0.0, min(score, 1.0))
    release_article = bool(include_signals) and score >= 0.30
    if exclusion_signals and not clearly_dropped:
        release_article = False
    if "announces" in exclusion_signals and not has_concrete_release_verb:
        release_article = False
        score = min(score, 0.25)

    LOGGER.debug(
        "classified title=%r release=%s score=%.2f include=%s exclude=%s",
        title,
        release_article,
        score,
        include_signals,
        exclusion_signals,
    )
    return ClassificationResult(
        release_article=release_article,
        confidence_score=score,
        include_signals=include_signals,
        exclusion_signals=exclusion_signals,
        clearly_dropped_release=clearly_dropped,
    )


def is_release_article(title: str, snippet: str | None = None) -> bool:
    return classify_article(title, snippet).release_article
