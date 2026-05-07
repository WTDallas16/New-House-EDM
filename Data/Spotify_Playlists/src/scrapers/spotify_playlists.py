from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import spotipy
from dotenv import load_dotenv
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOAuth

from src.extraction.normalize import clean_text
from src.models import ReleaseCandidate

LOGGER = logging.getLogger(__name__)

DEFAULT_SCOPE = "playlist-read-private playlist-read-collaborative"
SPOTIFY_ROOT = "https://open.spotify.com"


@dataclass(slots=True)
class PlaylistSource:
    playlist_id: str
    original_value: str


class SpotifyPlaylistScraper:
    source_name = "Spotify Playlist"

    def __init__(self, cache_path: str = ".spotify_token_cache", skip_playlist_errors: bool = True) -> None:
        load_dotenv()
        self.cache_path = cache_path
        self.skip_playlist_errors = skip_playlist_errors

    def scrape_releases(self, playlist_values: list[str], market: str | None = None) -> list[ReleaseCandidate]:
        sources = [_playlist_source(value) for value in playlist_values if clean_text(value)]
        if not sources:
            raise ValueError("No Spotify playlists were provided.")

        sp = self._client()
        candidates: list[ReleaseCandidate] = []
        for source in sources:
            LOGGER.info("Fetching Spotify playlist %s from %s", source.playlist_id, source.original_value)
            try:
                playlist = sp.playlist(
                    source.playlist_id,
                    fields="id,name,owner(display_name,id),external_urls,href",
                    market=market,
                )
                playlist_meta = _playlist_metadata(playlist)
                for item in _playlist_items(sp, source.playlist_id, market=market):
                    candidate = _candidate_from_playlist_item(item, playlist_meta)
                    if candidate:
                        candidates.append(candidate)
            except SpotifyException as exc:
                if not self.skip_playlist_errors:
                    raise
                LOGGER.warning(
                    "Skipping Spotify playlist %s (%s): %s",
                    source.playlist_id,
                    source.original_value,
                    _spotify_error_summary(exc),
                )
        return candidates

    def _client(self) -> spotipy.Spotify:
        client_id = _env_first("SPOTIFY_CLIENT_ID", "SPOTIPY_CLIENT_ID", "clientid")
        client_secret = _env_first("SPOTIFY_CLIENT_SECRET", "SPOTIPY_CLIENT_SECRET", "secretclientid")
        redirect_uri = _env_first("SPOTIFY_REDIRECT_URI", "SPOTIPY_REDIRECT_URI", "redirect_uri")
        scope = _env_first("SPOTIFY_SCOPE", "SPOTIPY_SCOPE", "scope") or DEFAULT_SCOPE

        missing = [
            name
            for name, value in (
                ("SPOTIFY_CLIENT_ID", client_id),
                ("SPOTIFY_CLIENT_SECRET", client_secret),
                ("SPOTIFY_REDIRECT_URI", redirect_uri),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Missing Spotify credentials. Set SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, "
                "and SPOTIFY_REDIRECT_URI in your environment or .env file."
            )

        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=scope,
            cache_path=self.cache_path,
            open_browser=True,
        )
        return spotipy.Spotify(auth_manager=auth_manager)


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _playlist_source(value: str) -> PlaylistSource:
    original = clean_text(value)
    playlist_id = _playlist_id_from_value(original)
    if not playlist_id:
        raise ValueError(f"Could not parse Spotify playlist ID from {value!r}")
    return PlaylistSource(playlist_id=playlist_id, original_value=original)


def _spotify_error_summary(exc: SpotifyException) -> str:
    status = getattr(exc, "http_status", None)
    message = getattr(exc, "msg", None) or str(exc)
    reason = getattr(exc, "reason", None)
    if reason:
        return f"HTTP {status}: {message} ({reason})"
    return f"HTTP {status}: {message}"


def _playlist_id_from_value(value: str) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    if text.startswith("spotify:playlist:"):
        return text.rsplit(":", 1)[-1]
    if "open.spotify.com" in text:
        parsed = urlparse(text)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "playlist":
            return parts[1]
        query_id = parse_qs(parsed.query).get("playlist")
        if query_id:
            return query_id[0]
    if re.fullmatch(r"[A-Za-z0-9]{16,}", text):
        return text
    return None


def playlist_values_from_file(path: str | Path) -> list[str]:
    values: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            values.append(stripped)
    return values


def _playlist_items(sp: spotipy.Spotify, playlist_id: str, market: str | None = None) -> list[dict]:
    fields = (
        "items(added_at,added_by(id,external_urls),track("
        "id,name,type,is_local,is_playable,explicit,popularity,duration_ms,preview_url,"
        "track_number,disc_number,external_ids,external_urls,artists(id,name,external_urls),"
        "album(id,name,album_type,total_tracks,release_date,release_date_precision,external_urls))),"
        "next"
    )
    page = sp.playlist_items(playlist_id, limit=100, offset=0, fields=fields, market=market)
    items = list(page.get("items") or [])
    while page.get("next"):
        page = sp.next(page)
        items.extend(page.get("items") or [])
    return items


def _playlist_metadata(playlist: dict) -> dict[str, str]:
    owner = playlist.get("owner") or {}
    external_urls = playlist.get("external_urls") or {}
    return {
        "playlist_id": str(playlist.get("id") or ""),
        "playlist_name": clean_text(playlist.get("name") or ""),
        "playlist_owner": clean_text(owner.get("display_name") or owner.get("id") or ""),
        "playlist_url": str(external_urls.get("spotify") or f"{SPOTIFY_ROOT}/playlist/{playlist.get('id')}"),
    }


def _candidate_from_playlist_item(item: dict, playlist_meta: dict[str, str]) -> ReleaseCandidate | None:
    track = item.get("track") or {}
    if track.get("type") != "track" or track.get("is_local"):
        return None
    artist_names = [clean_text(artist.get("name") or "") for artist in track.get("artists") or []]
    artist_names = [name for name in artist_names if name]
    title = clean_text(track.get("name") or "")
    if not artist_names or not title:
        return None

    album = track.get("album") or {}
    external_urls = track.get("external_urls") or {}
    album_urls = album.get("external_urls") or {}
    primary_artist = artist_names[0]
    spotify_url = str(external_urls.get("spotify") or f"{SPOTIFY_ROOT}/track/{track.get('id')}")
    album_release_date = clean_text(album.get("release_date") or "")

    open_graph = {
        **playlist_meta,
        "spotify_track_id": str(track.get("id") or ""),
        "spotify_album_id": str(album.get("id") or ""),
        "spotify_artist_ids": ", ".join(str(artist.get("id") or "") for artist in track.get("artists") or [] if artist.get("id")),
        "all_artists": ", ".join(artist_names),
        "album_name": clean_text(album.get("name") or ""),
        "album_type": clean_text(album.get("album_type") or ""),
        "album_total_tracks": str(album.get("total_tracks") or ""),
        "album_release_date_precision": clean_text(album.get("release_date_precision") or ""),
        "album_url": str(album_urls.get("spotify") or ""),
        "spotify_popularity": str(track.get("popularity") if track.get("popularity") is not None else ""),
        "duration_ms": str(track.get("duration_ms") or ""),
        "explicit": str(bool(track.get("explicit"))),
        "isrc": str((track.get("external_ids") or {}).get("isrc") or ""),
        "added_at": clean_text(item.get("added_at") or ""),
        "added_by": str((item.get("added_by") or {}).get("id") or ""),
        "track_number": str(track.get("track_number") or ""),
        "disc_number": str(track.get("disc_number") or ""),
        "preview_url": str(track.get("preview_url") or ""),
    }

    return ReleaseCandidate(
        artist=primary_artist,
        track_or_project_title=title,
        release_type=_release_type(album),
        confidence_score=_confidence(track),
        extraction_method="spotify_playlist_api",
        source_article_title=f"{primary_artist} - {title}",
        source_article_url=spotify_url,
        source_name="Spotify Playlist",
        article_date=album_release_date or None,
        embedded_music_links=[spotify_url],
        open_graph=open_graph,
    )


def _release_type(album: dict) -> str:
    album_type = clean_text(album.get("album_type") or "").lower()
    total_tracks = int(album.get("total_tracks") or 0)
    if album_type == "single":
        return "single" if total_tracks <= 3 else "EP"
    if album_type == "album":
        return "album" if total_tracks > 6 else "EP"
    return "track"


def _confidence(track: dict) -> float:
    score = 0.75
    if track.get("id"):
        score += 0.10
    if (track.get("external_urls") or {}).get("spotify"):
        score += 0.10
    if (track.get("external_ids") or {}).get("isrc"):
        score += 0.05
    return min(score, 1.0)
