from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

SPOTIFY_ARTIST_URL = "https://open.spotify.com/artist/{spotify_id}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass(slots=True)
class GenreTarget:
    url: str
    limit: int
    genre: str | None = None


@dataclass(slots=True)
class ArtistRow:
    artist_name: str
    spotify_url: str
    genre: str
    rank: int | None = None
    monthly_listeners: int | None = None
    spotify_id: str | None = None
    soundcloud_url: str = ""
    soundcloud_user_id: str = ""
    genres: list[str] = field(default_factory=list)

    def csv_row(self) -> dict[str, str | int | None]:
        return {
            "artist_name": self.artist_name,
            "spotify_url": self.spotify_url,
            "soundcloud_url": self.soundcloud_url,
            "soundcloud_user_id": self.soundcloud_user_id,
            "genre": " | ".join(self.genres or [self.genre]),
            "rank": self.rank,
            "monthly_listeners": self.monthly_listeners,
        }


class MusicMetricsVaultScraper:
    def __init__(self, timeout: float = 25.0) -> None:
        self.timeout = timeout
        self.session = requests.Session()

    def scrape_genre(self, target: GenreTarget) -> list[ArtistRow]:
        LOGGER.info("Fetching MusicMetricsVault genre %s limit=%s", target.url, target.limit)
        response = self.session.get(target.url, headers=HEADERS, timeout=self.timeout)
        response.raise_for_status()
        genre = target.genre or genre_from_url(target.url)
        artists = parse_artists_from_html(response.text, genre=genre)
        return artists[: target.limit]


def load_genre_targets(path: str | Path) -> list[GenreTarget]:
    targets: list[GenreTarget] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = [part.strip() for part in stripped.split(",")]
        if len(parts) < 2:
            raise ValueError(f"Expected 'url,limit' in {path}: {line!r}")
        genre = parts[2] if len(parts) >= 3 and parts[2] else None
        targets.append(GenreTarget(url=parts[0], limit=int(parts[1]), genre=genre))
    return targets


def genre_from_url(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "genres":
        return parts[1].replace("-", " ")
    return "unknown"


def parse_artists_from_html(html_text: str, genre: str) -> list[ArtistRow]:
    snapshot_artists = _artists_from_livewire_snapshot(html_text, genre)
    if snapshot_artists:
        return snapshot_artists
    return _artists_from_links(html_text, genre)


def _artists_from_livewire_snapshot(html_text: str, genre: str) -> list[ArtistRow]:
    soup = BeautifulSoup(html_text, "html.parser")
    for element in soup.find_all(attrs={"wire:snapshot": True}):
        raw_snapshot = element.get("wire:snapshot") or ""
        try:
            snapshot = json.loads(raw_snapshot)
        except json.JSONDecodeError:
            continue
        data = snapshot.get("data") or {}
        if "allArtists" not in data:
            continue
        rows = decode_livewire_artist_collection(data["allArtists"])
        artists = [_artist_row_from_payload(row, genre) for row in rows]
        return [artist for artist in artists if artist]
    return []


def decode_livewire_artist_collection(value) -> list[dict]:
    collection = value[0] if isinstance(value, list) and value else value
    rows: list[dict] = []
    if not isinstance(collection, list):
        return rows
    for item in collection:
        if isinstance(item, list) and item and isinstance(item[0], dict):
            rows.append(item[0])
        elif isinstance(item, dict):
            rows.append(item)
    return rows


def _artist_row_from_payload(payload: dict, genre: str) -> ArtistRow | None:
    name = clean_text(str(payload.get("name") or ""))
    spotify_id = clean_text(str(payload.get("spotify_id") or ""))
    if not name:
        return None
    rank = _int_or_none(payload.get("_original_rank"))
    listeners = _int_or_none(payload.get("listeners"))
    spotify_url = SPOTIFY_ARTIST_URL.format(spotify_id=spotify_id) if spotify_id else ""
    return ArtistRow(
        artist_name=name,
        spotify_url=spotify_url,
        genre=genre,
        rank=rank,
        monthly_listeners=listeners,
        spotify_id=spotify_id or None,
        genres=[genre],
    )


def _artists_from_links(html_text: str, genre: str) -> list[ArtistRow]:
    soup = BeautifulSoup(html_text, "html.parser")
    rows: list[ArtistRow] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        name = clean_text(link.get_text(" ", strip=True))
        spotify_id = spotify_id_from_mmv_artist_url(href)
        if not name or not spotify_id or spotify_id in seen:
            continue
        seen.add(spotify_id)
        rows.append(
            ArtistRow(
                artist_name=name,
                spotify_url=SPOTIFY_ARTIST_URL.format(spotify_id=spotify_id),
                genre=genre,
                rank=len(rows) + 1,
                spotify_id=spotify_id,
                genres=[genre],
            )
        )
    return rows


def spotify_id_from_mmv_artist_url(url: str) -> str | None:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) >= 3 and parts[-3] == "artists":
        candidate = parts[-1]
        if re.fullmatch(r"[A-Za-z0-9]{16,}", candidate):
            return candidate
    return None


def dedupe_artists(rows: list[ArtistRow]) -> list[ArtistRow]:
    by_key: dict[str, ArtistRow] = {}
    for row in rows:
        key = row.spotify_id or normalize_artist_name(row.artist_name)
        current = by_key.get(key)
        if current is None:
            row.genres = list(dict.fromkeys(row.genres or [row.genre]))
            by_key[key] = row
            continue
        for genre in row.genres or [row.genre]:
            if genre not in current.genres:
                current.genres.append(genre)
        if _rank_score(row.rank) < _rank_score(current.rank):
            current.rank = row.rank
            current.genre = row.genre
        if (row.monthly_listeners or 0) > (current.monthly_listeners or 0):
            current.monthly_listeners = row.monthly_listeners
        if not current.spotify_url and row.spotify_url:
            current.spotify_url = row.spotify_url
        if not current.spotify_id and row.spotify_id:
            current.spotify_id = row.spotify_id
        if not current.soundcloud_url and row.soundcloud_url:
            current.soundcloud_url = row.soundcloud_url
        if not current.soundcloud_user_id and row.soundcloud_user_id:
            current.soundcloud_user_id = row.soundcloud_user_id
    return sorted(by_key.values(), key=lambda row: (_rank_score(row.rank), row.artist_name.lower()))


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def normalize_artist_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).lower()).strip()


def _rank_score(rank: int | None) -> int:
    return rank if rank is not None else 999999


def _int_or_none(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
