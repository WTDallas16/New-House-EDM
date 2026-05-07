from __future__ import annotations

import logging
import os
from pathlib import Path

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyClientCredentials

LOGGER = logging.getLogger(__name__)


class SpotifyArtistLookup:
    def __init__(self) -> None:
        load_dotenv()
        fallback_env = Path(__file__).resolve().parents[2] / "Spotify_Playlists" / ".env"
        if fallback_env.exists():
            load_dotenv(fallback_env, override=False)
        self.client_id = _env_first("SPOTIFY_CLIENT_ID", "SPOTIPY_CLIENT_ID", "clientid")
        self.client_secret = _env_first("SPOTIFY_CLIENT_SECRET", "SPOTIPY_CLIENT_SECRET", "secretclientid")
        self.client = self._client() if self.client_id and self.client_secret else None

    def search_artist_url(self, artist_name: str) -> str:
        if not self.client:
            LOGGER.debug("Spotify credentials missing; cannot search for %s", artist_name)
            return ""
        result = self.client.search(q=f'artist:"{artist_name}"', type="artist", limit=1)
        items = ((result.get("artists") or {}).get("items") or [])
        if not items:
            return ""
        return str((items[0].get("external_urls") or {}).get("spotify") or "")

    def _client(self) -> spotipy.Spotify:
        auth_manager = SpotifyClientCredentials(
            client_id=self.client_id,
            client_secret=self.client_secret,
        )
        return spotipy.Spotify(auth_manager=auth_manager)


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip().strip('"').strip("'")
    return None
