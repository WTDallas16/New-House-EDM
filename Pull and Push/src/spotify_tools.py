from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import spotipy
from dotenv import load_dotenv
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOAuth

from src.models import ResolvedTrack
from src.normalize import chunked, clean_text, normalize_text, normalize_title

LOGGER = logging.getLogger(__name__)

SPOTIFY_TRACK_RE = re.compile(r"(?:open\.spotify\.com/track/|spotify:track:)([A-Za-z0-9]+)")
DEFAULT_SCOPE = "playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public"


class SpotifyRateLimited(RuntimeError):
    def __init__(self, retry_after: int | None = None) -> None:
        self.retry_after = retry_after
        super().__init__("Spotify API rate limit reached")


class SpotifyTools:
    def __init__(self, data_root: Path, cache_path: str = ".spotify_token_cache") -> None:
        load_dotenv()
        fallback_env = data_root / "Spotify_Playlists" / ".env"
        if fallback_env.exists():
            load_dotenv(fallback_env, override=False)
        self.client = self._make_client(cache_path)

    def _make_client(self, cache_path: str) -> spotipy.Spotify:
        client_id = _env_first("SPOTIFY_CLIENT_ID", "SPOTIPY_CLIENT_ID", "clientid")
        client_secret = _env_first("SPOTIFY_CLIENT_SECRET", "SPOTIPY_CLIENT_SECRET", "secretclientid")
        redirect_uri = _env_first("SPOTIFY_REDIRECT_URI", "SPOTIPY_REDIRECT_URI", "redirect_uri")
        scope = _env_first("SPOTIFY_SCOPE", "SPOTIPY_SCOPE", "scope") or DEFAULT_SCOPE
        missing = [name for name, value in {
            "SPOTIFY_CLIENT_ID": client_id,
            "SPOTIFY_CLIENT_SECRET": client_secret,
            "SPOTIFY_REDIRECT_URI": redirect_uri,
        }.items() if not value]
        if missing:
            raise RuntimeError(f"Missing Spotify credentials: {', '.join(missing)}")
        auth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=scope,
            cache_path=cache_path,
            open_browser=True,
        )
        return spotipy.Spotify(auth_manager=auth, requests_timeout=20, retries=0, status_retries=0)

    def resolve_track(self, item: dict[str, Any], lookback_days: int = 7, today: date | None = None) -> dict[str, str | None]:
        direct_id = spotify_track_id_from_record(item)
        if direct_id:
            return {
                "spotify_id": direct_id,
                "spotify_uri": f"spotify:track:{direct_id}",
                "spotify_url": f"https://open.spotify.com/track/{direct_id}",
            }

        artist = clean_text(item.get("artist"))
        title = clean_text(item.get("track_or_project_title"))
        if not artist or not title:
            return {"spotify_id": None, "spotify_uri": None, "spotify_url": None}
        query = f'track:"{title}" artist:"{artist}"'
        try:
            payload = self.client.search(q=query, type="track", limit=5, market="US")
        except SpotifyException as exc:
            if getattr(exc, "http_status", None) == 429:
                raise SpotifyRateLimited(retry_after_seconds(exc)) from exc
            LOGGER.warning("Spotify search failed for %s - %s: %s", artist, title, exc)
            return {"spotify_id": None, "spotify_uri": None, "spotify_url": None}

        tracks = ((payload.get("tracks") or {}).get("items") or []) if isinstance(payload, dict) else []
        best = best_spotify_match(artist, title, tracks, lookback_days=lookback_days, today=today)
        if not best:
            return {"spotify_id": None, "spotify_uri": None, "spotify_url": None}
        track_id = str(best.get("id") or "")
        return {
            "spotify_id": track_id or None,
            "spotify_uri": f"spotify:track:{track_id}" if track_id else None,
            "spotify_url": str((best.get("external_urls") or {}).get("spotify") or f"https://open.spotify.com/track/{track_id}"),
        }

    def find_or_create_playlist(self, name: str, public: bool = False) -> str:
        current_user = self.client.current_user()
        user_id = str(current_user.get("id") or "")
        for playlist in self._iter_current_user_playlists():
            if clean_text(playlist.get("name")).lower() == name.lower():
                return str(playlist.get("id") or "")
        playlist = self.client.user_playlist_create(
            user=user_id,
            name=name,
            public=public,
            description=f"Auto-refreshed by the New House pipeline on {datetime.now(timezone.utc).date().isoformat()}",
        )
        return str(playlist.get("id") or "")

    def replace_playlist_tracks(self, playlist_id: str, uris: list[str]) -> None:
        self.client.playlist_replace_items(playlist_id, [])
        for batch in chunked(uris, 100):
            self.client.playlist_add_items(playlist_id, batch)

    def _iter_current_user_playlists(self):
        page = self.client.current_user_playlists(limit=50)
        while page:
            for playlist in page.get("items") or []:
                yield playlist
            if not page.get("next"):
                break
            page = self.client.next(page)


def spotify_track_id_from_record(item: dict[str, Any]) -> str:
    open_graph = item.get("open_graph") or {}
    for value in [
        open_graph.get("spotify_track_id"),
        item.get("source_article_url"),
        *(item.get("embedded_music_links") or []),
    ]:
        match = SPOTIFY_TRACK_RE.search(str(value or ""))
        if match:
            return match.group(1)
    raw_id = clean_text(open_graph.get("spotify_track_id"))
    return raw_id if re.fullmatch(r"[A-Za-z0-9]{16,}", raw_id) else ""


def best_spotify_match(
    artist: str,
    title: str,
    tracks: list[dict[str, Any]],
    lookback_days: int = 7,
    today: date | None = None,
) -> dict[str, Any] | None:
    current_day = today or date.today()
    cutoff = current_day - timedelta(days=lookback_days)
    target_artists = spotify_artist_aliases(artist)
    target_title = normalize_title(title)
    best: tuple[float, dict[str, Any]] | None = None
    for track in tracks:
        candidate_title = normalize_title(track.get("name"))
        candidate_artists = [normalize_text(entry.get("name")) for entry in track.get("artists") or [] if entry.get("name")]
        title_score = spotify_title_score(target_title, candidate_title)
        artist_score = spotify_artist_score(target_artists, candidate_artists)
        if title_score < 0.82 or artist_score < 0.82:
            continue
        if not spotify_track_is_in_window(track, cutoff=cutoff, current_day=current_day):
            continue
        popularity = float(track.get("popularity") or 0) / 100
        score = (title_score * 0.55) + (artist_score * 0.40) + (popularity * 0.05)
        if best is None or score > best[0]:
            best = (score, track)
    if best and best[0] >= 0.84:
        return best[1]
    return None


def spotify_artist_aliases(artist: str) -> list[str]:
    text = clean_text(artist)
    text = re.sub(r"\([^)]*\)", " ", text)
    parts = re.split(r"\s*(?:,|\bx\b|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b)\s*", text, flags=re.IGNORECASE)
    return [normalize_text(alias) for alias in unique_nonempty([text, *parts])]


def spotify_title_score(target_title: str, candidate_title: str) -> float:
    if candidate_title == target_title:
        return 1.0
    if len(target_title) >= 6 and (target_title in candidate_title or candidate_title in target_title):
        return 0.86
    return 0.0


def spotify_artist_score(target_artists: list[str], candidate_artists: list[str]) -> float:
    score = 0.0
    for target in target_artists:
        for candidate in candidate_artists:
            if target == candidate:
                score = max(score, 1.0)
            elif len(target) >= 5 and len(candidate) >= 5 and (target in candidate or candidate in target):
                score = max(score, 0.84)
    return score


def spotify_track_is_in_window(track: dict[str, Any], cutoff: date, current_day: date) -> bool:
    album = track.get("album") or {}
    release_date = parse_spotify_date(album.get("release_date"), album.get("release_date_precision"))
    if release_date is None:
        return True
    return cutoff <= release_date <= current_day


def parse_spotify_date(value: Any, precision: Any) -> date | None:
    if precision != "day":
        return None
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d").date()
    except ValueError:
        return None


def unique_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = clean_text(value)
        if text and text.lower() not in seen:
            seen.add(text.lower())
            unique.append(text)
    return unique


def retry_after_seconds(exc: SpotifyException) -> int | None:
    headers = getattr(exc, "headers", {}) or {}
    value = headers.get("Retry-After") or headers.get("retry-after")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def write_spotify_backlog(path: Path, backlog: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(backlog, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def spotify_uris_from_tracks(tracks: list[ResolvedTrack]) -> list[str]:
    seen: set[str] = set()
    uris: list[str] = []
    for track in tracks:
        if track.spotify_uri and track.spotify_uri not in seen:
            seen.add(track.spotify_uri)
            uris.append(track.spotify_uri)
    return uris


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip().strip('"').strip("'")
    return None
