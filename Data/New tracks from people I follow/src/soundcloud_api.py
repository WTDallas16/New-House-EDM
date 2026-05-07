from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

LOGGER = logging.getLogger(__name__)

API_BASE = "https://api.soundcloud.com"
TOKEN_URL = "https://secure.soundcloud.com/oauth/token"
ACCESS_VALUES = "playable,preview,blocked"
TOKEN_REFRESH_BUFFER_SECONDS = 300


class SoundCloudTokenManager:
    def __init__(self, token_file: str | Path | None = None) -> None:
        load_dotenv()
        fallback_env = Path(__file__).resolve().parents[2] / "SoundCloud_Playlists" / ".env"
        self.fallback_env_dir: Path | None = fallback_env.parent if fallback_env.exists() else None
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
        return str(token_data.get("token_type") or "Bearer")

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

    def save_token(self, token_data: dict[str, Any]) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
        self._token_data = token_data

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
        refreshed = response.json()
        expires_in = int(refreshed.get("expires_in") or 3600)
        refreshed["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).timestamp()
        if "refresh_token" not in refreshed:
            refreshed["refresh_token"] = refresh_token
        self.save_token(refreshed)
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


class SoundCloudAPIClient:
    def __init__(self, timeout: float = 20.0, token_file: str | Path | None = None) -> None:
        self.timeout = timeout
        self.token_manager = SoundCloudTokenManager(token_file=token_file)
        self.client_id = self.token_manager.client_id

    @property
    def can_use_api(self) -> bool:
        return self.token_manager.can_use_api

    def get_json(self, path_or_url: str, **params) -> Any:
        response = self._request("GET", path_or_url, params=params)
        return response.json()

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
                items = payload.get("collection") or []
                next_url = payload.get("next_href")
            collection.extend(item for item in items if isinstance(item, dict))
            if max_items and len(collection) >= max_items:
                return collection[:max_items]
        return collection

    def followings(self, max_users: int | None = None) -> list[dict[str, Any]]:
        return self.get_collection("/me/followings", limit=200, max_items=max_users)

    def user_tracks(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.get_collection(f"/users/{user_id}/tracks", limit=min(limit, 200), max_items=limit)

    def _request(self, method: str, path_or_url: str, params: dict | None = None) -> requests.Response:
        params = dict(params or {})
        params.setdefault("access", ACCESS_VALUES)
        url = path_or_url if path_or_url.startswith("http") else f"{API_BASE}{path_or_url if path_or_url.startswith('/') else '/' + path_or_url}"
        response = self._send(method, url, params=params, include_auth=True)
        if response.status_code == 401 and self.token_manager.can_refresh:
            LOGGER.info("SoundCloud API returned 401; refreshing OAuth token and retrying once")
            self.token_manager.refresh_access_token(self.token_manager.load_token())
            response = self._send(method, url, params=params, include_auth=True)
        if response.status_code == 401 and self.client_id:
            LOGGER.info("SoundCloud API still returned 401; retrying public client_id request without OAuth header")
            response = self._send(method, url, params=params, include_auth=False)
        response.raise_for_status()
        return response

    def _send(self, method: str, url: str, params: dict, include_auth: bool) -> requests.Response:
        params = dict(params)
        headers = {"Accept": "application/json"}
        if include_auth:
            headers.update(self.token_manager.auth_header())
        elif self.client_id and "client_id" not in params:
            params["client_id"] = self.client_id
        return requests.request(method, url, headers=headers, params=params, timeout=self.timeout)


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip().strip('"').strip("'")
    return None
