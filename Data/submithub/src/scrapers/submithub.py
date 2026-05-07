from __future__ import annotations

import json
import logging
import random
import ssl
import string
import time
from dataclasses import dataclass
from datetime import date
from urllib.parse import parse_qs, quote, urlparse

import websocket

from src.extraction.normalize import clean_text
from src.models import ReleaseCandidate
from src.scrapers.base import BaseScraper

LOGGER = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; EDMReleaseExtractor/1.0; "
        "+https://example.local/release-extractor)"
    )
}

DEFAULT_GENRE = "House / Techno"
DDP_URL = "wss://www.submithub.com/sockjs/{server_id}/{session_id}/websocket"
SUBMITHUB_ROOT = "https://www.submithub.com"


@dataclass(slots=True)
class ChartSummary:
    track_id: str
    points: float
    approved: int
    rgb: int
    complete: int
    country: str | None
    tags: list[str]


class SubmitHubScraper(BaseScraper):
    source_name = "SubmitHub"

    def __init__(self, timeout: float = 30.0, limit: int = 100) -> None:
        self.timeout = timeout
        self.limit = limit

    def scrape_category(
        self,
        url: str,
        lookback_days: int | None = None,
        max_pages: int | None = None,
    ):
        """Compatibility hook; SubmitHub emits candidates directly via scrape_releases."""
        return []

    def scrape_releases(
        self,
        url: str,
        lookback_days: int | None = None,
        max_pages: int | None = None,
    ) -> list[ReleaseCandidate]:
        genre = _genre_from_url(url) or DEFAULT_GENRE
        limit = max_pages or self.limit
        LOGGER.info("Fetching SubmitHub popular chart for genre=%s limit=%s", genre, limit)
        with DDPClient(timeout=self.timeout) as ddp:
            genres = ddp.call("clientGenres")
            subgenres = _subgenres_for_parent(genres or [], genre)
            summaries = _chart_summaries(
                ddp.call("newPopular", [_popular_query(subgenres), limit]) or []
            )
            if not summaries:
                return []
            tracks = ddp.call("popularTracks", [_popular_tracks_query([summary.track_id for summary in summaries])]) or []
        return _release_candidates_from_chart(summaries, tracks, limit=limit)


class DDPClient:
    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self.ws: websocket.WebSocket | None = None
        self.next_id = 1

    def __enter__(self) -> DDPClient:
        server_id = f"{random.randint(0, 999):03d}"
        session_id = "".join(random.choice(string.ascii_lowercase) for _ in range(8))
        url = DDP_URL.format(server_id=server_id, session_id=session_id)
        self.ws = websocket.create_connection(
            url,
            timeout=self.timeout,
            header=["Origin: https://www.submithub.com", "User-Agent: Mozilla/5.0"],
            sslopt={"cert_reqs": ssl.CERT_NONE},
        )
        self._send({"msg": "connect", "version": "1", "support": ["1", "pre2", "pre1"]})
        while True:
            message = self._recv()
            if message.get("msg") == "connected":
                return self
            if message.get("msg") == "error":
                raise RuntimeError(f"SubmitHub DDP connection failed: {message}")

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.ws:
            self.ws.close()

    def call(self, method: str, params: list | None = None):
        call_id = str(self.next_id)
        self.next_id += 1
        self._send({"msg": "method", "method": method, "params": params or [], "id": call_id})
        while True:
            message = self._recv()
            if message.get("msg") == "result" and message.get("id") == call_id:
                if message.get("error"):
                    raise RuntimeError(f"SubmitHub method {method} failed: {message['error']}")
                return message.get("result")

    def _send(self, message: dict) -> None:
        if not self.ws:
            raise RuntimeError("DDP socket is not connected")
        self.ws.send(json.dumps([json.dumps(message)]))

    def _recv(self) -> dict:
        if not self.ws:
            raise RuntimeError("DDP socket is not connected")
        while True:
            raw = self.ws.recv()
            if raw in ("o", "h"):
                continue
            if raw.startswith("a"):
                payloads = json.loads(raw[1:])
                if not payloads:
                    continue
                return json.loads(payloads[0])
            return json.loads(raw)


def _genre_from_url(url: str) -> str | None:
    values = parse_qs(urlparse(url).query).get("genre")
    if not values:
        return None
    return clean_text(values[0])


def _subgenres_for_parent(genres: list[dict], parent: str) -> list[str]:
    subgenres = [genre["name"] for genre in genres if genre.get("parent") == parent and genre.get("name")]
    if not subgenres:
        LOGGER.warning("No SubmitHub subgenres found for %s; falling back to the parent genre value", parent)
        return [parent]
    return subgenres


def _popular_query(subgenres: list[str]) -> dict:
    week_ms = _rounded_now_ms() - 192 * 3600 * 1000
    return {
        "points": {"$gte": 2},
        "top_3": {"$in": subgenres},
        "hidden": {"$ne": True},
        "updated": {"$gte": {"$date": week_ms}},
        "$or": [
            {"popularWeek": {"$exists": False}},
            {"popularWeek": {"$gte": {"$date": week_ms}}},
        ],
    }


def _popular_tracks_query(track_ids: list[str]) -> dict:
    week_ms = _rounded_now_ms() - 192 * 3600 * 1000
    release_window_ms = _rounded_now_ms() - 720 * 3600 * 1000
    return {
        "_id": {"$in": track_ids},
        "released": {"$gte": {"$date": release_window_ms}},
        "$or": [
            {"popular.popularWeek": {"$exists": False}},
            {"popular.popularWeek": {"$gte": {"$date": week_ms}}},
        ],
    }


def _rounded_now_ms() -> int:
    now_ms = int(time.time() * 1000)
    hour_ms = 3600 * 1000
    return now_ms - (now_ms % hour_ms)


def _chart_summaries(rows: list[dict]) -> list[ChartSummary]:
    summaries: list[ChartSummary] = []
    for row in rows:
        track_ids = row.get("tracks") or []
        if not track_ids:
            continue
        tags = row.get("tags") or []
        tag_list = tags[0] if tags and isinstance(tags[0], list) else tags
        summaries.append(
            ChartSummary(
                track_id=track_ids[-1],
                points=float(row.get("points") or 0),
                approved=int(row.get("approved") or 0),
                rgb=int(row.get("rgb") or 0),
                complete=int(row.get("complete") or 0),
                country=row.get("country"),
                tags=[clean_text(str(tag)) for tag in tag_list if tag],
            )
        )
    return summaries


def _release_candidates_from_chart(
    summaries: list[ChartSummary],
    tracks: list[dict],
    limit: int | None = None,
) -> list[ReleaseCandidate]:
    by_track_id = {track.get("_id"): track for track in tracks}
    candidates: list[ReleaseCandidate] = []
    for rank, summary in enumerate(summaries, start=1):
        track = by_track_id.get(summary.track_id)
        if not track:
            continue
        artist = clean_text(track.get("artist") or "")
        title = _clean_track_title(track.get("title") or "")
        if not artist or not title:
            continue
        released_date = _date_from_ejson(track.get("released"))
        if released_date and date.fromisoformat(released_date) > date.today():
            continue
        source_urls = _source_urls(track)
        candidates.append(
            ReleaseCandidate(
                artist=artist,
                track_or_project_title=title,
                release_type=_release_type(track),
                confidence_score=_confidence(summary),
                extraction_method="submithub_chart",
                source_article_title=f"{artist} - {title}",
                source_article_url=_source_url(track),
                source_name="SubmitHub",
                article_date=released_date,
                embedded_music_links=source_urls,
                open_graph={
                    "chart_rank": str(rank),
                    "popular_points": _number_string(summary.points),
                    "hot_or_not_likes": str(summary.approved),
                    "curator_approvals": str(summary.approved),
                    "rgb_bonus": str(summary.rgb),
                    "approval_responses": str(summary.complete),
                    "country": summary.country or "",
                    "genres": ", ".join(summary.tags),
                    "label": clean_text(track.get("label") or ""),
                    "submitHub_track_id": summary.track_id,
                },
            )
        )
    candidates.sort(key=lambda item: float(item.open_graph.get("popular_points") or 0), reverse=True)
    if limit:
        candidates = candidates[:limit]
    return candidates


def _clean_track_title(value: str) -> str:
    return clean_text(value).strip("\"'“”‘’")


def _source_urls(track: dict) -> list[str]:
    urls = []
    for source in track.get("source") or []:
        if isinstance(source, dict) and source.get("url"):
            urls.append(str(source["url"]))
    return list(dict.fromkeys(urls))


def _source_url(track: dict) -> str:
    slug = track.get("slug")
    if slug:
        return f"{SUBMITHUB_ROOT}/song/{quote(str(slug).strip('/'))}"
    return f"{SUBMITHUB_ROOT}/popular/{track.get('_id')}"


def _release_type(track: dict) -> str:
    unoriginal = track.get("unoriginal") or []
    if isinstance(unoriginal, list) and "remix" in unoriginal:
        return "remix"
    return "track"


def _confidence(summary: ChartSummary) -> float:
    score = 0.65
    if summary.points >= 20:
        score += 0.15
    if summary.approved >= 20:
        score += 0.10
    if summary.tags:
        score += 0.05
    return min(score, 1.0)


def _date_from_ejson(value) -> str | None:
    if isinstance(value, dict) and "$date" in value:
        try:
            return date.fromtimestamp(int(value["$date"]) / 1000).isoformat()
        except (TypeError, ValueError, OSError):
            return None
    return None


def _number_string(value: float) -> str:
    return str(int(value)) if value == int(value) else f"{value:.2f}"
