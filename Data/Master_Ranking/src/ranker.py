from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

DEFAULT_INPUTS = [
    "../weraveyou/data/extracted_releases_v3.json",
    "../edmtunes/data/extracted_releases.json",
    "../edm.com/data/extracted_releases.json",
    "../1001tracklists/data/extracted_releases.json",
    "../submithub/data/extracted_releases.json",
    "../Spotify_Playlists/data/extracted_releasesv2.json",
    "../SoundCloud_Playlists/data/extracted_releasesv3.json",
    "../Top_Artisits/data/master_recent_tracks_v2.json",
]

SOURCE_WEIGHTS = {
    "Spotify Artist Profile": 0.90,
    "SoundCloud Artist Profile": 0.82,
    "Spotify Playlist": 0.82,
    "SoundCloud Playlist": 0.76,
    "SubmitHub": 0.78,
    "We Rave You": 0.72,
    "EDMTunes": 0.72,
    "EDM.com": 0.72,
    "1001Tracklists": 0.88,
}


@dataclass(slots=True)
class LoadedRecord:
    item: dict[str, Any]
    source_path: str
    duplicate_key: str


def load_records(paths: list[Path]) -> list[LoadedRecord]:
    records: list[LoadedRecord] = []
    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict) or item.get("release_article") is False:
                continue
            key = duplicate_key(item)
            if not key:
                continue
            records.append(LoadedRecord(item=dict(item), source_path=str(path), duplicate_key=key))
    return records


def rank_records(records: list[LoadedRecord], today: date | None = None) -> list[dict[str, Any]]:
    current_day = today or date.today()
    groups = group_records(records)

    ranked: list[dict[str, Any]] = []
    for key, group in groups.items():
        duplicate_context = build_duplicate_context(group)
        for record in group:
            score, factors = calculate_score(record.item, duplicate_context, today=current_day)
            item = dict(record.item)
            item["ranking_score"] = score
            item["ranking_factors"] = factors
            item["duplicate_group_key"] = key
            item["cross_source_duplicate_count"] = duplicate_context["duplicate_count"]
            item["cross_source_sources"] = duplicate_context["sources"]
            item["cross_source_source_count"] = len(duplicate_context["sources"])
            item["source_file"] = record.source_path
            ranked.append(item)

    ranked.sort(key=lambda item: item.get("ranking_score") or 0, reverse=True)
    return ranked


def group_records(records: list[LoadedRecord]) -> dict[str, list[LoadedRecord]]:
    parent = list(range(len(records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    alias_owner: dict[str, int] = {}
    aliases_by_index: list[list[str]] = []
    for index, record in enumerate(records):
        aliases = duplicate_aliases(record.item)
        aliases_by_index.append(aliases)
        for alias in aliases:
            if alias in alias_owner:
                union(index, alias_owner[alias])
            else:
                alias_owner[alias] = index

    grouped_indexes: dict[int, list[int]] = defaultdict(list)
    for index in range(len(records)):
        grouped_indexes[find(index)].append(index)

    groups: dict[str, list[LoadedRecord]] = {}
    for indexes in grouped_indexes.values():
        aliases = sorted({alias for index in indexes for alias in aliases_by_index[index]})
        key = preferred_group_key(aliases)
        groups[key] = [records[index] for index in indexes]
    return groups


def unique_records(ranked_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[str, dict[str, Any]] = {}
    for item in ranked_records:
        key = str(item.get("duplicate_group_key") or "")
        if not key:
            continue
        current = best_by_key.get(key)
        if current is None or (item.get("ranking_score") or 0) > (current.get("ranking_score") or 0):
            best_by_key[key] = item
    return sorted(best_by_key.values(), key=lambda item: item.get("ranking_score") or 0, reverse=True)


def calculate_score(item: dict[str, Any], duplicate_context: dict[str, Any], today: date | None = None) -> tuple[float, dict[str, Any]]:
    current_day = today or date.today()
    open_graph = item.get("open_graph") or {}
    source_name = str(item.get("source_name") or "")
    article_date = parse_date(item.get("article_date"))
    age_days = max((current_day - article_date).days, 0) if article_date else None

    existing_score = parse_float(item.get("ranking_score"))
    confidence = bounded(parse_float(item.get("confidence_score")), 1)
    source_quality = SOURCE_WEIGHTS.get(source_name, 0.65)
    recency = recency_score(age_days, lookback_days=21)
    music_link = 1.0 if item.get("embedded_music_links") else 0.0
    platform_popularity = platform_popularity_score(open_graph)
    source_chart = source_chart_score(open_graph, source_name)
    duplicate = duplicate_score(duplicate_context)

    components = {
        "existing_source_ranking": bounded(existing_score, 100),
        "confidence": confidence,
        "source_quality": source_quality,
        "recency": recency,
        "music_link": music_link,
        "platform_popularity": platform_popularity,
        "source_chart": source_chart,
        "cross_source_duplicates": duplicate,
    }
    weights = {
        "existing_source_ranking": 0.20 if existing_score is not None else 0.0,
        "confidence": 0.12,
        "source_quality": 0.10,
        "recency": 0.12,
        "music_link": 0.06,
        "platform_popularity": 0.18 if has_platform_values(open_graph) else 0.0,
        "source_chart": 0.12 if has_chart_values(open_graph, source_name) else 0.0,
        "cross_source_duplicates": 0.20,
    }
    available_weight = sum(weights[key] for key in weights)
    weighted = sum(components[key] * weights[key] for key in components)
    score = round((weighted / available_weight) * 100, 2) if available_weight else 0.0
    return min(score, 100.0), {
        "score_version": "cross_source_v1",
        "score_description": (
            "0-100 score using source confidence, source quality, recency, embedded links, "
            "available platform/chart popularity signals, existing source ranking when present, "
            "and a boost for repeated sightings across independent sources."
        ),
        "weights": weights,
        "available_weight": round(available_weight, 4),
        "raw": {
            "source_name": source_name,
            "existing_source_ranking": existing_score,
            "confidence_score": parse_float(item.get("confidence_score")),
            "article_date": item.get("article_date"),
            "release_age_days": age_days,
            "platform_values": platform_raw_values(open_graph),
            "source_chart_values": chart_raw_values(open_graph),
            "duplicate_count": duplicate_context["duplicate_count"],
            "source_count": len(duplicate_context["sources"]),
            "sources": duplicate_context["sources"],
        },
        "components": {key: round(value, 4) for key, value in components.items()},
    }


def build_duplicate_context(group: list[LoadedRecord]) -> dict[str, Any]:
    sources = sorted({str(record.item.get("source_name") or record.source_path) for record in group})
    return {
        "duplicate_count": len(group),
        "sources": sources,
        "source_files": sorted({record.source_path for record in group}),
    }


def duplicate_score(context: dict[str, Any]) -> float:
    duplicate_count = int(context["duplicate_count"])
    source_count = len(context["sources"])
    count_score = min(max(duplicate_count - 1, 0) / 4, 1.0)
    source_score = min(max(source_count - 1, 0) / 3, 1.0)
    return (count_score * 0.35) + (source_score * 0.65)


def platform_popularity_score(open_graph: dict[str, Any]) -> float:
    values = platform_raw_values(open_graph)
    scores: list[float] = []
    if values["spotify_track_popularity"] is not None:
        scores.append(bounded(values["spotify_track_popularity"], 100))
    if values["spotify_popularity"] is not None:
        scores.append(bounded(values["spotify_popularity"], 100))
    if values["soundcloud_playback_count"] is not None:
        scores.append(log_score(values["soundcloud_playback_count"], ceiling=1_000_000))
    if values["soundcloud_likes_count"] is not None:
        scores.append(log_score(values["soundcloud_likes_count"], ceiling=50_000))
    if values["soundcloud_reposts_count"] is not None:
        scores.append(log_score(values["soundcloud_reposts_count"], ceiling=5_000))
    return max(scores) if scores else 0.0


def source_chart_score(open_graph: dict[str, Any], source_name: str) -> float:
    values = chart_raw_values(open_graph)
    scores: list[float] = []
    if source_name == "SubmitHub":
        if values["popular_points"] is not None:
            scores.append(bounded(values["popular_points"], 100))
        if values["hot_or_not_likes"] is not None:
            scores.append(bounded(values["hot_or_not_likes"], 100))
        if values["chart_rank"] is not None:
            scores.append(rank_score(values["chart_rank"], max_rank=100))
    if source_name == "1001Tracklists" and values["chart_rank"] is not None:
        scores.append(rank_score(values["chart_rank"], max_rank=30))
    if values["playlist_track_count"] is not None:
        scores.append(0.55)
    return max(scores) if scores else 0.0


def duplicate_key(item: dict[str, Any]) -> str:
    aliases = duplicate_aliases(item)
    return preferred_group_key(aliases)


def duplicate_aliases(item: dict[str, Any]) -> list[str]:
    open_graph = item.get("open_graph") or {}
    aliases: list[str] = []
    spotify_track_id = clean_id(open_graph.get("spotify_track_id"))
    if spotify_track_id:
        aliases.append(f"spotify:{spotify_track_id}")
    isrc = clean_id(open_graph.get("isrc"))
    if isrc:
        aliases.append(f"isrc:{isrc.upper()}")
    soundcloud_track_id = clean_id(open_graph.get("soundcloud_track_id"))
    if soundcloud_track_id:
        aliases.append(f"soundcloud:{soundcloud_track_id}")

    artist = normalize_text(str(open_graph.get("all_artists") or item.get("artist") or ""))
    title = normalize_title(str(item.get("track_or_project_title") or ""))
    if artist and title:
        aliases.append(f"text:{artist}|{title}")
    return aliases


def preferred_group_key(aliases: list[str]) -> str:
    for prefix in ("spotify:", "isrc:", "soundcloud:", "text:"):
        for alias in aliases:
            if alias.startswith(prefix):
                return alias
    return aliases[0] if aliases else ""


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"\b(feat|ft|featuring|with|x)\b", " ", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_title(value: str) -> str:
    normalized = normalize_text(value)
    normalized = re.sub(r"\b(original mix|extended mix|radio edit|edit|club mix)\b", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def clean_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if not text or text.lower() == "none" else text


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        text = str(value).strip().replace(",", "")
        return float(text) if text else None
    except ValueError:
        return None


def bounded(value: float | None, ceiling: float) -> float:
    if value is None or value <= 0:
        return 0.0
    return min(value / ceiling, 1.0)


def log_score(value: float | None, ceiling: float) -> float:
    if value is None or value <= 0:
        return 0.0
    return min(math.log10(value + 1) / math.log10(ceiling + 1), 1.0)


def rank_score(rank: float | None, max_rank: int) -> float:
    if rank is None or rank <= 0:
        return 0.0
    return max(1.0 - ((rank - 1) / max_rank), 0.0)


def recency_score(age_days: int | None, lookback_days: int) -> float:
    if age_days is None:
        return 0.35
    return max(1.0 - (age_days / lookback_days), 0.0)


def platform_raw_values(open_graph: dict[str, Any]) -> dict[str, float | None]:
    return {
        "spotify_track_popularity": parse_float(open_graph.get("spotify_track_popularity")),
        "spotify_popularity": parse_float(open_graph.get("spotify_popularity")),
        "soundcloud_playback_count": parse_float(open_graph.get("playback_count")),
        "soundcloud_likes_count": parse_float(open_graph.get("likes_count")),
        "soundcloud_reposts_count": parse_float(open_graph.get("reposts_count")),
    }


def chart_raw_values(open_graph: dict[str, Any]) -> dict[str, float | None]:
    return {
        "chart_rank": parse_float(open_graph.get("chart_rank")),
        "popular_points": parse_float(open_graph.get("popular_points")),
        "hot_or_not_likes": parse_float(open_graph.get("hot_or_not_likes")),
        "playlist_track_count": parse_float(open_graph.get("playlist_track_count")),
    }


def has_platform_values(open_graph: dict[str, Any]) -> bool:
    return any(value is not None for value in platform_raw_values(open_graph).values())


def has_chart_values(open_graph: dict[str, Any], source_name: str) -> bool:
    values = chart_raw_values(open_graph)
    if source_name == "SubmitHub":
        return any(values[key] is not None for key in ("popular_points", "hot_or_not_likes", "chart_rank"))
    if source_name == "1001Tracklists":
        return values["chart_rank"] is not None
    return values["playlist_track_count"] is not None


def write_json(data: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
