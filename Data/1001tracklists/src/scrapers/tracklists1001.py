from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from src.extraction.normalize import clean_text
from src.models import ReleaseCandidate
from src.scrapers.base import BaseScraper

LOGGER = logging.getLogger(__name__)

SOURCE_NAME = "1001Tracklists"
ROOT_URL = "https://www.1001tracklists.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}

CHARTS = (
    {
        "name_template": "Top {genre} Newcomer Tracks",
        "param": "nc",
        "window": "first played in the last 21-30 days",
        "metric": "unique_dj_plays",
        "confidence": 0.92,
    },
    {
        "name_template": "Most Heard {genre} Tracks",
        "param": "mh",
        "window": "track-player opens in the last 7 days",
        "metric": "listener_track_player_opens",
        "confidence": 0.84,
    },
)

FALLBACK_CHARTS = (
    {
        "name": "Daily Newcomer Tracks",
        "url_template": "https://www.1001tracklists.com/charts/daily/{year}/{month}/{day}/newcomer.html",
        "window": "daily newcomer chart",
        "metric": "daily_newcomer_rank",
        "confidence": 0.82,
    },
    {
        "name": "Most Heard Tracks",
        "url_template": "https://www.1001tracklists.com/charts/mostheard/index.html",
        "window": "recent track-player opens",
        "metric": "most_heard_rank",
        "confidence": 0.80,
    },
    {
        "name": "Weekly DJ Support Tracks",
        "url_template": "https://www.1001tracklists.com/charts/weekly/index.html",
        "window": "unique DJ support in the last 4 weeks",
        "metric": "unique_dj_support_rank",
        "confidence": 0.78,
    },
)

SECTION_STOP_PREFIXES = (
    "This chart",
    "Most Watched",
    "Last IDed",
    "Genres",
    "Hot Shows",
    "Hot Events",
    "Most Viewed",
    "Most Liked",
)


@dataclass(slots=True)
class TextToken:
    text: str
    href: str | None = None


@dataclass(slots=True)
class ChartTrack:
    rank: int
    artist: str
    title: str
    label: str | None
    track_url: str | None
    label_url: str | None
    chart_name: str
    chart_window: str
    chart_metric: str
    confidence: float


class Tracklists1001AccessError(RuntimeError):
    """Raised when 1001Tracklists returns a human-validation page."""


class Tracklists1001Scraper(BaseScraper):
    source_name = SOURCE_NAME

    def __init__(
        self,
        timeout: float = 20.0,
        default_max_pages: int = 3,
        cookie_header: str | None = None,
        html_input: str | Path | None = None,
        chart_fallback: bool = True,
    ) -> None:
        self.timeout = timeout
        self.default_max_pages = default_max_pages
        self.cookie_header = cookie_header or os.environ.get("TRACKLISTS1001_COOKIE")
        self.html_input = Path(html_input) if html_input else None
        self.chart_fallback = chart_fallback

    def scrape_category(
        self,
        url: str,
        lookback_days: int | None = None,
        max_pages: int | None = None,
    ):
        """Compatibility hook; 1001Tracklists emits candidates directly via scrape_releases."""
        return []

    def scrape_releases(
        self,
        url: str,
        lookback_days: int | None = None,
        max_pages: int | None = None,
    ) -> list[ReleaseCandidate]:
        page_limit = max_pages or self.default_max_pages
        genre = _genre_from_url(url)
        LOGGER.info("Fetching 1001Tracklists sidebar charts for genre=%s max_pages=%s", genre, page_limit)
        session = requests.Session()
        try:
            html = self._read_html_input() if self.html_input else self._fetch(url, session=session)
            tracks = _extract_sidebar_chart_tracks(html, base_url=url, genre=genre)
            if not self.html_input:
                tracks.extend(self._fetch_show_more_tracks(html, url, genre, session, page_limit))
        except Tracklists1001AccessError:
            if self.html_input or not self.chart_fallback:
                raise
            LOGGER.warning("Genre page was challenged; falling back to unblocked 1001Tracklists chart pages")
            tracks = self._fetch_fallback_chart_tracks(session=session, max_pages=page_limit)
        if not tracks:
            LOGGER.warning("No 1001Tracklists sidebar chart tracks found at %s", url)
        candidates = [_candidate_from_track(track) for track in tracks]
        return candidates

    def _read_html_input(self) -> str:
        if not self.html_input:
            raise RuntimeError("No HTML input path configured")
        try:
            html = self.html_input.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Unable to read HTML input file {self.html_input}: {exc}") from exc
        if _looks_like_turnstile_challenge(html):
            raise Tracklists1001AccessError(
                f"{self.html_input} contains the 1001Tracklists Turnstile/forwarding page, not the chart page."
            )
        return html

    def _fetch(self, url: str, session: requests.Session | None = None) -> str:
        client = session or requests.Session()
        headers = _request_headers(self.cookie_header)
        try:
            response = client.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Unable to fetch 1001Tracklists page {url}: {exc}") from exc
        if _looks_like_turnstile_challenge(response.text):
            raise Tracklists1001AccessError(
                "1001Tracklists returned a Turnstile/forwarding challenge instead of the genre page. "
                "Open the page in your browser, complete the check, then either export your Cookie header "
                "as TRACKLISTS1001_COOKIE or save the page HTML and pass --html-input."
            )
        return response.text

    def _fetch_show_more_tracks(
        self,
        html: str,
        base_url: str,
        genre: str,
        session: requests.Session,
        max_pages: int,
    ) -> list[ChartTrack]:
        if max_pages <= 1:
            return []

        tracks: list[ChartTrack] = []
        for chart in CHARTS:
            chart_name = chart["name_template"].format(genre=genre)
            params = _statistic_updater_params_for_chart(html, chart_name)
            if not params:
                LOGGER.debug("No show-more params found for %s", chart_name)
                continue
            for page in range(2, max_pages + 1):
                params["page"] = str(page)
                try:
                    response = session.get(
                        urljoin(base_url, "/ajax/get_tracks.php"),
                        params=params,
                        headers=_request_headers(self.cookie_header)
                        | {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
                        timeout=self.timeout,
                    )
                    response.raise_for_status()
                    payload = response.json()
                except (requests.RequestException, ValueError) as exc:
                    LOGGER.warning("Unable to fetch 1001Tracklists show-more page %s for %s: %s", page, chart_name, exc)
                    break
                if not payload.get("success") or not payload.get("data"):
                    break
                fragment = f"<h2>{chart_name}</h2>{''.join(payload['data'])}<p>This chart</p>"
                tracks.extend(_extract_sidebar_chart_tracks(fragment, base_url=base_url, genre=genre))
        return tracks

    def _fetch_fallback_chart_tracks(self, session: requests.Session, max_pages: int) -> list[ChartTrack]:
        current_day = date.today()
        tracks: list[ChartTrack] = []
        for chart in FALLBACK_CHARTS[: max(max_pages, 1)]:
            url = chart["url_template"].format(
                year=current_day.strftime("%Y"),
                month=current_day.strftime("%m"),
                day=current_day.strftime("%d"),
            )
            try:
                html = self._fetch(url, session=session)
            except RuntimeError as exc:
                LOGGER.warning("Unable to fetch fallback chart %s: %s", url, exc)
                continue
            tracks.extend(
                _extract_chart_page_tracks(
                    html,
                    base_url=url,
                    chart_name=str(chart["name"]),
                    chart_window=str(chart["window"]),
                    chart_metric=str(chart["metric"]),
                    confidence=float(chart["confidence"]),
                )
            )
        return tracks


def _genre_from_url(url: str) -> str:
    match = re.search(r"/genre/([^/]+)/", url)
    if not match:
        return "House"
    return clean_text(match.group(1).replace("-", " ").title())


def _looks_like_turnstile_challenge(html: str) -> bool:
    lowered = html.lower()
    return (
        "challenges.cloudflare.com/turnstile" in lowered
        or "please wait, you will be forwarded" in lowered
        or "name=\"captcha\"" in lowered
    )


def _request_headers(cookie_header: str | None = None) -> dict[str, str]:
    headers = dict(HEADERS)
    if cookie_header:
        headers["Cookie"] = cookie_header.strip()
    return headers


def _extract_sidebar_chart_tracks(html: str, base_url: str, genre: str = "House") -> list[ChartTrack]:
    soup = BeautifulSoup(html, "html.parser")
    tokens = _document_tokens(soup)
    tracks: list[ChartTrack] = []
    for chart in CHARTS:
        chart_name = chart["name_template"].format(genre=genre)
        tracks.extend(
            _parse_chart_tokens(
                tokens=tokens,
                chart_name=chart_name,
                chart_window=chart["window"],
                chart_metric=chart["metric"],
                confidence=float(chart["confidence"]),
                base_url=base_url,
            )
        )
    return tracks


def _extract_chart_page_tracks(
    html: str,
    base_url: str,
    chart_name: str,
    chart_window: str,
    chart_metric: str,
    confidence: float,
) -> list[ChartTrack]:
    soup = BeautifulSoup(html, "html.parser")
    tracks: list[ChartTrack] = []
    for row in soup.select("div.bItm.oItm"):
        rank_text = clean_text(row.select_one(".bRank").get_text(" ", strip=True) if row.select_one(".bRank") else "")
        if not rank_text.isdigit():
            continue
        track_link = row.select_one('a[href*="/track/"]')
        if not track_link:
            continue
        parsed = _parse_artist_and_title(track_link.get_text(" ", strip=True))
        if not parsed:
            continue
        label_link = row.select_one(".trackLabel a[href]")
        metric_value = _chart_row_metric_value(row)
        artist, title = parsed
        tracks.append(
            ChartTrack(
                rank=int(rank_text),
                artist=artist,
                title=title,
                label=clean_text(label_link.get_text(" ", strip=True)) if label_link else None,
                track_url=urljoin(base_url, str(track_link.get("href") or "")),
                label_url=urljoin(base_url, str(label_link.get("href") or "")) if label_link else None,
                chart_name=chart_name,
                chart_window=chart_window,
                chart_metric=f"{chart_metric}:{metric_value}" if metric_value else chart_metric,
                confidence=confidence,
            )
        )
    return tracks


def _chart_row_metric_value(row: Tag) -> str:
    badge = row.select_one(".playC span")
    if badge:
        return clean_text(badge.get_text(" ", strip=True))
    save_badge = row.select_one(".badgeSpotify span")
    if save_badge:
        return clean_text(save_badge.get_text(" ", strip=True))
    return ""


def _document_tokens(soup: BeautifulSoup) -> list[TextToken]:
    root = soup.body or soup
    tokens: list[TextToken] = []
    for node in root.descendants:
        if not isinstance(node, NavigableString):
            continue
        parent = node.parent
        if not isinstance(parent, Tag) or parent.name in {"script", "style", "noscript"}:
            continue
        text = clean_text(str(node))
        if not text:
            continue
        anchor = parent if parent.name == "a" else parent.find_parent("a")
        href = str(anchor.get("href")) if isinstance(anchor, Tag) and anchor.get("href") else None
        tokens.append(TextToken(text=text, href=href))
    return _dedupe_adjacent_tokens(tokens)


def _dedupe_adjacent_tokens(tokens: list[TextToken]) -> list[TextToken]:
    cleaned: list[TextToken] = []
    for token in tokens:
        if cleaned and cleaned[-1].text == token.text and cleaned[-1].href == token.href:
            continue
        cleaned.append(token)
    return cleaned


def _parse_chart_tokens(
    tokens: list[TextToken],
    chart_name: str,
    chart_window: str,
    chart_metric: str,
    confidence: float,
    base_url: str,
) -> list[ChartTrack]:
    start = _find_token(tokens, chart_name)
    if start is None:
        return []

    tracks: list[ChartTrack] = []
    index = start + 1
    while index < len(tokens):
        token = tokens[index]
        if _is_chart_stop(token.text, chart_name):
            break
        if token.text == "Show More":
            index += 1
            continue
        if not token.text.isdigit():
            index += 1
            continue

        rank = int(token.text)
        track_token_index = _next_track_token_index(tokens, index + 1, chart_name)
        if track_token_index is None:
            index += 1
            continue

        track_token = tokens[track_token_index]
        parsed = _parse_artist_and_title(track_token.text)
        if not parsed:
            index = track_token_index + 1
            continue
        artist, title = parsed

        label_token = _next_label_token(tokens, track_token_index + 1, chart_name)
        tracks.append(
            ChartTrack(
                rank=rank,
                artist=artist,
                title=title,
                label=label_token.text if label_token else None,
                track_url=urljoin(base_url, track_token.href) if track_token.href else None,
                label_url=urljoin(base_url, label_token.href) if label_token and label_token.href else None,
                chart_name=chart_name,
                chart_window=chart_window,
                chart_metric=chart_metric,
                confidence=confidence,
            )
        )
        index = track_token_index + 1
    return tracks


def _find_token(tokens: list[TextToken], text: str) -> int | None:
    expected = clean_text(text).lower()
    for index, token in enumerate(tokens):
        if token.text.lower() == expected:
            return index
    return None


def _next_track_token_index(tokens: list[TextToken], start: int, chart_name: str) -> int | None:
    for index in range(start, min(start + 8, len(tokens))):
        text = tokens[index].text
        if _is_chart_stop(text, chart_name) or text.isdigit():
            return None
        if _parse_artist_and_title(text):
            return index
    return None


def _next_label_token(tokens: list[TextToken], start: int, chart_name: str) -> TextToken | None:
    if start >= len(tokens):
        return None
    token = tokens[start]
    if token.text.isdigit() or token.text == "Show More" or _is_chart_stop(token.text, chart_name):
        return None
    if _parse_artist_and_title(token.text):
        return None
    return token


def _is_chart_stop(text: str, current_chart_name: str) -> bool:
    if text == current_chart_name:
        return False
    if text.startswith(SECTION_STOP_PREFIXES):
        return True
    return any(text == chart["name_template"].format(genre="House") for chart in CHARTS)


def _parse_artist_and_title(value: str) -> tuple[str, str] | None:
    text = clean_text(value)
    if " - " not in text:
        return None
    artist, title = text.split(" - ", 1)
    artist = clean_text(artist)
    title = clean_text(title)
    if not artist or not title:
        return None
    return artist, title


def _candidate_from_track(track: ChartTrack) -> ReleaseCandidate:
    return ReleaseCandidate(
        artist=track.artist,
        track_or_project_title=track.title,
        release_type=_release_type(track.title),
        confidence_score=track.confidence,
        extraction_method="1001tracklists_sidebar_chart",
        source_article_title=f"{track.artist} - {track.title}",
        source_article_url=track.track_url or ROOT_URL,
        source_name=SOURCE_NAME,
        article_date=None,
        embedded_music_links=[],
        open_graph={
            "chart_name": track.chart_name,
            "chart_rank": str(track.rank),
            "chart_window": track.chart_window,
            "chart_metric": track.chart_metric,
            "label": track.label or "",
            "label_url": track.label_url or "",
        },
    )


def _release_type(title: str) -> str:
    lowered = title.lower()
    if "remix" in lowered:
        return "remix"
    if "rework" in lowered:
        return "rework"
    return "track"


def _statistic_updater_params_for_chart(html: str, chart_name: str) -> dict[str, str]:
    start = html.find(chart_name)
    if start == -1:
        return {}
    section = html[start : start + 6000]
    match = re.search(r"StatisticUpdater\s*\([^,]+,\s*(\{.*?\})\s*\)", section, re.DOTALL)
    if not match:
        return {}
    params = _parse_js_object(match.group(1))
    if "mode" not in params:
        params["mode"] = "9"
    if "params" not in params:
        for chart in CHARTS:
            if chart_name == chart["name_template"].format(genre="House"):
                params["params"] = str(chart["param"])
                break
    return params


def _parse_js_object(raw: str) -> dict[str, str]:
    params: dict[str, str] = {}
    source = unescape(raw)
    for key, single_quoted, double_quoted, bare_value in re.findall(
        r"([A-Za-z_][\w-]*)\s*:\s*(?:'([^']*)'|\"([^\"]*)\"|([^,{}]+))",
        source,
    ):
        value = single_quoted or double_quoted or bare_value
        params[key] = clean_text(value)
    return params
