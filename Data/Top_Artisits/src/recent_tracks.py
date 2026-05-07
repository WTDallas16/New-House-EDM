from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests
import spotipy
from dotenv import load_dotenv
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyClientCredentials

from src.models import ReleaseCandidate
from src.soundcloud_api import SoundCloudAPIClient

LOGGER = logging.getLogger(__name__)
SPOTIFY_ARTIST_RE = re.compile(r"(?:open\.spotify\.com/artist/|spotify:artist:)([A-Za-z0-9]+)")


class SpotifyRateLimitReached(RuntimeError):
    def __init__(self, retry_after_seconds: int | None = None) -> None:
        self.retry_after_seconds = retry_after_seconds
        detail = f" Retry after {retry_after_seconds} seconds." if retry_after_seconds else ""
        super().__init__(f"Spotify rate limit reached.{detail}")


@dataclass(slots=True)
class ArtistProfile:
    artist_name: str
    spotify_url: str
    soundcloud_url: str = ""
    soundcloud_user_id: str = ""
    genre: str = ""
    rank: str = ""
    monthly_listeners: str = ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find recent Spotify releases from a CSV of artist profiles.")
    parser.add_argument("--artists-csv", default="master_artist_list.csv", help="CSV from src.main.")
    parser.add_argument("--output", default="data/master_recent_tracks.json")
    parser.add_argument("--lookback-days", type=int, default=14, help="Only include releases from this many days back.")
    parser.add_argument("--market", default="US", help="Spotify market/country code.")
    parser.add_argument("--limit-artists", type=int, default=0, help="Optional first-N artist limit for testing.")
    parser.add_argument(
        "--ranking-mode",
        default="fast",
        choices=["fast", "full"],
        help="fast uses CSV/release-date signals; full also asks Spotify for artist and track popularity.",
    )
    parser.add_argument(
        "--rank-existing-json",
        default=None,
        help="Add ranking fields to an existing extracted JSON file without calling Spotify.",
    )
    parser.add_argument(
        "--stop-on-rate-limit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Stop the scan cleanly after the first Spotify 429 instead of continuing to burn requests.",
    )
    parser.add_argument(
        "--soundcloud-fallback",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="After a Spotify rate limit, continue remaining artists through SoundCloud profile tracks when profile IDs are available.",
    )
    parser.add_argument("--soundcloud-only", action="store_true", help="Skip Spotify and collect recent tracks only from SoundCloud profile fields.")
    parser.add_argument("--soundcloud-track-limit", type=int, default=50, help="Max recent SoundCloud tracks to inspect per artist.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def load_artist_profiles(path: Path, limit: int = 0) -> list[ArtistProfile]:
    profiles: list[ArtistProfile] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            spotify_url = (row.get("spotify_url") or "").strip()
            soundcloud_url = (row.get("soundcloud_url") or "").strip()
            soundcloud_user_id = (row.get("soundcloud_user_id") or "").strip()
            if not spotify_url and not soundcloud_url and not soundcloud_user_id:
                continue
            if spotify_url and not spotify_artist_id_from_url(spotify_url):
                LOGGER.debug("Skipping %s because Spotify URL is not an artist profile", spotify_url)
                continue
            profiles.append(
                ArtistProfile(
                    artist_name=(row.get("artist_name") or "").strip(),
                    spotify_url=spotify_url,
                    soundcloud_url=soundcloud_url,
                    soundcloud_user_id=soundcloud_user_id,
                    genre=(row.get("genre") or "").strip(),
                    rank=(row.get("rank") or "").strip(),
                    monthly_listeners=(row.get("monthly_listeners") or "").strip(),
                )
            )
            if limit and len(profiles) >= limit:
                break
    return profiles


def spotify_artist_id_from_url(value: str) -> str:
    match = SPOTIFY_ARTIST_RE.search(value)
    if match:
        return match.group(1)
    parsed = urlparse(value)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[-2] == "artist":
        return parts[-1]
    if parsed.scheme == "" and "/" not in value and value:
        return value.strip()
    return ""


def parse_spotify_release_date(value: str, precision: str = "day") -> date | None:
    if precision != "day":
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def release_type_from_album(album: dict, track_name: str) -> str:
    lowered = track_name.lower()
    if "remix" in lowered:
        return "remix"
    if "rework" in lowered:
        return "rework"

    album_type = str(album.get("album_type") or "").lower()
    total_tracks = int(album.get("total_tracks") or 0)
    if album_type == "single":
        return "single" if total_tracks <= 3 else "EP"
    if album_type == "album":
        return "album" if total_tracks > 6 else "EP"
    return "track"


def make_spotify_client() -> spotipy.Spotify:
    load_dotenv()
    fallback_env = Path(__file__).resolve().parents[2] / "Spotify_Playlists" / ".env"
    if fallback_env.exists():
        load_dotenv(fallback_env, override=False)
    client_id = _env_first("SPOTIFY_CLIENT_ID", "SPOTIPY_CLIENT_ID", "clientid")
    client_secret = _env_first("SPOTIFY_CLIENT_SECRET", "SPOTIPY_CLIENT_SECRET", "secretclientid")
    if not client_id or not client_secret:
        raise RuntimeError("Spotify credentials were not found in Top_Artisits/.env or ../Spotify_Playlists/.env")
    auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
    return spotipy.Spotify(
        auth_manager=auth_manager,
        requests_timeout=20,
        retries=0,
        status_retries=0,
        backoff_factor=0.4,
    )


def fetch_recent_tracks(
    client: spotipy.Spotify,
    profiles: list[ArtistProfile],
    lookback_days: int = 14,
    market: str = "US",
    today: date | None = None,
    ranking_mode: str = "fast",
    stop_on_rate_limit: bool = True,
    soundcloud_fallback: bool = True,
    soundcloud_track_limit: int = 50,
) -> list[ReleaseCandidate]:
    current_day = today or date.today()
    cutoff = current_day - timedelta(days=lookback_days)
    releases: list[ReleaseCandidate] = []
    seen_album_ids: set[str] = set()
    seen_track_ids: set[str] = set()
    artist_stats_cache: dict[str, dict] = {}
    track_stats_cache: dict[str, dict] = {}
    fallback_start_index: int | None = None

    for index, profile in enumerate(profiles, start=1):
        artist_id = spotify_artist_id_from_url(profile.spotify_url)
        if not artist_id:
            continue
        artist_stats: dict | None = None
        LOGGER.info("Checking %s (%d/%d)", profile.artist_name or artist_id, index, len(profiles))
        try:
            artist_albums = iter_artist_albums(client, artist_id, market=market)
            for album in artist_albums:
                album_id = str(album.get("id") or "")
                if not album_id or album_id in seen_album_ids:
                    continue
                seen_album_ids.add(album_id)

                release_date = parse_spotify_release_date(
                    str(album.get("release_date") or ""),
                    str(album.get("release_date_precision") or ""),
                )
                if release_date is None or release_date < cutoff or release_date > current_day:
                    continue
                if ranking_mode == "full" and artist_stats is None:
                    artist_stats = artist_stats_cache.get(artist_id)
                    if artist_stats is None:
                        artist_stats = spotify_call(client.artist, artist_id) or {}
                        artist_stats_cache[artist_id] = artist_stats

                for track in iter_album_tracks(client, album_id, market=market):
                    track_id = str(track.get("id") or "")
                    if track_id and track_id in seen_track_ids:
                        continue
                    if track_id:
                        seen_track_ids.add(track_id)
                    track_stats = track_stats_cache.get(track_id, {}) if track_id else {}
                    if ranking_mode == "full" and track_id and track_id not in track_stats_cache:
                        track_stats = spotify_call(client.track, track_id, market=market) or {}
                        track_stats_cache[track_id] = track_stats
                    releases.append(
                        build_release_candidate(
                            profile,
                            artist_id,
                            album,
                            track,
                            release_date,
                            artist_stats=artist_stats or {},
                            track_stats=track_stats,
                            lookback_days=lookback_days,
                            today=current_day,
                        )
                    )
        except SpotifyRateLimitReached as exc:
            retry_after = f" Retry after {exc.retry_after_seconds} seconds." if exc.retry_after_seconds else ""
            LOGGER.warning("Stopping Spotify artist scan at %s (%d/%d) after rate limit.%s", profile.artist_name, index, len(profiles), retry_after)
            fallback_start_index = index - 1
            if stop_on_rate_limit:
                break
            continue

    if soundcloud_fallback and fallback_start_index is not None:
        releases.extend(
            fetch_soundcloud_recent_tracks(
                profiles[fallback_start_index:],
                lookback_days=lookback_days,
                today=current_day,
                track_limit=soundcloud_track_limit,
            )
        )

    return releases


def fetch_soundcloud_recent_tracks(
    profiles: list[ArtistProfile],
    lookback_days: int = 14,
    today: date | None = None,
    track_limit: int = 50,
    client: SoundCloudAPIClient | None = None,
) -> list[ReleaseCandidate]:
    current_day = today or date.today()
    cutoff = current_day - timedelta(days=lookback_days)
    client = client or SoundCloudAPIClient()
    if not client.can_use_api:
        LOGGER.warning("SoundCloud fallback requested, but SoundCloud API credentials are unavailable.")
        return []

    releases: list[ReleaseCandidate] = []
    seen_track_ids: set[str] = set()
    for profile in profiles:
        user_id = clean_optional(profile.soundcloud_user_id)
        user_url = clean_optional(profile.soundcloud_url)
        if not user_id and user_url:
            try:
                resolved = client.resolve(user_url)
            except requests.RequestException as exc:
                LOGGER.warning("Could not resolve SoundCloud profile for %s: %s", profile.artist_name, exc)
                continue
            if resolved.get("kind") != "user":
                continue
            user_id = str(resolved.get("id") or "")
            if not user_url:
                user_url = str(resolved.get("permalink_url") or "")
        if not user_id:
            LOGGER.debug("Skipping %s; no SoundCloud profile ID", profile.artist_name)
            continue

        LOGGER.info("Checking SoundCloud profile %s", profile.artist_name)
        try:
            tracks = client.user_tracks(user_id, limit=track_limit)
        except requests.RequestException as exc:
            LOGGER.warning("SoundCloud tracks lookup failed for %s: %s", profile.artist_name, exc)
            continue
        for track in tracks:
            track_id = str(track.get("id") or "")
            if track_id and track_id in seen_track_ids:
                continue
            if not soundcloud_track_looks_like_release(track):
                continue
            release_date = soundcloud_release_date(track)
            if release_date is None or release_date < cutoff or release_date > current_day:
                continue
            if track_id:
                seen_track_ids.add(track_id)
            candidate = build_soundcloud_candidate(profile, track, user_id, user_url, release_date, lookback_days, current_day)
            if candidate:
                releases.append(candidate)
    return releases


def iter_artist_albums(client: spotipy.Spotify, artist_id: str, market: str = "US"):
    page = spotify_call(
        client.artist_albums,
        artist_id,
        album_type="album,single",
        country=market,
        limit=50,
    )
    while page:
        for album in page.get("items") or []:
            yield album
        if not page.get("next"):
            break
        page = spotify_call(client.next, page)


def iter_album_tracks(client: spotipy.Spotify, album_id: str, market: str = "US"):
    page = spotify_call(client.album_tracks, album_id, limit=50, market=market)
    while page:
        for track in page.get("items") or []:
            yield track
        if not page.get("next"):
            break
        page = spotify_call(client.next, page)


def spotify_call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except SpotifyException as exc:
        status = getattr(exc, "http_status", None)
        if status == 429:
            retry_after = retry_after_seconds(exc)
            raise SpotifyRateLimitReached(retry_after) from exc
        LOGGER.warning("Spotify API call failed: %s", exc)
        return None


def build_soundcloud_candidate(
    profile: ArtistProfile,
    track: dict,
    soundcloud_user_id: str,
    soundcloud_url: str,
    release_date: date,
    lookback_days: int,
    today: date,
) -> ReleaseCandidate | None:
    artist, title = soundcloud_artist_and_title(track, profile)
    if not artist or not title:
        return None
    track_url = str(track.get("permalink_url") or "")
    user = track.get("user") or {}
    publisher = track.get("publisher_metadata") or {}
    ranking_score, ranking_factors = calculate_ranking(
        profile=profile,
        release_date=release_date,
        artist_stats={},
        track_stats={},
        lookback_days=lookback_days,
        today=today,
    )
    return ReleaseCandidate(
        artist=artist,
        track_or_project_title=title,
        release_type=release_type_from_title(title),
        confidence_score=soundcloud_confidence(track),
        extraction_method="soundcloud_artist_profile_api",
        source_article_title=f"{artist} - {title}",
        source_article_url=track_url or soundcloud_url,
        source_name="SoundCloud Artist Profile",
        article_date=release_date.isoformat(),
        ranking_score=ranking_score,
        ranking_factors=ranking_factors,
        embedded_music_links=[track_url] if track_url else [],
        open_graph={
            "soundcloud_track_id": str(track.get("id") or ""),
            "soundcloud_user_id": soundcloud_user_id or str(user.get("id") or ""),
            "soundcloud_username": str(user.get("username") or ""),
            "soundcloud_profile_url": soundcloud_url,
            "source_artist_name": profile.artist_name,
            "source_artist_genres": profile.genre,
            "source_artist_rank": profile.rank,
            "source_artist_monthly_listeners": profile.monthly_listeners,
            "all_artists": artist,
            "genre": str(track.get("genre") or ""),
            "tag_list": str(track.get("tag_list") or ""),
            "label": str(track.get("label_name") or publisher.get("publisher") or ""),
            "album_name": str(publisher.get("album_title") or ""),
            "isrc": str(publisher.get("isrc") or ""),
            "explicit": str(bool(publisher.get("explicit"))),
            "duration_ms": value_as_str(track.get("duration")),
            "playback_count": value_as_str(track.get("playback_count")),
            "likes_count": value_as_str(track.get("likes_count") or track.get("favoritings_count")),
            "reposts_count": value_as_str(track.get("reposts_count")),
            "created_at": str(track.get("created_at") or ""),
        },
    )


def soundcloud_artist_and_title(track: dict, profile: ArtistProfile) -> tuple[str, str]:
    raw_title = clean_text(str(track.get("title") or ""))
    publisher = track.get("publisher_metadata") or {}
    publisher_artist = clean_text(str(publisher.get("artist") or ""))
    publisher_title = clean_text(str(publisher.get("release_title") or ""))
    if publisher_artist:
        return publisher_artist, publisher_title or strip_artist_prefix(raw_title, publisher_artist) or raw_title
    parsed = parse_artist_title(raw_title)
    if parsed:
        return parsed
    return profile.artist_name, raw_title


def soundcloud_release_date(track: dict) -> date | None:
    for key in ("release_date", "display_date", "created_at"):
        value = clean_text(str(track.get(key) or ""))
        if not value:
            continue
        for pattern in (r"(\d{4}-\d{2}-\d{2})", r"(\d{4}/\d{2}/\d{2})"):
            match = re.match(pattern, value)
            if match:
                text = match.group(1).replace("/", "-")
                try:
                    return datetime.strptime(text, "%Y-%m-%d").date()
                except ValueError:
                    return None
    return None


def release_type_from_title(title: str) -> str:
    lowered = title.lower()
    if "remix" in lowered:
        return "remix"
    if "rework" in lowered:
        return "rework"
    return "track"


def soundcloud_confidence(track: dict) -> float:
    score = 0.70
    publisher = track.get("publisher_metadata") or {}
    if track.get("permalink_url"):
        score += 0.10
    if publisher.get("isrc"):
        score += 0.10
    if publisher.get("artist") or publisher.get("release_title"):
        score += 0.10
    return min(score, 1.0)


def soundcloud_track_looks_like_release(track: dict) -> bool:
    title = clean_text(str(track.get("title") or "")).lower()
    publisher = track.get("publisher_metadata") or {}
    duration_ms = parse_int(track.get("duration")) or 0
    if publisher.get("isrc") or publisher.get("release_title"):
        return True
    if duration_ms and duration_ms > 15 * 60 * 1000:
        return False
    excluded_patterns = (
        "live @",
        "live at",
        "dj set",
        "full set",
        "festival set",
        "radio show",
        "podcast",
        "essential mix",
        "boiler room",
        "after party",
    )
    return not any(pattern in title for pattern in excluded_patterns)


def parse_artist_title(value: str) -> tuple[str, str] | None:
    for separator in (" - ", " – ", " — "):
        if separator in value:
            artist, title = value.split(separator, 1)
            artist = clean_text(artist)
            title = clean_text(title)
            if artist and title:
                return artist, title
    return None


def strip_artist_prefix(title: str, artist: str) -> str | None:
    match = re.match(rf"^{re.escape(artist)}\s*[-–—]\s*(.+)$", title, re.IGNORECASE)
    return clean_text(match.group(1)) if match else None


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def clean_optional(value: str) -> str:
    text = clean_text(value)
    return "" if text.lower() in {"", "none", "null", "nan"} else text


def normalize_for_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def retry_after_seconds(exc: SpotifyException) -> int | None:
    headers = getattr(exc, "headers", {}) or {}
    value = headers.get("Retry-After") or headers.get("retry-after")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_release_candidate(
    profile: ArtistProfile,
    spotify_artist_id: str,
    album: dict,
    track: dict,
    release_date: date,
    artist_stats: dict | None = None,
    track_stats: dict | None = None,
    lookback_days: int = 14,
    today: date | None = None,
) -> ReleaseCandidate:
    artist_stats = artist_stats or {}
    track_stats = track_stats or {}
    track_name = str(track.get("name") or "").strip()
    track_artists = track.get("artists") or []
    all_artist_names = ", ".join(str(artist.get("name") or "").strip() for artist in track_artists if artist.get("name"))
    artist_name = all_artist_names or profile.artist_name
    track_url = str((track.get("external_urls") or {}).get("spotify") or "")
    album_url = str((album.get("external_urls") or {}).get("spotify") or "")
    track_ids = ", ".join(str(artist.get("id") or "") for artist in track_artists if artist.get("id"))
    ranking_score, ranking_factors = calculate_ranking(
        profile=profile,
        release_date=release_date,
        artist_stats=artist_stats,
        track_stats=track_stats,
        lookback_days=lookback_days,
        today=today,
    )

    return ReleaseCandidate(
        artist=artist_name,
        track_or_project_title=track_name,
        release_type=release_type_from_album(album, track_name),
        confidence_score=1.0,
        extraction_method="spotify_artist_recent_releases_api",
        source_article_title=f"{artist_name} - {track_name}",
        source_article_url=track_url or album_url or profile.spotify_url,
        source_name="Spotify Artist Profile",
        article_date=release_date.isoformat(),
        ranking_score=ranking_score,
        ranking_factors=ranking_factors,
        embedded_music_links=[url for url in [track_url, album_url] if url],
        open_graph={
            "spotify_track_id": str(track.get("id") or ""),
            "spotify_album_id": str(album.get("id") or ""),
            "spotify_artist_id": spotify_artist_id,
            "spotify_artist_ids": track_ids,
            "artist_profile_url": profile.spotify_url,
            "source_artist_name": profile.artist_name,
            "source_artist_genres": profile.genre,
            "source_artist_rank": profile.rank,
            "source_artist_monthly_listeners": profile.monthly_listeners,
            "source_artist_spotify_popularity": value_as_str(artist_stats.get("popularity")),
            "source_artist_followers": value_as_str((artist_stats.get("followers") or {}).get("total")),
            "source_artist_spotify_genres": ", ".join(artist_stats.get("genres") or []),
            "all_artists": artist_name,
            "album_name": str(album.get("name") or ""),
            "album_type": str(album.get("album_type") or ""),
            "album_total_tracks": str(album.get("total_tracks") or ""),
            "album_release_date_precision": str(album.get("release_date_precision") or ""),
            "album_url": album_url,
            "duration_ms": value_as_str(track.get("duration_ms")),
            "explicit": value_as_str(track.get("explicit")),
            "spotify_track_popularity": value_as_str(track_stats.get("popularity")),
            "isrc": str(((track_stats.get("external_ids") or {}).get("isrc")) or ""),
            "track_number": value_as_str(track.get("track_number")),
            "disc_number": value_as_str(track.get("disc_number")),
            "preview_url": str(track.get("preview_url") or ""),
        },
    )


def write_json(releases: list[ReleaseCandidate], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump([release.as_dict() for release in releases], handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def rerank_existing_json(input_path: Path, output_path: Path, lookback_days: int) -> int:
    with input_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    current_day = date.today()
    for item in data:
        open_graph = item.get("open_graph") or {}
        release_date = parse_spotify_release_date(str(item.get("article_date") or ""), "day")
        if release_date is None:
            item["ranking_score"] = 0.0
            item["ranking_factors"] = {"score_version": "spotify_artist_profile_v1", "raw": {}, "components": {}}
            continue
        profile = ArtistProfile(
            artist_name=str(open_graph.get("source_artist_name") or item.get("artist") or ""),
            spotify_url=str(open_graph.get("artist_profile_url") or ""),
            genre=str(open_graph.get("source_artist_genres") or ""),
            rank=str(open_graph.get("source_artist_rank") or ""),
            monthly_listeners=str(open_graph.get("source_artist_monthly_listeners") or ""),
        )
        score, factors = calculate_ranking(
            profile=profile,
            release_date=release_date,
            artist_stats={
                "popularity": open_graph.get("source_artist_spotify_popularity"),
                "followers": {"total": open_graph.get("source_artist_followers")},
            },
            track_stats={"popularity": open_graph.get("spotify_track_popularity")},
            lookback_days=lookback_days,
            today=current_day,
        )
        item["ranking_score"] = score
        item["ranking_factors"] = factors
    data.sort(key=lambda item: item.get("ranking_score") or 0, reverse=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return len(data)


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip().strip('"').strip("'")
    return None


def value_as_str(value) -> str:
    return "" if value is None else str(value)


def calculate_ranking(
    profile: ArtistProfile,
    release_date: date,
    artist_stats: dict,
    track_stats: dict,
    lookback_days: int,
    today: date | None = None,
) -> tuple[float, dict[str, object]]:
    current_day = today or date.today()
    monthly_listeners = parse_int(profile.monthly_listeners)
    source_rank = parse_int(profile.rank)
    artist_popularity = parse_int(artist_stats.get("popularity"))
    artist_followers = parse_int((artist_stats.get("followers") or {}).get("total"))
    track_popularity = parse_int(track_stats.get("popularity"))
    age_days = max((current_day - release_date).days, 0)

    component_scores = {
        "monthly_listeners": normalized_log_score(monthly_listeners, ceiling=25_000_000),
        "source_rank": source_rank_score(source_rank),
        "spotify_artist_popularity": bounded_score(artist_popularity, ceiling=100),
        "spotify_artist_followers": normalized_log_score(artist_followers, ceiling=20_000_000),
        "spotify_track_popularity": bounded_score(track_popularity, ceiling=100),
        "recency": recency_score(age_days, lookback_days),
    }
    weights = {
        "monthly_listeners": 0.30,
        "source_rank": 0.15,
        "spotify_artist_popularity": 0.20,
        "spotify_artist_followers": 0.10,
        "spotify_track_popularity": 0.15,
        "recency": 0.10,
    }
    available_keys = [key for key in weights if component_is_available(key, monthly_listeners, source_rank, artist_popularity, artist_followers, track_popularity)]
    available_weight = sum(weights[key] for key in available_keys)
    weighted_score = sum(component_scores[key] * weights[key] for key in available_keys)
    score = round((weighted_score / available_weight) * 100, 2) if available_weight else 0.0
    return score, {
        "score_version": "spotify_artist_profile_v1",
        "score_description": (
            "0-100 weighted score using MusicMetricsVault monthly listeners/rank, "
            "Spotify artist popularity/followers when available, Spotify track popularity when available, and recency."
        ),
        "weights": weights,
        "available_weight": round(available_weight, 4),
        "raw": {
            "monthly_listeners": monthly_listeners,
            "source_rank": source_rank,
            "spotify_artist_popularity": artist_popularity,
            "spotify_artist_followers": artist_followers,
            "spotify_track_popularity": track_popularity,
            "release_age_days": age_days,
        },
        "components": {key: round(value, 4) for key, value in component_scores.items()},
    }


def component_is_available(
    key: str,
    monthly_listeners: int | None,
    source_rank: int | None,
    artist_popularity: int | None,
    artist_followers: int | None,
    track_popularity: int | None,
) -> bool:
    if key == "monthly_listeners":
        return monthly_listeners is not None
    if key == "source_rank":
        return source_rank is not None
    if key == "spotify_artist_popularity":
        return artist_popularity is not None
    if key == "spotify_artist_followers":
        return artist_followers is not None
    if key == "spotify_track_popularity":
        return track_popularity is not None
    return key == "recency"


def parse_int(value) -> int | None:
    if value is None:
        return None
    try:
        text = str(value).strip().replace(",", "")
        return int(float(text)) if text else None
    except ValueError:
        return None


def normalized_log_score(value: int | None, ceiling: int) -> float:
    if value is None or value <= 0:
        return 0.0
    return min(math.log10(value + 1) / math.log10(ceiling + 1), 1.0)


def bounded_score(value: int | None, ceiling: int) -> float:
    if value is None or value <= 0:
        return 0.0
    return min(value / ceiling, 1.0)


def source_rank_score(rank: int | None, max_rank: int = 500) -> float:
    if rank is None or rank <= 0:
        return 0.0
    return max(1.0 - ((rank - 1) / max_rank), 0.0)


def recency_score(age_days: int, lookback_days: int) -> float:
    if lookback_days <= 0:
        return 1.0
    return max(1.0 - (age_days / lookback_days), 0.0)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(name)s: %(message)s")

    if args.rank_existing_json:
        output = Path(args.output)
        count = rerank_existing_json(Path(args.rank_existing_json), output, lookback_days=args.lookback_days)
        LOGGER.info("Ranked %d existing tracks and wrote %s", count, output)
        return

    profiles = load_artist_profiles(Path(args.artists_csv), limit=args.limit_artists)
    LOGGER.info("Loaded %d Spotify artist profiles", len(profiles))
    if args.soundcloud_only:
        releases = fetch_soundcloud_recent_tracks(
            profiles,
            lookback_days=args.lookback_days,
            track_limit=args.soundcloud_track_limit,
        )
        releases.sort(key=lambda release: release.ranking_score, reverse=True)
        write_json(releases, Path(args.output))
        LOGGER.info("Wrote %d SoundCloud recent tracks to %s", len(releases), args.output)
        return

    client = make_spotify_client()
    releases = fetch_recent_tracks(
        client,
        profiles,
        lookback_days=args.lookback_days,
        market=args.market,
        ranking_mode=args.ranking_mode,
        stop_on_rate_limit=args.stop_on_rate_limit,
    )
    releases.sort(key=lambda release: release.ranking_score, reverse=True)
    write_json(releases, Path(args.output))
    LOGGER.info("Wrote %d recent tracks to %s", len(releases), args.output)


if __name__ == "__main__":
    main()
