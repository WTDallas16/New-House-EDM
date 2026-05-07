from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.models import ResolvedTrack
from src.normalize import normalize_text, normalize_title
from src.soundcloud_tools import (
    SoundCloudTools,
    soundcloud_artist_score,
    soundcloud_candidate_artists,
    soundcloud_identity_artists,
    soundcloud_title_score,
    soundcloud_track_is_in_window,
)
from src.spotify_tools import SpotifyRateLimited, SpotifyTools, write_spotify_backlog

LOGGER = logging.getLogger(__name__)


def resolve_top_tracks(
    records: list[dict[str, Any]],
    top_n: int,
    data_root: Path,
    cache_path: Path,
    backlog_path: Path,
    resolve_spotify: bool = True,
    resolve_soundcloud: bool = True,
    lookback_days: int = 7,
) -> list[ResolvedTrack]:
    cache = load_cache(cache_path)
    spotify = SpotifyTools(data_root) if resolve_spotify else None
    soundcloud = SoundCloudTools(data_root) if resolve_soundcloud else None
    spotify_disabled = False
    spotify_backlog: list[dict[str, Any]] = []
    resolved: list[ResolvedTrack] = []

    for index, item in enumerate(records[:top_n], start=1):
        key = cache_key(item)
        cached = cache.get(key, {})
        track = ResolvedTrack(
            rank=index,
            ranking_score=float(item.get("ranking_score") or 0),
            artist=str(item.get("artist") or ""),
            title=str(item.get("track_or_project_title") or ""),
            source_names=list(item.get("cross_source_sources") or [item.get("source_name") or ""]),
            source_record=item,
            spotify_url=cached.get("spotify_url"),
            spotify_uri=cached.get("spotify_uri"),
            spotify_id=cached.get("spotify_id"),
            soundcloud_url=cached.get("soundcloud_url"),
            soundcloud_track_id=cached.get("soundcloud_track_id"),
        )
        if track.soundcloud_track_id and soundcloud and not cached_soundcloud_match_is_trusted(item, soundcloud, track, lookback_days=lookback_days):
            track.notes.append("discarded_untrusted_cached_soundcloud_match")
            track.soundcloud_track_id = None
            track.soundcloud_url = None
        if track.spotify_id and not cached_spotify_match_is_trusted(cached):
            track.notes.append("discarded_legacy_cached_spotify_match")
            track.spotify_id = None
            track.spotify_uri = None
            track.spotify_url = None

        if spotify and not spotify_disabled and not track.spotify_uri:
            try:
                spotify_match = spotify.resolve_track(item, lookback_days=lookback_days)
                track.spotify_id = spotify_match.get("spotify_id")
                track.spotify_uri = spotify_match.get("spotify_uri")
                track.spotify_url = spotify_match.get("spotify_url")
            except SpotifyRateLimited as exc:
                spotify_disabled = True
                retry_after = exc.retry_after
                track.notes.append("spotify_resolution_rate_limited")
                spotify_backlog.append(backlog_entry(item, retry_after))
                LOGGER.warning("Spotify rate limited while resolving links; remaining missing Spotify links will be logged for later.")
        elif spotify_disabled and not track.spotify_uri:
            spotify_backlog.append(backlog_entry(item, None))
            track.notes.append("spotify_resolution_deferred")

        if soundcloud and not track.soundcloud_track_id:
            sc_match = soundcloud.resolve_track(item, lookback_days=lookback_days)
            track.soundcloud_track_id = sc_match.get("soundcloud_track_id")
            track.soundcloud_url = sc_match.get("soundcloud_url")

        cache[key] = {
            "spotify_url": track.spotify_url,
            "spotify_uri": track.spotify_uri,
            "spotify_id": track.spotify_id,
            "spotify_match_version": "strict_v3_date_checked" if track.spotify_id else None,
            "soundcloud_url": track.soundcloud_url,
            "soundcloud_track_id": track.soundcloud_track_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        resolved.append(track)

    write_cache(cache_path, cache)
    write_spotify_backlog(backlog_path, spotify_backlog)
    return resolved


def cached_soundcloud_match_is_trusted(item: dict[str, Any], soundcloud: SoundCloudTools, track: ResolvedTrack, lookback_days: int = 7) -> bool:
    artist = str(item.get("artist") or "")
    title = str(item.get("track_or_project_title") or "")
    target_artists = [normalize_text(alias) for alias in artist.split(",") if alias.strip()] or [normalize_text(artist)]
    target_title = normalize_title(title)
    try:
        payload = soundcloud.get(f"/tracks/{track.soundcloud_track_id}")
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Could not validate cached SoundCloud match for %s - %s: %s", track.artist, track.title, exc)
        return False
    candidate_artists = soundcloud_candidate_artists(payload)
    identity_artists = soundcloud_identity_artists(payload)
    candidate_title = normalize_title(payload.get("title"))
    candidate_all = normalize_text(f"{' '.join(candidate_artists)} {payload.get('title') or ''}")
    title_ok = soundcloud_title_score(target_title, candidate_title, candidate_all) >= 0.72
    artist_ok = soundcloud_artist_score(target_artists, candidate_artists, candidate_all) >= 0.72
    identity_ok = soundcloud_artist_score(target_artists, identity_artists, candidate_all) >= 0.72
    current_day = date.today()
    date_ok = soundcloud_track_is_in_window(payload, cutoff=current_day - timedelta(days=lookback_days), current_day=current_day)
    return title_ok and artist_ok and identity_ok and date_ok


def cached_spotify_match_is_trusted(cached: dict[str, Any]) -> bool:
    return cached.get("spotify_match_version") == "strict_v3_date_checked"


def cache_key(item: dict[str, Any]) -> str:
    open_graph = item.get("open_graph") or {}
    for field in ("spotify_track_id", "isrc", "soundcloud_track_id"):
        value = str(open_graph.get(field) or "").strip()
        if value:
            return f"{field}:{value}"
    artist = normalize_text(item.get("artist"))
    title = normalize_title(item.get("track_or_project_title"))
    return f"text:{artist}|{title}"


def backlog_entry(item: dict[str, Any], retry_after: int | None) -> dict[str, Any]:
    return {
        "artist": item.get("artist"),
        "track_or_project_title": item.get("track_or_project_title"),
        "ranking_score": item.get("ranking_score"),
        "retry_after_seconds": retry_after,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "source_record": item,
    }


def load_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def write_resolved(path: Path, tracks: list[ResolvedTrack]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump([track.as_dict() for track in tracks], handle, indent=2, ensure_ascii=False)
        handle.write("\n")
