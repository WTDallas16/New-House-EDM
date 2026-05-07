from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag

from weraveyou.src.extraction.normalize import clean_text
from weraveyou.src.models import ArticleCard
from weraveyou.src.scrapers.base import BaseScraper

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


class WeRaveYouScraper(BaseScraper):
    source_name = "We Rave You"

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
                if existing is None or (not existing.publish_date and card.publish_date):
                    cards_by_url[card.url] = card
                    new_cards += 1

            LOGGER.info("Discovered %d eligible article cards from %s", len(page_cards), page_url)
            if not page_cards or new_cards == 0:
                LOGGER.info("Stopping pagination because %s had no new article cards", page_url)
                break
            if reached_cutoff:
                LOGGER.info("Stopping pagination because %s reached the lookback cutoff", page_url)
                break

        cards = list(cards_by_url.values())
        LOGGER.info("Discovered %d total article cards from %s", len(cards), url)
        return cards


def _category_from_url(url: str) -> str:
    parts = [part for part in urlparse(url).path.strip("/").split("/") if part]
    if "page" in parts:
        parts = parts[: parts.index("page")]
    return parts[-1] if parts else "unknown"


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
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href"))
        absolute_url = urljoin(page_url, href)
        if not _looks_like_article_url(absolute_url):
            continue

        text = clean_text(anchor.get_text(" ", strip=True))
        if not text or text.lower() in {"read more", "home", "music", "house"}:
            continue

        title, publish_date = _split_title_and_date(text)
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


def _looks_like_article_url(url: str) -> bool:
    parsed = urlparse(url)
    if "weraveyou.com" not in parsed.netloc:
        return False
    if "/category/" in parsed.path or "/tag/" in parsed.path:
        return False
    return bool(re.search(r"/20\d{2}/\d{2}/[^/]+/?$", parsed.path))


def _split_title_and_date(text: str) -> tuple[str, str | None]:
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
