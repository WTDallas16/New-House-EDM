from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse, urlunparse

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


class EDMTunesScraper(BaseScraper):
    source_name = "EDMTunes"

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
        rss_cards = self._scrape_feed(_feed_url(url), cutoff)
        cards_by_url: dict[str, ArticleCard] = {card.url: card for card in rss_cards}
        category = _category_from_url(url)
        pages_to_fetch = max_pages if max_pages is not None else self.max_pages

        for page_number in range(1, pages_to_fetch + 1):
            page_url = _paginated_url(url, page_number)
            LOGGER.info("Fetching category page %s", page_url)
            try:
                response = requests.get(page_url, headers=HEADERS, timeout=self.timeout)
                response.raise_for_status()
            except requests.RequestException as exc:
                LOGGER.warning("Stopping pagination at %s: %s", page_url, exc)
                break

            soup = BeautifulSoup(response.text, "html.parser")
            page_cards, reached_cutoff = _extract_cards_from_page(
                soup=soup,
                page_url=page_url,
                category=category,
                source_name=self.source_name,
                cutoff=cutoff,
            )
            new_cards = 0
            for card in page_cards:
                existing = cards_by_url.get(card.url)
                if existing:
                    card = _merge_cards(existing, card)
                if existing is None or (not existing.publish_date and card.publish_date):
                    cards_by_url[card.url] = card
                    new_cards += 1
                elif existing:
                    cards_by_url[card.url] = card

            LOGGER.info("Discovered %d eligible article cards from %s", len(page_cards), page_url)
            if not page_cards:
                LOGGER.info("Stopping pagination because %s had no new article cards", page_url)
                break
            if reached_cutoff:
                LOGGER.info("Stopping pagination because %s reached the lookback cutoff", page_url)
                break

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


def _category_from_url(url: str) -> str:
    parts = [part for part in urlparse(url).path.strip("/").split("/") if part]
    if "page" in parts:
        parts = parts[: parts.index("page")]
    if "feed" in parts:
        parts = parts[: parts.index("feed")]
    return parts[-1] if parts else "music"


def _feed_url(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if "page" in parts:
        parts = parts[: parts.index("page")]
    if parts and parts[-1] == "feed":
        path = "/" + "/".join(parts) + "/"
    else:
        path = "/" + "/".join(parts + ["feed"]) + "/"
    return urlunparse(parsed._replace(path=path))


def _paginated_url(url: str, page_number: int) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if "page" in parts:
        parts = parts[: parts.index("page")]
    if page_number > 1:
        parts.extend(["page", str(page_number)])
    path = "/" + "/".join(parts) + "/"
    return urlunparse(parsed._replace(path=path))


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
        href = str(anchor.get("href"))
        absolute_url = urljoin(page_url, href)
        if not _looks_like_article_url(absolute_url):
            continue
        absolute_url = _canonical_url(absolute_url)

        text = clean_text(anchor.get_text(" ", strip=True))
        if not text or text.lower() in {"read more", "home", "music"}:
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

        card = ArticleCard(
            title=title,
            url=absolute_url,
            source_name=source_name,
            category=category,
            publish_date=publish_date,
            snippet=_nearby_snippet(anchor),
        )
        existing = cards_by_url.get(absolute_url)
        if existing is None or (not existing.publish_date and card.publish_date):
            cards_by_url[absolute_url] = card

    return list(cards_by_url.values()), reached_cutoff


def _extract_cards_from_feed(feed_xml: str, cutoff: date | None) -> list[ArticleCard]:
    try:
        root = ET.fromstring(feed_xml)
    except ET.ParseError as exc:
        LOGGER.warning("Unable to parse EDMTunes RSS feed: %s", exc)
        return []

    cards: list[ArticleCard] = []
    for item in root.findall(".//item"):
        title = clean_text(_child_text(item, "title"))
        url = _canonical_url(clean_text(_child_text(item, "link")))
        if not title or not url:
            continue
        published = _to_iso_date(_child_text(item, "pubDate"))
        if cutoff and published:
            parsed_date = _parse_date(published)
            if parsed_date and parsed_date < cutoff:
                continue
        categories = [clean_text(category.text or "") for category in item.findall("category")]
        categories = [category for category in categories if category]
        snippet = _html_to_text(_child_text(item, "description"))
        cards.append(
            ArticleCard(
                title=title,
                url=url,
                source_name="EDMTunes",
                category=", ".join(categories) if categories else "music",
                publish_date=published,
                snippet=snippet,
            )
        )
    return cards


def _child_text(item: ET.Element, name: str) -> str:
    child = item.find(name)
    return child.text if child is not None and child.text else ""


def _looks_like_article_url(url: str) -> bool:
    parsed = urlparse(url)
    if "edmtunes.com" not in parsed.netloc:
        return False
    if parsed.path.rstrip("/") in {"", "/music"}:
        return False
    if "/page/" in parsed.path or "/tag/" in parsed.path or "/category/" in parsed.path:
        return False
    return bool(re.search(r"/20\d{2}/\d{2}/[^/]+/?$", parsed.path))


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(query="", fragment=""))


def _split_title_and_date(text: str) -> tuple[str, str | None]:
    text = html.unescape(text)
    text = re.sub(r"^Latest news\s+", "", text, flags=re.IGNORECASE)
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


def _merge_cards(preferred: ArticleCard, fallback: ArticleCard) -> ArticleCard:
    return ArticleCard(
        title=preferred.title or fallback.title,
        url=preferred.url or fallback.url,
        source_name=preferred.source_name or fallback.source_name,
        category=preferred.category or fallback.category,
        publish_date=preferred.publish_date or fallback.publish_date,
        snippet=preferred.snippet or fallback.snippet,
    )
