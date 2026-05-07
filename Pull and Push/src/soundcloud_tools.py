from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from src.models import ResolvedTrack
from src.normalize import clean_text, normalize_text, normalize_title

LOGGER = logging.getLogger(__name__)

API_BASE = "https://api.soundcloud.com"
TOKEN_URL = "https://secure.soundcloud.com/oauth/token"
ACCESS_VALUES = "playable,preview,blocked"
TOKEN_REFRESH_BUFFER_SECONDS = 300
SOUNDCLOUD_TRACK_RE = re.compile(r"https?://(?:www\.)?soundcloud\.com/[^/]+/[^/?#]+")


class SoundCloudTokenManager:
    def __init__(self, data_root: Path, token_file: str | Path | None = None) -> None:
        load_dotenv()
        fallback_env = data_root / "SoundCloud_Playlists" / ".env"
        self.fallback_env_dir = fallback_env.parent if fallback_env.exists() else None
        if fallback_env.exists():
            load_dotenv(fallback_env, override=False)
        self.client_id = _env_first("SC_CLIENT_ID", "SOUNDCLOUD_CLIENT_ID")
        self.client_secret = _env_first("SC_CLIENT_SECRET", "SOUNDCLOUD_CLIENT_SECRET")
        self.access_token = _env_first("SC_ACCESS_TOKEN", "SOUNDCLOUD_ACCESS_TOKEN")
        self.refresh_token = _env_first("SC_REFRESH_TOKEN", "SOUNDCLOUD_REFRESH_TOKEN")
        token_file_value = token_file or _env_first("SC_TOKEN_FILE", "SOUNDCLOUD_TOKEN_FILE") or "sc_token.json"
        self.token_file = self._resolve_token_file(Path(token_file_value))
        self._token_data: dict[str, Any] | None = None

    @property
    def can_use_api(self) -> bool:
        return bool(self.access_token or self.client_id or self.token_file.exists())

    @property
    def can_refresh(self) -> bool:
        return bool(self.refresh_token or self.token_file.exists())

    def auth_header(self) -> dict[str, str]:
        token = self.get_valid_token()
        return {"Authorization": f"{self.auth_scheme()} {token}"} if token else {}

    def auth_scheme(self) -> str:
        configured = _env_first("SC_AUTH_SCHEME", "SOUNDCLOUD_AUTH_SCHEME")
        if configured:
            return configured
        token_data = self.load_token()
        return str(token_data.get("token_type") or "OAuth")

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

    def load_token(self) -> dict[str, Any]:
        if self._token_data is not None:
            return self._token_data
        if not self.token_file.exists():
            self._token_data = {}
            return self._token_data
        self._token_data = json.loads(self.token_file.read_text(encoding="utf-8"))
        return self._token_data

    def refresh_access_token(self, token_data: dict[str, Any]) -> dict[str, Any]:
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
        refreshed = parse_json_response(response)
        if not isinstance(refreshed, dict):
            raise RuntimeError("SoundCloud token refresh returned an unexpected non-object response.")
        expires_in = int(refreshed.get("expires_in") or 3600)
        refreshed["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).timestamp()
        if "refresh_token" not in refreshed:
            refreshed["refresh_token"] = refresh_token
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps(refreshed, indent=2), encoding="utf-8")
        self._token_data = refreshed
        return refreshed

    def _token_expiring(self, token_data: dict[str, Any]) -> bool:
        expires_at = token_data.get("expires_at")
        if not expires_at:
            return bool(token_data.get("refresh_token"))
        try:
            expiry = (
                datetime.fromtimestamp(float(expires_at), tz=timezone.utc)
                if isinstance(expires_at, (int, float))
                else datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            )
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        return expiry <= datetime.now(timezone.utc) + timedelta(seconds=TOKEN_REFRESH_BUFFER_SECONDS)

    def _resolve_token_file(self, path: Path) -> Path:
        if path.is_absolute() or path.exists():
            return path
        if self.fallback_env_dir and (self.fallback_env_dir / path).exists():
            return self.fallback_env_dir / path
        return path


class SoundCloudTools:
    def __init__(self, data_root: Path, timeout: float = 20.0) -> None:
        self.timeout = timeout
        self.token_manager = SoundCloudTokenManager(data_root)
        self.client_id = self.token_manager.client_id

    @property
    def can_use_api(self) -> bool:
        return self.token_manager.can_use_api

    def resolve_track(self, item: dict[str, Any], lookback_days: int = 7, today: date | None = None) -> dict[str, str | None]:
        current_day = today or date.today()
        cutoff = current_day - timedelta(days=lookback_days)
        direct_url = soundcloud_url_from_record(item)
        direct_id = soundcloud_track_id_from_record(item)
        if direct_id and direct_url:
            return {"soundcloud_track_id": direct_id, "soundcloud_url": direct_url}
        if direct_url:
            try:
                resolved = self.get("/resolve", url=direct_url)
                if resolved.get("kind") == "track":
                    return {
                        "soundcloud_track_id": str(resolved.get("id") or direct_id or ""),
                        "soundcloud_url": str(resolved.get("permalink_url") or direct_url),
                    }
            except requests.RequestException as exc:
                LOGGER.warning("SoundCloud resolve failed for %s: %s", direct_url, exc)
            return {"soundcloud_track_id": direct_id or None, "soundcloud_url": direct_url}

        artist = clean_text(item.get("artist"))
        title = clean_text(item.get("track_or_project_title"))
        if not artist or not title:
            return {"soundcloud_track_id": None, "soundcloud_url": None}
        tracks_by_id: dict[str, dict[str, Any]] = {}
        try:
            for query in soundcloud_search_queries(artist, title):
                for track in self.get_collection("/tracks", limit=25, max_items=25, q=query):
                    track_id = str(track.get("id") or track.get("permalink_url") or "")
                    if track_id:
                        tracks_by_id[track_id] = track
        except requests.RequestException as exc:
            LOGGER.warning("SoundCloud search failed for %s - %s: %s", artist, title, exc)
            return {"soundcloud_track_id": None, "soundcloud_url": None}
        best = best_soundcloud_match(artist, title, list(tracks_by_id.values()), lookback_days=lookback_days, today=current_day)
        if not best:
            return {"soundcloud_track_id": None, "soundcloud_url": None}
        return {
            "soundcloud_track_id": str(best.get("id") or ""),
            "soundcloud_url": str(best.get("permalink_url") or ""),
        }

    def find_or_create_playlist(self, name: str, sharing: str = "private") -> str:
        for playlist in self.get_collection("/me/playlists", limit=50):
            if clean_text(playlist.get("title")).lower() == name.lower():
                return str(playlist.get("id") or "")
        payload = self.post(
            "/playlists",
            form_body={"playlist[title]": name, "playlist[sharing]": sharing},
        )
        return str(payload.get("id") or "")

    def replace_playlist_tracks(self, playlist_id: str, track_ids: list[str]) -> None:
        form_body = playlist_tracks_form(track_ids)
        # Sending the final track list directly replaces the old playlist
        # contents, so we do not need a separate empty-list update.
        self.put(f"/playlists/{playlist_id}", form_body=form_body)
        playlist = self.get(f"/playlists/{playlist_id}")
        updated_tracks = playlist.get("tracks") or []
        updated_count = len(updated_tracks) if isinstance(updated_tracks, list) else 0
        expected_count = len({str(track_id) for track_id in track_ids if str(track_id).isdigit()})
        if expected_count and updated_count == 0:
            raise RuntimeError(
                "SoundCloud accepted the playlist update but returned 0 tracks. "
                "The API may have ignored the track-list payload."
            )

    def get(self, path_or_url: str, **params) -> dict[str, Any]:
        payload = self.get_json(path_or_url, **params)
        return payload if isinstance(payload, dict) else {}

    def get_json(self, path_or_url: str, **params) -> Any:
        return parse_json_response(self._request("GET", path_or_url, params=params))

    def get_collection(self, path_or_url: str, limit: int = 50, max_items: int | None = None, **params) -> list[dict[str, Any]]:
        params = dict(params)
        params.setdefault("limit", min(limit, 200))
        params.setdefault("linked_partitioning", 1)
        next_url: str | None = path_or_url
        collection: list[dict[str, Any]] = []
        while next_url:
            payload = self.get_json(next_url, **params)
            params = {}
            if isinstance(payload, list):
                items = payload
                next_url = None
            else:
                items = payload.get("collection") if isinstance(payload, dict) else []
                next_url = payload.get("next_href") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                items = []
            collection.extend(item for item in items if isinstance(item, dict))
            if max_items and len(collection) >= max_items:
                return collection[:max_items]
        return collection

    def post(self, path_or_url: str, form_body: FormBody | None = None, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = parse_json_response(self._request("POST", path_or_url, form_body=form_body, json_body=json_body))
        return payload if isinstance(payload, dict) else {}

    def put(self, path_or_url: str, form_body: FormBody | None = None, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = parse_json_response(self._request("PUT", path_or_url, form_body=form_body, json_body=json_body))
        return payload if isinstance(payload, dict) else {}

    def _request(
        self,
        method: str,
        path_or_url: str,
        params: dict[str, Any] | None = None,
        form_body: FormBody | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> requests.Response:
        params = dict(params or {})
        if method.upper() == "GET":
            params.setdefault("access", ACCESS_VALUES)
        url = path_or_url if path_or_url.startswith("http") else f"{API_BASE}{path_or_url if path_or_url.startswith('/') else '/' + path_or_url}"
        response = self._send(method, url, params=params, form_body=form_body, json_body=json_body, include_auth=True)
        if response.status_code == 401 and self.token_manager.can_refresh:
            LOGGER.info("SoundCloud API returned 401; refreshing OAuth token and retrying once")
            self.token_manager.refresh_access_token(self.token_manager.load_token())
            response = self._send(method, url, params=params, form_body=form_body, json_body=json_body, include_auth=True)
        if method.upper() == "GET" and response.status_code == 401 and self.client_id:
            LOGGER.info("SoundCloud API still returned 401; retrying public client_id request without OAuth header")
            response = self._send(method, url, params=params, form_body=form_body, json_body=json_body, include_auth=False)
        raise_for_status_with_body(response)
        return response

    def _send(
        self,
        method: str,
        url: str,
        params: dict[str, Any],
        form_body: FormBody | None,
        json_body: dict[str, Any] | None,
        include_auth: bool,
    ) -> requests.Response:
        params = dict(params)
        headers = {"Accept": "application/json; charset=utf-8"}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        if include_auth:
            headers.update(self.token_manager.auth_header())
        elif self.client_id and "client_id" not in params:
            params["client_id"] = self.client_id
        return requests.request(method, url, headers=headers, params=params, data=form_body, json=json_body, timeout=self.timeout)


def raise_for_status_with_body(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        body = response.text[:1000] if response.text else ""
        message = str(exc)
        if body:
            message = f"{message} | response body: {body}"
        raise requests.HTTPError(message, response=response) from exc


def parse_json_response(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        method = response.request.method if response.request else "REQUEST"
        body = response.text[:1000] if response.text else ""
        content_type = response.headers.get("content-type", "")
        message = (
            "SoundCloud API returned a non-JSON response "
            f"for {method} {response.url} "
            f"(status={response.status_code}, content-type={content_type or 'unknown'})"
        )
        if body:
            message = f"{message} | response body: {body}"
        else:
            message = f"{message} | response body was empty"
        raise requests.RequestException(message, response=response) from exc


FormBody = dict[str, Any] | list[tuple[str, Any]]


def playlist_tracks_form(track_ids: list[str]) -> list[tuple[str, Any]]:
    form_body: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for track_id in track_ids:
        clean_id = str(track_id)
        if clean_id.isdigit() and clean_id not in seen:
            seen.add(clean_id)
            form_body.append(("playlist[tracks][][id]", clean_id))
    return form_body


def soundcloud_track_id_from_record(item: dict[str, Any]) -> str:
    open_graph = item.get("open_graph") or {}
    raw_id = clean_text(open_graph.get("soundcloud_track_id"))
    return raw_id if raw_id.isdigit() else ""


def soundcloud_url_from_record(item: dict[str, Any]) -> str:
    values = [item.get("source_article_url"), *(item.get("embedded_music_links") or [])]
    for value in values:
        text = str(value or "")
        match = SOUNDCLOUD_TRACK_RE.search(text)
        if match and "/sets/" not in match.group(0):
            return match.group(0)
    return ""


def best_soundcloud_match(
    artist: str,
    title: str,
    tracks: list[dict[str, Any]],
    lookback_days: int = 7,
    today: date | None = None,
) -> dict[str, Any] | None:
    current_day = today or date.today()
    cutoff = current_day - timedelta(days=lookback_days)
    target_artists = [normalize_text(alias) for alias in artist_aliases(artist)]
    target_artists = [alias for alias in target_artists if alias]
    target_title = normalize_title(title)
    best: tuple[float, dict[str, Any]] | None = None
    for track in tracks:
        candidate_title = normalize_title(track.get("title"))
        candidate_artists = soundcloud_candidate_artists(track)
        identity_artists = soundcloud_identity_artists(track)
        candidate_all = normalize_text(f"{' '.join(candidate_artists)} {candidate_title}")
        title_score = soundcloud_title_score(target_title, candidate_title, candidate_all)
        artist_score = soundcloud_artist_score(target_artists, candidate_artists)
        identity_score = soundcloud_artist_score(target_artists, identity_artists)
        if title_score < 0.72 or artist_score < 0.72 or identity_score < 0.72:
            continue
        if not soundcloud_track_is_in_window(track, cutoff=cutoff, current_day=current_day):
            continue
        popularity = min(float(track.get("playback_count") or 0) / 1_000_000, 1.0)
        score = (title_score * 0.55) + (artist_score * 0.40) + (popularity * 0.05)
        if best is None or score > best[0]:
            best = (score, track)
    if best and best[0] >= 0.76:
        return best[1]
    return None


def soundcloud_search_queries(artist: str, title: str) -> list[str]:
    queries: list[str] = []
    for alias in artist_aliases(artist)[:4]:
        queries.append(f"{alias} {title}")
    return unique_nonempty(queries)


def artist_aliases(artist: str) -> list[str]:
    text = clean_text(artist)
    without_parens = re.sub(r"\([^)]*\)", " ", text)
    parts = re.split(r"\s*(?:,|\bx\b|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b)\s*", without_parens, flags=re.IGNORECASE)
    aliases = [text, without_parens, *parts]
    return unique_nonempty(clean_text(alias) for alias in aliases)


def soundcloud_candidate_artists(track: dict[str, Any]) -> list[str]:
    values = [*soundcloud_identity_artists(track)]
    title = clean_text(track.get("title"))
    parsed = parse_track_artist_prefix(title)
    if parsed:
        values.append(parsed)
    return unique_nonempty(normalize_text(value) for value in values if value)


def soundcloud_identity_artists(track: dict[str, Any]) -> list[str]:
    user = track.get("user") or {}
    publisher = track.get("publisher_metadata") or {}
    values = [
        publisher.get("artist"),
        publisher.get("writer_composer"),
        user.get("username"),
        user.get("permalink"),
    ]
    return unique_nonempty(normalize_text(value) for value in values if value)


def parse_track_artist_prefix(title: str) -> str:
    for separator in (" - ", " – ", " — "):
        if separator in title:
            return title.split(separator, 1)[0]
    return ""


def soundcloud_title_score(target_title: str, candidate_title: str, candidate_all: str) -> float:
    if candidate_title == target_title:
        return 1.0
    if target_title and target_title in candidate_title:
        return 0.86
    if target_title and target_title in candidate_all:
        return 0.74
    return 0.0


def soundcloud_artist_score(target_artists: list[str], candidate_artists: list[str], candidate_all: str = "") -> float:
    score = 0.0
    for target_artist in target_artists:
        for candidate_artist in candidate_artists:
            if target_artist == candidate_artist:
                score = max(score, 1.0)
            elif len(target_artist) >= 5 and len(candidate_artist) >= 5 and (target_artist in candidate_artist or candidate_artist in target_artist):
                score = max(score, 0.84)
    return score


def soundcloud_track_is_in_window(track: dict[str, Any], cutoff: date, current_day: date) -> bool:
    release_date = soundcloud_track_date(track)
    if release_date is None:
        return True
    return cutoff <= release_date <= current_day


def soundcloud_track_date(track: dict[str, Any]) -> date | None:
    structured = soundcloud_structured_release_date(track)
    if structured:
        return structured
    for key in ("release_date", "display_date", "created_at"):
        value = clean_text(track.get(key))
        if not value:
            continue
        for fmt in ("%Y-%m-%d", "%Y/%m/%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(value[: len(fmt)], fmt).date()
            except ValueError:
                continue
        match = re.match(r"(\d{4})[-/](\d{2})[-/](\d{2})", value)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                return None
    return None


def soundcloud_structured_release_date(track: dict[str, Any]) -> date | None:
    year = parse_int(track.get("release_year"))
    month = parse_int(track.get("release_month"))
    day = parse_int(track.get("release_day"))
    if not year:
        return None
    month = month or 1
    day = day or 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        text = str(value).strip()
        return int(text) if text else None
    except ValueError:
        return None


def unique_nonempty(values) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = clean_text(value)
        if text and text.lower() not in seen:
            seen.add(text.lower())
            unique.append(text)
    return unique


def soundcloud_ids_from_tracks(tracks: list[ResolvedTrack]) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for track in tracks:
        track_id = clean_text(track.soundcloud_track_id)
        if track_id and track_id not in seen:
            seen.add(track_id)
            ids.append(track_id)
    return ids


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip().strip('"').strip("'")
    return None
