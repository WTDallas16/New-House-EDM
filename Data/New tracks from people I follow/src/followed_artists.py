from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from src.soundcloud_api import SoundCloudAPIClient

LOGGER = logging.getLogger(__name__)

EDM_KEYWORDS = {
    "edm",
    "electronic",
    "electronica",
    "dance",
    "house",
    "tech house",
    "deep house",
    "afro house",
    "melodic house",
    "progressive house",
    "bass house",
    "future house",
    "disco house",
    "techno",
    "trance",
    "dubstep",
    "drum and bass",
    "dnb",
    "garage",
    "ukg",
    "breaks",
    "trap",
    "bass",
    "club",
}


@dataclass(slots=True)
class FollowedArtist:
    artist_name: str
    soundcloud_url: str
    soundcloud_user_id: str
    genres: list[str] = field(default_factory=list)
    edm_match_terms: list[str] = field(default_factory=list)
    followers_count: int | None = None
    track_count: int | None = None
    country: str = ""
    city: str = ""

    def csv_row(self) -> dict[str, str | int | None]:
        return {
            "artist_name": self.artist_name,
            "soundcloud_url": self.soundcloud_url,
            "soundcloud_user_id": self.soundcloud_user_id,
            "genres": " | ".join(self.genres),
            "edm_match_terms": " | ".join(self.edm_match_terms),
            "followers_count": self.followers_count,
            "track_count": self.track_count,
            "country": self.country,
            "city": self.city,
        }


def build_followed_artists(
    client: SoundCloudAPIClient,
    max_users: int | None = None,
    track_sample_limit: int = 10,
    edm_only: bool = True,
) -> list[FollowedArtist]:
    if not client.can_use_api:
        raise RuntimeError("SoundCloud API credentials are unavailable.")
    followed_users = client.followings(max_users=max_users)
    artists: list[FollowedArtist] = []
    for index, user in enumerate(followed_users, start=1):
        user_id = str(user.get("id") or "")
        username = clean_text(user.get("username") or "")
        if not user_id or not username:
            continue
        LOGGER.info("Inspecting followed SoundCloud user %s (%d/%d)", username, index, len(followed_users))
        genres = collect_user_genres(client, user_id, track_sample_limit=track_sample_limit)
        match_terms = edm_terms_for_user(user, genres)
        if edm_only and not match_terms:
            continue
        artists.append(
            FollowedArtist(
                artist_name=username,
                soundcloud_url=str(user.get("permalink_url") or ""),
                soundcloud_user_id=user_id,
                genres=genres,
                edm_match_terms=match_terms,
                followers_count=int_or_none(user.get("followers_count")),
                track_count=int_or_none(user.get("track_count")),
                country=clean_text(user.get("country_code") or user.get("country") or ""),
                city=clean_text(user.get("city") or ""),
            )
        )
    return artists


def collect_user_genres(client: SoundCloudAPIClient, user_id: str, track_sample_limit: int = 10) -> list[str]:
    try:
        tracks = client.user_tracks(user_id, limit=track_sample_limit)
    except requests.RequestException as exc:
        LOGGER.warning("Could not inspect tracks for SoundCloud user %s: %s", user_id, exc)
        return []
    genres: list[str] = []
    for track in tracks:
        for value in (track.get("genre"), track.get("tag_list")):
            for genre in split_genre_terms(str(value or "")):
                if genre and genre not in genres:
                    genres.append(genre)
    return genres


def edm_terms_for_user(user: dict[str, Any], genres: list[str]) -> list[str]:
    haystack = " ".join(
        [
            str(user.get("username") or ""),
            str(user.get("description") or ""),
            " ".join(genres),
        ]
    ).lower()
    matches = sorted(term for term in EDM_KEYWORDS if term in haystack)
    return matches


def write_followed_artists_csv(artists: list[FollowedArtist], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "artist_name",
        "soundcloud_url",
        "soundcloud_user_id",
        "genres",
        "edm_match_terms",
        "followers_count",
        "track_count",
        "country",
        "city",
    ]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for artist in artists:
            writer.writerow(artist.csv_row())


def read_followed_artists_csv(path: Path) -> list[FollowedArtist]:
    artists: list[FollowedArtist] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            artists.append(
                FollowedArtist(
                    artist_name=clean_text(row.get("artist_name") or ""),
                    soundcloud_url=clean_text(row.get("soundcloud_url") or ""),
                    soundcloud_user_id=clean_text(row.get("soundcloud_user_id") or ""),
                    genres=[item.strip() for item in (row.get("genres") or "").split("|") if item.strip()],
                    edm_match_terms=[item.strip() for item in (row.get("edm_match_terms") or "").split("|") if item.strip()],
                    followers_count=int_or_none(row.get("followers_count")),
                    track_count=int_or_none(row.get("track_count")),
                    country=clean_text(row.get("country") or ""),
                    city=clean_text(row.get("city") or ""),
                )
            )
    return artists


def split_genre_terms(value: str) -> list[str]:
    text = clean_text(value).strip('"')
    if not text:
        return []
    pieces = re.split(r"[,#/;|]+", text)
    return [clean_text(piece.strip('" ')) for piece in pieces if clean_text(piece.strip('" '))]


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def int_or_none(value: Any) -> int | None:
    try:
        text = str(value).replace(",", "").strip()
        return int(float(text)) if text else None
    except (TypeError, ValueError):
        return None
