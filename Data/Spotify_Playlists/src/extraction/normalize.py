from __future__ import annotations

import re
import unicodedata

from src.models import ReleaseCandidate


def clean_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \t\r\n,;:-")


def normalize_key_part(value: str) -> str:
    value = clean_text(value).lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"&", " and ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def dedupe_key(candidate: ReleaseCandidate) -> tuple[str, str, str]:
    return (
        normalize_key_part(candidate.artist),
        normalize_key_part(candidate.track_or_project_title),
        normalize_key_part(candidate.release_type),
    )


def dedupe_releases(candidates: list[ReleaseCandidate]) -> list[ReleaseCandidate]:
    by_key: dict[tuple[str, str, str], ReleaseCandidate] = {}
    for candidate in candidates:
        key = dedupe_key(candidate)
        current = by_key.get(key)
        if current is None or candidate.confidence_score > current.confidence_score:
            by_key[key] = candidate
    return list(by_key.values())
