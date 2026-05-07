from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.extraction.normalize import clean_text
from src.extraction.parser import BODY_PATTERNS
from src.models import ArticleEnrichment
from src.scrapers.tracklists1001 import HEADERS

LOGGER = logging.getLogger(__name__)

MUSIC_DOMAINS = (
    "open.spotify.com",
    "spotify.link",
    "soundcloud.com",
    "music.apple.com",
    "itunes.apple.com",
    "youtube.com",
    "youtu.be",
    "beatport.com",
)


class ArticleEnricher:
    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    def enrich(self, url: str) -> ArticleEnrichment:
        LOGGER.info("Enriching article %s", url)
        try:
            response = requests.get(url, headers=HEADERS, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            LOGGER.warning("Unable to enrich %s: %s", url, exc)
            return ArticleEnrichment(url=url)

        soup = BeautifulSoup(response.text, "html.parser")
        open_graph = extract_open_graph(soup)
        body_text = extract_body_text(soup)
        embedded_music_links = extract_music_links(soup, url)
        json_ld = extract_json_ld(soup)
        body_release_matches = extract_body_release_matches(body_text)
        return ArticleEnrichment(
            url=url,
            body_text=body_text,
            embedded_music_links=embedded_music_links,
            open_graph=open_graph,
            json_ld=json_ld,
            body_release_matches=body_release_matches,
        )


def extract_open_graph(soup: BeautifulSoup) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        key = tag.get("property") or tag.get("name")
        value = tag.get("content")
        if not key or not value:
            continue
        key_text = str(key)
        if key_text.startswith(("og:", "twitter:")):
            metadata[key_text] = clean_text(str(value))
    return metadata


def extract_json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            LOGGER.debug("Skipping malformed JSON-LD block")
            continue
        if isinstance(parsed, dict):
            payloads.append(parsed)
        elif isinstance(parsed, list):
            payloads.extend(item for item in parsed if isinstance(item, dict))
    return payloads


def extract_body_text(soup: BeautifulSoup) -> str:
    for unwanted in soup(["script", "style", "noscript", "iframe"]):
        unwanted.decompose()
    article = soup.find("article") or soup.find("main") or soup.body
    if not article:
        return ""
    return clean_text(article.get_text(" ", strip=True))


def extract_music_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    links: list[str] = []
    container = soup.find("article") or soup.find("main") or soup
    for tag in container.find_all(["a", "iframe", "embed"], href=True):
        href = str(tag.get("href"))
        absolute = urljoin(base_url, href)
        if _is_music_link(absolute):
            links.append(absolute)
    for tag in container.find_all(["iframe", "embed"], src=True):
        src = str(tag.get("src"))
        absolute = urljoin(base_url, src)
        if _is_music_link(absolute):
            links.append(absolute)
    return list(dict.fromkeys(links))


def _is_music_link(url: str) -> bool:
    lowered = url.lower()
    if not any(domain in lowered for domain in MUSIC_DOMAINS):
        return False
    parsed = urlparse(lowered)
    path = parsed.path.strip("/")
    path_parts = [part for part in path.split("/") if part]
    if parsed.netloc == "open.spotify.com" and path.startswith("user/"):
        return False
    if parsed.netloc == "open.spotify.com" and path.startswith("artist/"):
        return False
    if parsed.netloc.endswith("youtube.com") and path.startswith(("user/", "channel/", "c/")):
        return False
    if parsed.netloc.endswith("soundcloud.com") and path in {"weraveyou", "we-rave-you", "edmtunes"}:
        return False
    if parsed.netloc.endswith("soundcloud.com") and len(path_parts) == 1:
        return False
    return True


def extract_body_release_matches(body_text: str) -> list[str]:
    matches: list[str] = []
    for pattern in BODY_PATTERNS:
        for match in re.finditer(pattern, body_text, re.IGNORECASE):
            matches.append(clean_text(match.group(0)))
    return matches[:10]
