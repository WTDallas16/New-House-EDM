from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from src.extraction.normalize import clean_text
from src.models import ReleaseCandidate

LOGGER = logging.getLogger(__name__)

SOURCE_NAME = "SoundCloud Playlist"
SOUNDCLOUD_ROOT = "https://soundcloud.com"
API_BASE = "https://api.soundcloud.com"
TOKEN_URL = "https://secure.soundcloud.com/oauth/token"
ACCESS_VALUES = "playable,preview,blocked"
TOKEN_REFRESH_BUFFER_SECONDS = 300

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass(slots=True)
class SoundCloudPlaylist:
    title: str
    url: str
    owner: str
    playlist_id: str
    track_count: str
    likes_count: str
    reposts_count: str
    tracks: list[dict]
    extraction_method: str = "soundcloud_playlist_page"


class SoundCloudPlaylistScraper:
    source_name = SOURCE_NAME

    def __init__(
        self,
        timeout: float = 20.0,
        token_file: str | Path | None = None,
        use_html_fallback: bool = True,
    ) -> None:
        load_dotenv()
        self.timeout = timeout
        self.client = SoundCloudAPIClient(timeout=timeout, token_file=token_file)
        self.use_html_fallback = use_html_fallback

    def scrape_releases(self, playlist_values: list[str]) -> list[ReleaseCandidate]:
        urls = [_playlist_url(value) for value in playlist_values if clean_text(value)]
        if not urls:
            raise ValueError("No SoundCloud playlists were provided.")

        candidates: list[ReleaseCandidate] = []
        for url in urls:
            LOGGER.info("Fetching SoundCloud playlist %s", url)
            playlist = self._playlist_from_api_or_html(url)
            for track in playlist.tracks:
                candidate = _candidate_from_track(track, playlist)
                if candidate:
                    candidates.append(candidate)
        return candidates

    def _playlist_from_api_or_html(self, url: str) -> SoundCloudPlaylist:
        if self.client.can_use_api:
            try:
                return self.client.resolve_playlist(url)
            except requests.RequestException as exc:
                if not self.use_html_fallback:
                    raise RuntimeError(f"SoundCloud API failed for {url}: {exc}") from exc
                LOGGER.warning("SoundCloud API failed for %s; falling back to page HTML: %s", url, exc)
        elif not self.use_html_fallback:
            raise RuntimeError(
                "SoundCloud API credentials are missing. Set SC_CLIENT_ID plus either sc_token.json "
                "or SC_ACCESS_TOKEN, or allow HTML fallback."
            )

        html = self._fetch_html(url)
        return _playlist_from_html(html, fallback_url=url)

    def _fetch_html(self, url: str) -> str:
        try:
            response = requests.get(url, headers=HEADERS, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Unable to fetch SoundCloud playlist {url}: {exc}") from exc
        return response.text


class SoundCloudTokenManager:
    def __init__(self, token_file: str | Path | None = None) -> None:
        self.client_id = _env_first("SC_CLIENT_ID", "SOUNDCLOUD_CLIENT_ID")
        self.client_secret = _env_first("SC_CLIENT_SECRET", "SOUNDCLOUD_CLIENT_SECRET")
        self.access_token = _env_first("SC_ACCESS_TOKEN", "SOUNDCLOUD_ACCESS_TOKEN")
        self.refresh_token = _env_first("SC_REFRESH_TOKEN", "SOUNDCLOUD_REFRESH_TOKEN")
        token_file_value = token_file or _env_first("SC_TOKEN_FILE", "SOUNDCLOUD_TOKEN_FILE") or "sc_token.json"
        self.token_file = Path(token_file_value)
        self._token_data: dict | None = None

    @property
    def has_any_auth(self) -> bool:
        return bool(self.access_token or self.refresh_token or self.token_file.exists())

    @property
    def can_refresh(self) -> bool:
        return bool(self.refresh_token or self.token_file.exists())

    def auth_header(self) -> dict[str, str]:
        token = self.get_valid_token()
        scheme = self.auth_scheme()
        return {"Authorization": f"{scheme} {token}"} if token else {}

    def auth_scheme(self) -> str:
        configured = _env_first("SC_AUTH_SCHEME", "SOUNDCLOUD_AUTH_SCHEME")
        if configured:
            return configured
        token_data = self.load_token()
        token_type = clean_text(str(token_data.get("token_type") or ""))
        if token_type:
            return token_type
        return "Bearer"

    def force_refresh(self) -> str | None:
        token_data = self.load_token()
        if not token_data:
            return None
        refreshed = self.refresh_access_token(token_data)
        return str(refreshed.get("access_token") or "")

    def get_valid_token(self) -> str | None:
        if self.access_token and not self.token_file.exists():
            return self.access_token
        token_data = self.load_token()
        if not token_data and self.access_token:
            return self.access_token
        if not token_data:
            return None
        if self._token_expiring(token_data):
            token_data = self.refresh_access_token(token_data)
        return str(token_data.get("access_token") or "")

    def load_token(self) -> dict:
        if self._token_data is not None:
            return self._token_data
        if not self.token_file.exists():
            self._token_data = {}
            return self._token_data
        try:
            self._token_data = json.loads(self.token_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Unable to read SoundCloud token file {self.token_file}: {exc}") from exc
        return self._token_data

    def save_token(self, token_data: dict) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
        self._token_data = token_data

    def refresh_access_token(self, token_data: dict) -> dict:
        refresh_token = str(token_data.get("refresh_token") or self.refresh_token or "")
        if not refresh_token:
            raise RuntimeError("SoundCloud access token expired and no refresh_token is available.")
        if not self.client_id or not self.client_secret:
            raise RuntimeError("SoundCloud token refresh requires SC_CLIENT_ID and SC_CLIENT_SECRET.")

        response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
            },
            timeout=30,
        )
        response.raise_for_status()
        refreshed = response.json()
        expires_in = int(refreshed.get("expires_in") or 3600)
        refreshed["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).timestamp()
        if "refresh_token" not in refreshed:
            refreshed["refresh_token"] = refresh_token
        self.save_token(refreshed)
        return refreshed

    def _token_expiring(self, token_data: dict) -> bool:
        expires_at = token_data.get("expires_at")
        if not expires_at:
            return bool(token_data.get("refresh_token"))
        try:
            if isinstance(expires_at, (int, float)):
                expiry = datetime.fromtimestamp(float(expires_at), tz=timezone.utc)
            else:
                expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        return expiry <= datetime.now(timezone.utc) + timedelta(seconds=TOKEN_REFRESH_BUFFER_SECONDS)


class SoundCloudAPIClient:
    def __init__(self, timeout: float = 20.0, token_file: str | Path | None = None) -> None:
        self.timeout = timeout
        self.token_manager = SoundCloudTokenManager(token_file=token_file)
        self.client_id = self.token_manager.client_id

    @property
    def can_use_api(self) -> bool:
        return bool(self.token_manager.has_any_auth or self.client_id)

    def resolve_playlist(self, playlist_url: str) -> SoundCloudPlaylist:
        data = self.get("/resolve", url=playlist_url)
        if data.get("kind") not in {"playlist", "system-playlist"} and not data.get("tracks"):
            raise RuntimeError(f"SoundCloud URL did not resolve to a playlist: {playlist_url}")
        if not data.get("tracks") and data.get("id"):
            data = self.get(f"/playlists/{data['id']}")
        tracks = self._hydrate_tracks(data.get("tracks") or [])
        data["tracks"] = tracks
        return _playlist_from_api_data(data, playlist_url)

    def get(self, path_or_url: str, **params) -> dict:
        response = self._request("GET", path_or_url, params=params)
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Expected SoundCloud API object response from {path_or_url}")
        return payload

    def _request(self, method: str, path_or_url: str, params: dict | None = None) -> requests.Response:
        params = dict(params or {})
        params.setdefault("access", ACCESS_VALUES)
        url = path_or_url if path_or_url.startswith("http") else f"{API_BASE}{path_or_url if path_or_url.startswith('/') else '/' + path_or_url}"
        response = self._send(method, url, params=params, include_auth=True)
        if getattr(response, "status_code", 200) == 401 and self.token_manager.can_refresh:
            LOGGER.info("SoundCloud API returned 401; refreshing OAuth token and retrying once")
            try:
                self.token_manager.force_refresh()
                response = self._send(method, url, params=params, include_auth=True)
            except (RuntimeError, requests.RequestException) as exc:
                LOGGER.warning("SoundCloud token refresh retry failed: %s", exc)
        if getattr(response, "status_code", 200) == 401 and self.client_id:
            LOGGER.info("SoundCloud API still returned 401; retrying public client_id request without OAuth header")
            response = self._send(method, url, params=params, include_auth=False)
        _raise_for_status_with_body(response)
        return response

    def _send(self, method: str, url: str, params: dict, include_auth: bool) -> requests.Response:
        params = dict(params)
        headers = {"Accept": "application/json"}
        if include_auth:
            headers.update(self.token_manager.auth_header())
        elif self.client_id and "client_id" not in params:
            params["client_id"] = self.client_id
        return requests.request(method, url, headers=headers, params=params, timeout=self.timeout)

    def _hydrate_tracks(self, tracks: list[dict]) -> list[dict]:
        hydrated: list[dict] = []
        missing_ids: list[str] = []
        for track in tracks:
            if not isinstance(track, dict):
                continue
            if track.get("title") and track.get("permalink_url"):
                hydrated.append(track)
            elif track.get("id"):
                missing_ids.append(str(track["id"]))
        for track_id in missing_ids:
            try:
                hydrated.append(self.get(f"/tracks/{track_id}"))
            except requests.RequestException as exc:
                LOGGER.warning("Unable to hydrate SoundCloud track %s: %s", track_id, exc)
        return hydrated


def _raise_for_status_with_body(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        body = response.text[:1000] if response.text else ""
        message = f"{exc}"
        if body:
            message = f"{message} | response body: {body}"
        raise requests.HTTPError(message, response=response) from exc


def playlist_values_from_file(path: str | Path) -> list[str]:
    values: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            values.append(stripped)
    return values


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _playlist_url(value: str) -> str:
    text = clean_text(value)
    if not text:
        raise ValueError("Empty SoundCloud playlist value")
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        if "soundcloud.com" not in parsed.netloc:
            raise ValueError(f"Expected a soundcloud.com URL, got {value!r}")
        return text
    if text.startswith("soundcloud.com/"):
        return f"https://{text}"
    if "/" in text:
        return f"{SOUNDCLOUD_ROOT}/{text.strip('/')}"
    raise ValueError(
        "SoundCloud playlists must be playlist URLs or user/path values like "
        "'artist/sets/playlist-name'."
    )


def _playlist_from_html(html: str, fallback_url: str) -> SoundCloudPlaylist:
    hydration = _extract_sc_hydration(html)
    playlist_data = _find_hydration_playlist(hydration)
    if playlist_data:
        return _playlist_from_hydration_data(playlist_data, fallback_url)
    json_ld = _extract_json_ld_playlist(html)
    if json_ld:
        return json_ld
    raise RuntimeError(
        "Could not find SoundCloud playlist data in the page. "
        "The playlist may be private, unavailable, or rendered in a new format."
    )


def _extract_sc_hydration(html: str) -> list[dict]:
    for match in re.finditer(r"window\.__sc_hydration\s*=\s*(\[.*?\])\s*;", html, re.DOTALL):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
    return []


def _find_hydration_playlist(hydration: list[dict]) -> dict | None:
    for item in hydration:
        data = item.get("data")
        if not isinstance(data, dict):
            continue
        if _looks_like_playlist(data):
            return data
        collection = data.get("collection")
        if isinstance(collection, list):
            for entry in collection:
                if isinstance(entry, dict) and _looks_like_playlist(entry):
                    return entry
    return None


def _looks_like_playlist(data: dict) -> bool:
    return isinstance(data.get("tracks"), list) and (
        data.get("kind") in {"playlist", "system-playlist"} or data.get("track_count") is not None
    )


def _playlist_from_hydration_data(data: dict, fallback_url: str) -> SoundCloudPlaylist:
    user = data.get("user") or {}
    return SoundCloudPlaylist(
        title=clean_text(data.get("title") or ""),
        url=str(data.get("permalink_url") or fallback_url),
        owner=clean_text(user.get("username") or ""),
        playlist_id=str(data.get("id") or ""),
        track_count=str(data.get("track_count") or len(data.get("tracks") or [])),
        likes_count=str(data.get("likes_count") or data.get("favoritings_count") or ""),
        reposts_count=str(data.get("reposts_count") or ""),
        tracks=[track for track in data.get("tracks") or [] if isinstance(track, dict)],
    )


def _playlist_from_api_data(data: dict, fallback_url: str) -> SoundCloudPlaylist:
    playlist = _playlist_from_hydration_data(data, fallback_url)
    return SoundCloudPlaylist(
        title=playlist.title,
        url=playlist.url,
        owner=playlist.owner,
        playlist_id=playlist.playlist_id,
        track_count=playlist.track_count,
        likes_count=playlist.likes_count,
        reposts_count=playlist.reposts_count,
        tracks=playlist.tracks,
        extraction_method="soundcloud_playlist_api",
    )


def _extract_json_ld_playlist(html: str) -> SoundCloudPlaylist | None:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        payloads = parsed if isinstance(parsed, list) else [parsed]
        for payload in payloads:
            if not isinstance(payload, dict) or "track" not in payload:
                continue
            tracks = payload.get("track") or []
            if isinstance(tracks, dict):
                tracks = [tracks]
            return SoundCloudPlaylist(
                title=clean_text(payload.get("name") or ""),
                url=str(payload.get("url") or ""),
                owner=clean_text((payload.get("byArtist") or {}).get("name") if isinstance(payload.get("byArtist"), dict) else ""),
                playlist_id="",
                track_count=str(len(tracks)),
                likes_count="",
                reposts_count="",
                tracks=[_track_from_json_ld(track) for track in tracks if isinstance(track, dict)],
                extraction_method="soundcloud_playlist_page",
            )
    return None


def _track_from_json_ld(track: dict) -> dict:
    by_artist = track.get("byArtist") or {}
    return {
        "title": track.get("name"),
        "permalink_url": track.get("url"),
        "user": {"username": by_artist.get("name") if isinstance(by_artist, dict) else ""},
        "publisher_metadata": {
            "artist": by_artist.get("name") if isinstance(by_artist, dict) else "",
            "release_title": track.get("name"),
        },
    }


def _candidate_from_track(track: dict, playlist: SoundCloudPlaylist) -> ReleaseCandidate | None:
    title_raw = clean_text(track.get("title") or "")
    if not title_raw:
        return None

    publisher = track.get("publisher_metadata") or {}
    user = track.get("user") or {}
    artist, title = _artist_and_title(track)
    if not artist or not title:
        return None

    track_url = str(track.get("permalink_url") or "")
    release_date = _release_date(track)
    open_graph = {
        "playlist_id": playlist.playlist_id,
        "playlist_name": playlist.title,
        "playlist_owner": playlist.owner,
        "playlist_url": playlist.url,
        "playlist_track_count": playlist.track_count,
        "playlist_likes_count": playlist.likes_count,
        "playlist_reposts_count": playlist.reposts_count,
        "soundcloud_track_id": str(track.get("id") or ""),
        "soundcloud_user_id": str(user.get("id") or ""),
        "soundcloud_username": clean_text(user.get("username") or ""),
        "all_artists": clean_text(publisher.get("artist") or artist),
        "genre": clean_text(track.get("genre") or ""),
        "tag_list": clean_text(track.get("tag_list") or ""),
        "label": clean_text(track.get("label_name") or publisher.get("publisher") or ""),
        "album_name": clean_text(publisher.get("album_title") or ""),
        "isrc": clean_text(publisher.get("isrc") or ""),
        "upc": clean_text(publisher.get("upc_or_ean") or ""),
        "explicit": str(bool(publisher.get("explicit") or track.get("publisher_metadata", {}).get("explicit"))),
        "duration_ms": str(track.get("duration") or ""),
        "playback_count": str(track.get("playback_count") or ""),
        "likes_count": str(track.get("likes_count") or track.get("favoritings_count") or ""),
        "reposts_count": str(track.get("reposts_count") or ""),
        "created_at": clean_text(track.get("created_at") or ""),
        "purchase_url": str(track.get("purchase_url") or ""),
        "license": clean_text(track.get("license") or ""),
    }

    return ReleaseCandidate(
        artist=artist,
        track_or_project_title=title,
        release_type=_release_type(title),
        confidence_score=_confidence(track, artist, title_raw),
        extraction_method=playlist.extraction_method,
        source_article_title=f"{artist} - {title}",
        source_article_url=track_url or playlist.url,
        source_name=SOURCE_NAME,
        article_date=release_date,
        embedded_music_links=[track_url] if track_url else [],
        open_graph=open_graph,
    )


def _artist_and_title(track: dict) -> tuple[str, str]:
    raw_title = clean_text(track.get("title") or "")
    publisher = track.get("publisher_metadata") or {}
    user = track.get("user") or {}
    publisher_artist = clean_text(publisher.get("artist") or "")
    publisher_title = clean_text(publisher.get("release_title") or "")
    username = clean_text(user.get("username") or "")

    if publisher_artist:
        title = publisher_title or _strip_artist_prefix(raw_title, publisher_artist) or raw_title
        return publisher_artist, title

    parsed = _parse_artist_title(raw_title)
    if parsed:
        return parsed

    return username, raw_title


def _parse_artist_title(value: str) -> tuple[str, str] | None:
    text = clean_text(value)
    for separator in (" - ", " – ", " — "):
        if separator in text:
            artist, title = text.split(separator, 1)
            artist = clean_text(artist)
            title = clean_text(title)
            if artist and title:
                return artist, title
    return None


def _strip_artist_prefix(title: str, artist: str) -> str | None:
    escaped = re.escape(artist)
    match = re.match(rf"^{escaped}\s*[-–—]\s*(.+)$", title, re.IGNORECASE)
    if match:
        return clean_text(match.group(1))
    return None


def _release_date(track: dict) -> str | None:
    for key in ("release_date", "display_date", "created_at"):
        value = clean_text(track.get(key) or "")
        if not value:
            continue
        match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
        if match:
            return match.group(1)
        match = re.match(r"(\d{4}/\d{2}/\d{2})", value)
        if match:
            return match.group(1).replace("/", "-")
    return None


def _release_type(title: str) -> str:
    lowered = title.lower()
    if "remix" in lowered:
        return "remix"
    if "rework" in lowered:
        return "rework"
    return "track"


def _confidence(track: dict, artist: str, raw_title: str) -> float:
    score = 0.65
    if track.get("permalink_url"):
        score += 0.10
    if (track.get("publisher_metadata") or {}).get("isrc"):
        score += 0.10
    if (track.get("publisher_metadata") or {}).get("artist") or _parse_artist_title(raw_title):
        score += 0.10
    if artist:
        score += 0.05
    return min(score, 1.0)
