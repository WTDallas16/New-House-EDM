from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceSpec:
    name: str
    project_dir: Path
    output_path: Path
    args: list[str]
    api_source: bool = False


@dataclass(frozen=True, slots=True)
class SourceResult:
    name: str
    output_path: Path
    success: bool
    returncode: int


@dataclass(slots=True)
class ResolvedTrack:
    rank: int
    ranking_score: float
    artist: str
    title: str
    source_names: list[str]
    source_record: dict[str, Any]
    spotify_url: str | None = None
    spotify_uri: str | None = None
    spotify_id: str | None = None
    soundcloud_url: str | None = None
    soundcloud_track_id: str | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "ranking_score": self.ranking_score,
            "artist": self.artist,
            "track_or_project_title": self.title,
            "source_names": self.source_names,
            "spotify_url": self.spotify_url,
            "spotify_uri": self.spotify_uri,
            "spotify_id": self.spotify_id,
            "soundcloud_url": self.soundcloud_url,
            "soundcloud_track_id": self.soundcloud_track_id,
            "notes": self.notes,
            "source_record": self.source_record,
        }

