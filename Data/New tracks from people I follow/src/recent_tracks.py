from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from src.followed_artists import FollowedArtist, clean_text, read_followed_artists_csv
from src.models import ReleaseCandidate
from src.soundcloud_api import SoundCloudAPIClient

LOGGER = logging.getLogger(__name__)
SOURCE_NAME = "SoundCloud Followed Artist"


def fetch_recent_tracks_from_followed_artists(
    artists: list[FollowedArtist],
    client: SoundCloudAPIClient,
    lookback_days: int = 14,
    track_limit: int = 50,
    today: date | None = None,
) -> list[ReleaseCandidate]:
    current_day = today or date.today()
    cutoff = current_day - timedelta(days=lookback_days)
    candidates: list[ReleaseCandidate] = []
    seen_track_ids: set[str] = set()
    for artist in artists:
        if not artist.soundcloud_user_id:
            continue
        LOGGER.info("Checking followed SoundCloud artist %s", artist.artist_name)
        try:
            tracks = client.user_tracks(artist.soundcloud_user_id, limit=track_limit)
        except requests.RequestException as exc:
            LOGGER.warning("Track lookup failed for %s: %s", artist.artist_name, exc)
            continue
        for track in tracks:
            track_id = str(track.get("id") or "")
            if track_id and track_id in seen_track_ids:
                continue
            if not track_looks_like_release(track):
                continue
            release_date = track_release_date(track)
            if release_date is None or release_date < cutoff or release_date > current_day:
                continue
            candidate = candidate_from_track(artist, track, release_date, lookback_days, current_day)
            if candidate:
                candidates.append(candidate)
                if track_id:
                    seen_track_ids.add(track_id)
    candidates.sort(key=lambda item: item.ranking_score, reverse=True)
    return candidates


def fetch_recent_tracks_from_csv(
    csv_path: Path,
    client: SoundCloudAPIClient,
    lookback_days: int = 14,
    track_limit: int = 50,
) -> list[ReleaseCandidate]:
    return fetch_recent_tracks_from_followed_artists(
        read_followed_artists_csv(csv_path),
        client=client,
        lookback_days=lookback_days,
        track_limit=track_limit,
    )


def candidate_from_track(
    artist: FollowedArtist,
    track: dict[str, Any],
    release_date: date,
    lookback_days: int,
    today: date,
) -> ReleaseCandidate | None:
    artist_name, title = artist_and_title(track, artist.artist_name)
    if not artist_name or not title:
        return None
    track_url = str(track.get("permalink_url") or "")
    user = track.get("user") or {}
    publisher = track.get("publisher_metadata") or {}
    score, factors = ranking_for_track(artist, track, release_date, lookback_days, today)
    return ReleaseCandidate(
        artist=artist_name,
        track_or_project_title=title,
        release_type=release_type(title),
        confidence_score=confidence(track),
        extraction_method="soundcloud_followed_artist_api",
        source_article_title=f"{artist_name} - {title}",
        source_article_url=track_url or artist.soundcloud_url,
        source_name=SOURCE_NAME,
        article_date=release_date.isoformat(),
        ranking_score=score,
        ranking_factors=factors,
        embedded_music_links=[track_url] if track_url else [],
        open_graph={
            "soundcloud_track_id": str(track.get("id") or ""),
            "soundcloud_user_id": artist.soundcloud_user_id or str(user.get("id") or ""),
            "soundcloud_username": clean_text(user.get("username") or artist.artist_name),
            "soundcloud_profile_url": artist.soundcloud_url,
            "followed_artist_genres": " | ".join(artist.genres),
            "followed_artist_edm_match_terms": " | ".join(artist.edm_match_terms),
            "followed_artist_followers_count": str(artist.followers_count or ""),
            "all_artists": artist_name,
            "genre": clean_text(track.get("genre") or ""),
            "tag_list": clean_text(track.get("tag_list") or ""),
            "label": clean_text(track.get("label_name") or publisher.get("publisher") or ""),
            "album_name": clean_text(publisher.get("album_title") or ""),
            "isrc": clean_text(publisher.get("isrc") or ""),
            "explicit": str(bool(publisher.get("explicit"))),
            "duration_ms": str(track.get("duration") or ""),
            "playback_count": str(track.get("playback_count") or ""),
            "likes_count": str(track.get("likes_count") or track.get("favoritings_count") or ""),
            "reposts_count": str(track.get("reposts_count") or ""),
            "created_at": clean_text(track.get("created_at") or ""),
        },
    )


def ranking_for_track(
    artist: FollowedArtist,
    track: dict[str, Any],
    release_date: date,
    lookback_days: int,
    today: date,
) -> tuple[float, dict[str, object]]:
    age_days = max((today - release_date).days, 0)
    components = {
        "recency": max(1.0 - (age_days / lookback_days), 0.0) if lookback_days else 1.0,
        "artist_followers": log_score(artist.followers_count, 1_000_000),
        "track_plays": log_score(int_or_none(track.get("playback_count")), 1_000_000),
        "track_likes": log_score(int_or_none(track.get("likes_count") or track.get("favoritings_count")), 100_000),
        "track_reposts": log_score(int_or_none(track.get("reposts_count")), 10_000),
        "metadata_confidence": confidence(track),
    }
    weights = {
        "recency": 0.25,
        "artist_followers": 0.15,
        "track_plays": 0.20,
        "track_likes": 0.15,
        "track_reposts": 0.10,
        "metadata_confidence": 0.15,
    }
    score = round(sum(components[key] * weights[key] for key in weights) * 100, 2)
    return score, {
        "score_version": "soundcloud_followed_artist_v1",
        "weights": weights,
        "raw": {
            "release_age_days": age_days,
            "artist_followers": artist.followers_count,
            "playback_count": int_or_none(track.get("playback_count")),
            "likes_count": int_or_none(track.get("likes_count") or track.get("favoritings_count")),
            "reposts_count": int_or_none(track.get("reposts_count")),
        },
        "components": {key: round(value, 4) for key, value in components.items()},
    }


def artist_and_title(track: dict[str, Any], fallback_artist: str) -> tuple[str, str]:
    raw_title = clean_text(track.get("title") or "")
    publisher = track.get("publisher_metadata") or {}
    publisher_artist = clean_text(publisher.get("artist") or "")
    publisher_title = clean_text(publisher.get("release_title") or "")
    if publisher_artist:
        return publisher_artist, publisher_title or strip_artist_prefix(raw_title, publisher_artist) or raw_title
    parsed = parse_artist_title(raw_title)
    if parsed:
        return parsed
    return fallback_artist, raw_title


def track_release_date(track: dict[str, Any]) -> date | None:
    for key in ("release_date", "display_date", "created_at"):
        value = clean_text(track.get(key) or "")
        if not value:
            continue
        for pattern in (r"(\d{4}-\d{2}-\d{2})", r"(\d{4}/\d{2}/\d{2})"):
            match = re.match(pattern, value)
            if match:
                try:
                    return datetime.strptime(match.group(1).replace("/", "-"), "%Y-%m-%d").date()
                except ValueError:
                    return None
    return None


def track_looks_like_release(track: dict[str, Any]) -> bool:
    title = clean_text(track.get("title") or "").lower()
    publisher = track.get("publisher_metadata") or {}
    duration_ms = int_or_none(track.get("duration")) or 0
    if publisher.get("isrc") or publisher.get("release_title"):
        return True
    if duration_ms and duration_ms > 15 * 60 * 1000:
        return False
    excluded = ("live @", "live at", "dj set", "full set", "festival set", "radio show", "podcast", "essential mix", "boiler room")
    return not any(term in title for term in excluded)


def confidence(track: dict[str, Any]) -> float:
    score = 0.70
    publisher = track.get("publisher_metadata") or {}
    if track.get("permalink_url"):
        score += 0.10
    if publisher.get("isrc"):
        score += 0.10
    if publisher.get("artist") or publisher.get("release_title"):
        score += 0.10
    return min(score, 1.0)


def release_type(title: str) -> str:
    lowered = title.lower()
    if "remix" in lowered:
        return "remix"
    if "rework" in lowered:
        return "rework"
    return "track"


def parse_artist_title(value: str) -> tuple[str, str] | None:
    for separator in (" - ", " – ", " — "):
        if separator in value:
            artist, title = value.split(separator, 1)
            return clean_text(artist), clean_text(title)
    return None


def strip_artist_prefix(title: str, artist: str) -> str | None:
    match = re.match(rf"^{re.escape(artist)}\s*[-–—]\s*(.+)$", title, re.IGNORECASE)
    return clean_text(match.group(1)) if match else None


def int_or_none(value: Any) -> int | None:
    try:
        text = str(value).replace(",", "").strip()
        return int(float(text)) if text else None
    except (TypeError, ValueError):
        return None


def log_score(value: int | None, ceiling: int) -> float:
    if value is None or value <= 0:
        return 0.0
    import math

    return min(math.log10(value + 1) / math.log10(ceiling + 1), 1.0)


def write_json(candidates: list[ReleaseCandidate], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump([candidate.as_dict() for candidate in candidates], handle, indent=2, ensure_ascii=False)
        handle.write("\n")
