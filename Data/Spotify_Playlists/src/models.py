from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ReleaseCandidate:
    artist: str
    track_or_project_title: str
    release_type: str
    confidence_score: float
    extraction_method: str
    source_article_title: str
    source_article_url: str
    source_name: str
    article_date: str | None = None
    embedded_music_links: list[str] = field(default_factory=list)
    open_graph: dict[str, str] = field(default_factory=dict)
    release_article: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "artist": self.artist,
            "track_or_project_title": self.track_or_project_title,
            "release_type": self.release_type,
            "confidence_score": round(self.confidence_score, 3),
            "extraction_method": self.extraction_method,
            "source_article_title": self.source_article_title,
            "source_article_url": self.source_article_url,
            "source_name": self.source_name,
            "article_date": self.article_date,
            "embedded_music_links": self.embedded_music_links,
            "open_graph": self.open_graph,
            "release_article": self.release_article,
        }
