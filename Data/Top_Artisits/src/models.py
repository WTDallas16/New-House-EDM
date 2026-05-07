from __future__ import annotations

from dataclasses import asdict, dataclass, field


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
    article_date: str
    ranking_score: float = 0.0
    ranking_factors: dict[str, object] = field(default_factory=dict)
    embedded_music_links: list[str] = field(default_factory=list)
    open_graph: dict[str, str] = field(default_factory=dict)
    release_article: bool = True

    def as_dict(self) -> dict:
        return asdict(self)
