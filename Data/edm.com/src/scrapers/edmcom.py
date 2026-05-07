from __future__ import annotations

import html
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag

from src.extraction.normalize import clean_text
from src.models import ArticleCard
from src.scrapers.base import BaseScraper

LOGGER = logging.getLogger(__name__)

DATE_RE = re.compile(
    r"\b(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(?P<day>\d{1,2}),\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; EDMReleaseExtractor/1.0; "
        "+https://example.local/release-extractor)"
    )
}


class EDMComScraper(BaseScraper):
    source_name = "EDM.com"

    def __init__(self, timeout: float = 20.0, max_pages: int = 10) -> None:
        self.timeout = timeout
        self.max_pages = max_pages

    def scrape_category(
        self,
        url: str,
        lookback_days: int | None = None,
        max_pages: int | None = None,
    ) -> list[ArticleCard]:
        cutoff = date.today() - timedelta(days=lookback_days) if lookback_days else None
        cards_by_url: dict[str, ArticleCard] = {}
        category = _category_from_url(url)
        max_batches = max_pages if max_pages is not None else self.max_pages

        self._add_cards(cards_by_url, self._scrape_feed(_feed_url(url), cutoff))

        LOGGER.info("Fetching EDM.com archive page %s", url)
        try:
            response = requests.get(url, headers=HEADERS, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            LOGGER.warning("Unable to fetch EDM.com archive page %s: %s", url, exc)
            cards = list(cards_by_url.values())
            LOGGER.info("Discovered %d total article cards from %s", len(cards), url)
            return cards

        soup = BeautifulSoup(response.text, "html.parser")
        page_cards, reached_cutoff = _extract_cards_from_page(soup, url, category, self.source_name, cutoff)
        self._add_cards(cards_by_url, page_cards)
        LOGGER.info("Discovered %d eligible article cards from %s", len(page_cards), url)

        next_url = _find_load_more_url(soup, url, batch_number=2)
        seen_urls: set[str] = set()
        for batch_number in range(2, max_batches + 1):
            if reached_cutoff or not next_url or next_url in seen_urls:
                break
            seen_urls.add(next_url)
            LOGGER.info("Fetching EDM.com load-more batch %s: %s", batch_number, next_url)
            try:
                batch_response = requests.get(next_url, headers=HEADERS, timeout=self.timeout)
                batch_response.raise_for_status()
            except requests.RequestException as exc:
                LOGGER.warning("Stopping load-more batches at %s: %s", next_url, exc)
                break
            batch_soup = _soup_from_load_more_response(batch_response.text)
            batch_cards, reached_cutoff = _extract_cards_from_page(
                batch_soup,
                url,
                category,
                self.source_name,
                cutoff,
            )
            self._add_cards(cards_by_url, batch_cards)
            LOGGER.info("Discovered %d eligible article cards from load-more batch %s", len(batch_cards), batch_number)
            next_url = _find_load_more_url(batch_soup, url, batch_number=batch_number + 1)

        cards = list(cards_by_url.values())
        LOGGER.info("Discovered %d total article cards from %s", len(cards), url)
        return cards

    def _scrape_feed(self, feed_url: str, cutoff: date | None) -> list[ArticleCard]:
        LOGGER.info("Fetching RSS feed %s", feed_url)
        try:
            response = requests.get(feed_url, headers=HEADERS, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            LOGGER.warning("Unable to fetch RSS feed %s: %s", feed_url, exc)
            return []
        return _extract_cards_from_feed(response.text, cutoff)

    @staticmethod
    def _add_cards(cards_by_url: dict[str, ArticleCard], cards: list[ArticleCard]) -> None:
        for card in cards:
            existing = cards_by_url.get(card.url)
            cards_by_url[card.url] = _merge_cards(existing, card) if existing else card


def _category_from_url(url: str) -> str:
    parts = [part for part in urlparse(url).path.strip("/").split("/") if part]
    return parts[-1] if parts else "music-releases"


def _feed_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path="/.rss/full/", query="", fragment=""))


def _find_load_more_url(soup: BeautifulSoup, page_url: str, batch_number: int) -> str | None:
    for element in soup.find_all(["a", "button"]):
        label = clean_text(element.get_text(" ", strip=True)).lower()
        if "load more" not in label:
            continue
        for attr in ("href", "data-href", "data-url", "data-endpoint", "data-next", "data-next-url"):
            value = element.get(attr)
            if value:
                return urljoin(page_url, str(value))

    alm = soup.find(class_=re.compile(r"\bajax-load-more-wrap\b|\balm-listing\b"))
    if alm:
        query = {
            key.replace("data-", "").replace("-", "_"): value
            for key, value in alm.attrs.items()
            if key.startswith("data-") and isinstance(value, str)
        }
        query.setdefault("page", str(batch_number))
        query.setdefault("category", "music-releases")
        return urljoin(page_url, "/wp-json/ajaxloadmore/posts?" + urlencode(query))
    return None


def _soup_from_load_more_response(response_text: str) -> BeautifulSoup:
    response_text = response_text.strip()
    if response_text.startswith("{"):
        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError:
            payload = {}
        for key in ("html", "data", "posts", "content"):
            value = payload.get(key)
            if isinstance(value, str):
                return BeautifulSoup(value, "html.parser")
            if isinstance(value, list):
                fragments = []
                for item in value:
                    if isinstance(item, dict):
                        fragments.append(str(item.get("html") or item.get("content") or item.get("title", "")))
                    else:
                        fragments.append(str(item))
                return BeautifulSoup("\n".join(fragments), "html.parser")
    return BeautifulSoup(response_text, "html.parser")


def _extract_cards_from_page(
    soup: BeautifulSoup,
    page_url: str,
    category: str,
    source_name: str,
    cutoff: date | None,
) -> tuple[list[ArticleCard], bool]:
    cards_by_url: dict[str, ArticleCard] = {}
    reached_cutoff = False
    for anchor in soup.select("h1 a[href], h2 a[href], h3 a[href], article a[href]"):
        absolute_url = _canonical_url(urljoin(page_url, str(anchor.get("href"))))
        if not _looks_like_article_url(absolute_url):
            continue

        text = clean_text(anchor.get_text(" ", strip=True))
        if not text or text.lower() in {"read more", "home", "music releases"}:
            continue

        parent = anchor.find_parent(["article", "div", "li", "section"])
        title, publish_date = _split_title_and_date(text)
        if not publish_date and parent:
            publish_date = _date_from_text(parent.get_text(" ", strip=True))
        if not title or len(title) < 12:
            continue

        if cutoff and publish_date:
            parsed_date = _parse_date(publish_date)
            if parsed_date and parsed_date < cutoff:
                reached_cutoff = True
                continue

        cards_by_url[absolute_url] = ArticleCard(
            title=title,
            url=absolute_url,
            source_name=source_name,
            category=category,
            publish_date=publish_date,
            snippet=_nearby_snippet(anchor),
        )

    return list(cards_by_url.values()), reached_cutoff


def _extract_cards_from_feed(feed_xml: str, cutoff: date | None) -> list[ArticleCard]:
    try:
        root = ET.fromstring(feed_xml)
    except ET.ParseError as exc:
        LOGGER.warning("Unable to parse EDM.com RSS feed: %s", exc)
        return []

    cards: list[ArticleCard] = []
    for item in root.findall(".//item"):
        title = clean_text(_child_text(item, "title"))
        url = _canonical_url(clean_text(_child_text(item, "link")))
        if not title or not url or not _looks_like_article_url(url):
            continue
        published = _to_iso_date(_child_text(item, "pubDate"))
        if cutoff and published:
            parsed_date = _parse_date(published)
            if parsed_date and parsed_date < cutoff:
                continue
        categories = [clean_text(category.text or "") for category in item.findall("category")]
        categories = [category for category in categories if category]
        cards.append(
            ArticleCard(
                title=title,
                url=url,
                source_name="EDM.com",
                category=", ".join(categories) if categories else "music-releases",
                publish_date=published,
                snippet=_html_to_text(_child_text(item, "description")),
            )
        )
    return cards


def _child_text(item: ET.Element, name: str) -> str:
    child = item.find(name)
    return child.text if child is not None and child.text else ""


def _looks_like_article_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc not in {"edm.com", "www.edm.com"}:
        return False
    if not parsed.path.startswith("/music-releases/"):
        return False
    return parsed.path.rstrip("/") != "/music-releases"


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(netloc="edm.com", query="", fragment=""))


def _split_title_and_date(text: str) -> tuple[str, str | None]:
    text = html.unescape(text)
    text = re.sub(r"\s+Read more\s*$", "", text, flags=re.IGNORECASE)
    match = DATE_RE.search(text)
    if not match:
        return clean_text(text), None
    date_text = match.group(0)
    title = clean_text((text[: match.start()] + " " + text[match.end() :]).strip())
    return title, _to_iso_date(date_text)


def _to_iso_date(date_text: str) -> str | None:
    parsed = _parse_date(date_text)
    return parsed.isoformat() if parsed else None


def _parse_date(date_text: str) -> date | None:
    try:
        return date.fromisoformat(date_text)
    except ValueError:
        pass
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(date_text, fmt).date()
        except ValueError:
            continue
    try:
        return parsedate_to_datetime(date_text).date()
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _date_from_text(text: str) -> str | None:
    match = DATE_RE.search(text)
    if not match:
        return None
    return _to_iso_date(match.group(0))


def _html_to_text(value: str) -> str | None:
    if not value:
        return None
    soup = BeautifulSoup(html.unescape(value), "html.parser")
    text = clean_text(soup.get_text(" ", strip=True))
    return text[:500] if text else None


def _nearby_snippet(anchor: Tag) -> str | None:
    parent = anchor.find_parent(["article", "li", "div", "section"])
    if not parent:
        return None
    text = clean_text(parent.get_text(" ", strip=True))
    title_text = clean_text(anchor.get_text(" ", strip=True))
    text = text.replace(title_text, " ")
    text = re.sub(DATE_RE, " ", text)
    text = clean_text(text)
    return text[:300] if text and text.lower() != "read more" else None


def _merge_cards(preferred: ArticleCard | None, fallback: ArticleCard) -> ArticleCard:
    if preferred is None:
        return fallback
    return ArticleCard(
        title=preferred.title or fallback.title,
        url=preferred.url or fallback.url,
        source_name=preferred.source_name or fallback.source_name,
        category=preferred.category or fallback.category,
        publish_date=preferred.publish_date or fallback.publish_date,
        snippet=preferred.snippet or fallback.snippet,
    )
