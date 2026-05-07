from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

import requests

from src.soundcloud_api import SoundCloudAPIClient

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SoundCloudArtistMatch:
    url: str
    user_id: str
    username: str
    confidence: float


class SoundCloudArtistLookup:
    def __init__(self, client: SoundCloudAPIClient | None = None, min_confidence: float = 0.72) -> None:
        self.client = client or SoundCloudAPIClient()
        self.min_confidence = min_confidence

    def search_artist(self, artist_name: str) -> SoundCloudArtistMatch | None:
        if not self.client.can_use_api:
            LOGGER.debug("SoundCloud credentials missing; cannot search for %s", artist_name)
            return None
        try:
            users = self.client.search_users(artist_name, limit=8)
        except requests.RequestException as exc:
            LOGGER.warning("SoundCloud user search failed for %s: %s", artist_name, exc)
            return None
        ranked = sorted(
            (
                (self._score_user(artist_name, user), user)
                for user in users
                if user.get("id") and user.get("permalink_url")
            ),
            key=lambda item: item[0],
        )
        if not ranked:
            return None
        score, user = ranked[-1]
        if score < self.min_confidence:
            return None
        return SoundCloudArtistMatch(
            url=str(user.get("permalink_url") or ""),
            user_id=str(user.get("id") or ""),
            username=str(user.get("username") or ""),
            confidence=round(score, 3),
        )

    def _score_user(self, artist_name: str, user: dict) -> float:
        target = normalize_name(artist_name)
        username = normalize_name(str(user.get("username") or ""))
        permalink = normalize_name(str(user.get("permalink") or ""))
        score = 0.0
        if username == target:
            score += 0.65
        elif target and (target in username or username in target):
            score += 0.35
        if permalink == target:
            score += 0.25
        elif target and target.replace(" ", "") == permalink.replace(" ", ""):
            score += 0.20
        followers = int(user.get("followers_count") or 0)
        if followers >= 100_000:
            score += 0.10
        elif followers >= 10_000:
            score += 0.06
        elif followers >= 1_000:
            score += 0.03
        if user.get("verified"):
            score += 0.10
        return min(score, 1.0)


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()
