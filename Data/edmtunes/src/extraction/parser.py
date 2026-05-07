from __future__ import annotations

import logging
import re

from src.extraction.classifier import classify_article
from src.extraction.normalize import clean_text
from src.models import ArticleCard, ArticleEnrichment, ReleaseCandidate

LOGGER = logging.getLogger(__name__)

QUOTE_CHARS = "'\"‘’“”"
QUOTE_PATTERN = (
    r"(?P<title>"
    r"\"[^\"]{2,160}\""
    r"|'(?:[^']|'(?=[A-Za-z])){2,160}'"
    r"|“[^”]{2,160}”"
    r"|‘[^‘]{2,160}’(?![A-Za-z])"
    r")"
)

TITLE_PATTERNS: list[tuple[str, str]] = [
    (
        "regex",
        rf"^(?P<artist>.+?)\s+(?:releases?|drops?|unveils?|reveals?|unleash(?:es)?|delivers?|presents?|shares?|returns with|returns .*? with|extends .*? with|starts? .*? with|goes .*? with|gets .*? with|channels|continues .*? with|enlists? .+? for|details .*? and shares?|announces .*? and unveils?|announces .*?,\s*unveils?|joins? .*? with|joins? forces .*? (?:for|on|with)|teams up .*? (?:for|on|with)|collaborates .*? (?:for|on|with)|collides?\s+(?:for|on|with)|collides? .*? (?:for|on|with)|unites?\s+on|reunites?\s+for|provides? .*? in).+?{QUOTE_PATTERN}",
    ),
    (
        "regex",
        rf"^(?P<artist>.+?)\s+(?:re[- ]?imagines|remixes?|flips?|reworks?)\s+(?:.*?\s+)?{QUOTE_PATTERN}",
    ),
    (
        "regex",
        rf"^(?P<artist>.+?)\s+.+?\b(?:single|track|ep|album|anthem|release|remix|rework)[,:]?\s+{QUOTE_PATTERN}",
    ),
    (
        "regex",
        r"^(?P<artist>.+?)\s+[–-]\s+(?P<title>.+?)(?:\s+\[.*?\])?(?::\s*Listen)?$",
    ),
    (
        "regex",
        rf"^(?P<artist>.+?):\s+{QUOTE_PATTERN}$",
    ),
    (
        "regex",
        r"^(?P<artist>.+?)\s+(?:returns .*? with|releases?|drops?|unveils?|reveals?)\s+(?:new|latest|newest|debut)?\s*(?:single|track|EP|album)\s+(?P<title>[A-Z0-9][A-Z0-9 &+\-:'.!?]{2,})$",
    ),
    (
        "regex",
        r"^(?P<artist>.+?)\s+(?:unveils?|releases?|drops?|shares?)\s+(?:new|latest|newest|debut)?\s*(?:single|track|EP|album),?\s+(?P<title>[A-Z0-9][A-Z0-9 &+\-:'.!?]{2,})$",
    ),
    (
        "regex",
        rf"^(?P<artist>.+?)\s+(?:makes? .*? debut with|collaborates? on|link up on|links? up on).+?{QUOTE_PATTERN}",
    ),
    (
        "regex",
        rf"^(?P<artist>.+?)\s+goes\s+{QUOTE_PATTERN}\s+on\s+new\s+single\b",
    ),
]

BODY_PATTERNS = [
    rf"\b(?:single|track|song|release)\s+(?:titled|called|entitled)\s+{QUOTE_PATTERN}",
    rf"\bnew\s+(?:single|track|song|release)\s+{QUOTE_PATTERN}",
    rf"\breleased\s+{QUOTE_PATTERN}",
    rf"\bEP\s+(?:titled|called|entitled)?\s*{QUOTE_PATTERN}",
    rf"\balbum\s+(?:titled|called|entitled)?\s*{QUOTE_PATTERN}",
    rf"\bremix\s+of\s+{QUOTE_PATTERN}",
]

RELEASE_TYPE_PATTERNS = [
    ("remix", r"\bremix(?:es|ed)?\b"),
    ("rework", r"\brework(?:s|ed)?\b|re[- ]?imagines"),
    ("EP", r"\bEP\b"),
    ("album", r"\balbum\b"),
    ("single", r"\bsingle\b"),
    ("track", r"\btrack\b|\bcut\b|\bsong\b"),
]

TRAILING_NOISE_RE = re.compile(
    r"\s*(?::\s*Listen|\|\s*.*$|\s+-\s+(?:We Rave You|EDMTunes).*$|\s+\[[^\]]+\])\s*$",
    re.IGNORECASE,
)


def infer_release_type(text: str, project_title: str | None = None) -> str:
    if project_title:
        title_position = text.lower().find(project_title.lower())
        if title_position >= 0:
            start = max(0, title_position - 100)
            end = min(len(text), title_position + len(project_title) + 40)
            nearby_text = text[start:end]
            nearby_specific = [
                ("single", r"\bnew\s+single\b|\bsingle\s+[\"'‘“]"),
                ("track", r"\bnew\s+track\b|\btrack\s+[\"'‘“]|\bcut\s+on\b"),
                ("EP", r"\bnew\s+EP\b|\bEP\s+[\"'‘“]|[\"'‘“][^\"'‘’“”]+ EP[\"'’”]"),
                ("album", r"\bnew\s+album\b|\balbum\s+[\"'‘“]|[\"'‘“][^\"'‘’“”]+ album[\"'’”]"),
                ("remix", r"\bnew\s+remix\b|\bremix\b"),
                ("rework", r"\brework\b|re[- ]?imagines"),
            ]
            for release_type, pattern in nearby_specific:
                if re.search(pattern, nearby_text, re.IGNORECASE):
                    return release_type
            for release_type, pattern in RELEASE_TYPE_PATTERNS:
                if re.search(pattern, nearby_text, re.IGNORECASE):
                    return release_type
            return "unknown"

    for release_type, pattern in RELEASE_TYPE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return release_type
    return "unknown"


def clean_article_title(title: str) -> str:
    return clean_text(TRAILING_NOISE_RE.sub("", title))


def _clean_extracted_title(title: str) -> str:
    title = TRAILING_NOISE_RE.sub("", title)
    return clean_text(title.strip(QUOTE_CHARS))


def extract_from_title(title: str) -> tuple[str, str, str] | None:
    clean_title = clean_article_title(title)
    for method, pattern in TITLE_PATTERNS:
        match = re.search(pattern, clean_title, re.IGNORECASE)
        if not match:
            continue
        artist = clean_text(match.group("artist"))
        raw_title = match.group("title")
        if re.match(r"^\s*(?:and\s+announces?|announces?)\b", raw_title, re.IGNORECASE):
            continue
        extracted_title = _clean_extracted_title(raw_title)
        if artist and extracted_title:
            return artist, extracted_title, method
    return None


def extract_title_from_body(body_text: str) -> str | None:
    for pattern in BODY_PATTERNS:
        match = re.search(pattern, body_text, re.IGNORECASE)
        if match:
            return _clean_extracted_title(match.group("title"))
    return None


def _artist_from_og(open_graph: dict[str, str]) -> str | None:
    site_title = open_graph.get("og:title") or open_graph.get("twitter:title")
    if not site_title:
        return None
    parsed = extract_from_title(site_title)
    return parsed[0] if parsed else None


def _parsed_from_metadata(open_graph: dict[str, str]) -> tuple[str, str, str] | None:
    for key in ("og:title", "twitter:title"):
        title = open_graph.get(key)
        if not title:
            continue
        parsed = extract_from_title(title)
        if parsed:
            return parsed[0], parsed[1], "article_metadata"
    return None


def score_candidate(
    article: ArticleCard,
    enrichment: ArticleEnrichment | None,
    base_score: float | None = None,
) -> float:
    classification = classify_article(article.title, article.snippet)
    score = classification.confidence_score if base_score is None else base_score
    if enrichment and enrichment.embedded_music_links:
        score += 0.20
    if enrichment and enrichment.body_release_matches:
        score += 0.10
    return max(0.0, min(score, 1.0))


def parse_release_candidate(
    article: ArticleCard,
    enrichment: ArticleEnrichment | None = None,
) -> ReleaseCandidate | None:
    classification = classify_article(article.title, article.snippet)
    if not classification.release_article:
        return None

    parsed = extract_from_title(article.title)
    extraction_method = "regex"
    if parsed:
        artist, project_title, extraction_method = parsed
    else:
        metadata_parsed = _parsed_from_metadata(enrichment.open_graph) if enrichment else None
        if metadata_parsed:
            artist, project_title, extraction_method = metadata_parsed
        else:
            project_title = None
            artist = _artist_from_og(enrichment.open_graph) if enrichment else None
            if enrichment and artist:
                project_title = extract_title_from_body(enrichment.body_text)
                extraction_method = "article_body"
            if not project_title:
                LOGGER.info("Could not extract release title from %r", article.title)
                return None
    if not artist or not project_title:
        return None
    if re.match(r"^(?:and\s+announces?|announces?)\b", project_title, re.IGNORECASE):
        LOGGER.info("Skipping ambiguous announced project title from %r", article.title)
        return None

    evidence_text = " ".join(
        part
        for part in [
            article.title,
            article.snippet or "",
            enrichment.body_text if enrichment else "",
        ]
        if part
    )
    release_type = infer_release_type(evidence_text, project_title)
    if extraction_method == "regex" and enrichment and enrichment.embedded_music_links:
        extraction_method = "regex+embedded_player"

    return ReleaseCandidate(
        artist=artist,
        track_or_project_title=project_title,
        release_type=release_type,
        confidence_score=score_candidate(article, enrichment, classification.confidence_score),
        extraction_method=extraction_method,
        source_article_title=article.title,
        source_article_url=article.url,
        source_name=article.source_name,
        article_date=article.publish_date,
        embedded_music_links=enrichment.embedded_music_links if enrichment else [],
        open_graph=enrichment.open_graph if enrichment else {},
    )
