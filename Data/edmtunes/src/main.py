from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

from src.enrich.article_enricher import ArticleEnricher
from src.extraction.classifier import classify_article
from src.extraction.normalize import dedupe_releases
from src.extraction.parser import parse_release_candidate
from src.models import ReleaseCandidate
from src.scrapers.base import BaseScraper
from src.scrapers.edmtunes import EDMTunesScraper

LOGGER = logging.getLogger(__name__)

SCRAPERS: dict[str, type[BaseScraper]] = {
    "edmtunes": EDMTunesScraper,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract new EDM/house release candidates from music blogs.")
    parser.add_argument("--source", choices=sorted(SCRAPERS), required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--lookback-days", type=int, default=14)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--output", default="data/extracted_releases.json")
    parser.add_argument("--csv-output", default=None)
    parser.add_argument("--skip-enrichment", action="store_true")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def extract_releases(
    source: str,
    url: str,
    lookback_days: int | None = 14,
    enrich_articles: bool = True,
    max_pages: int | None = 10,
) -> list[ReleaseCandidate]:
    scraper_cls = SCRAPERS[source]
    scraper = scraper_cls()
    enricher = ArticleEnricher()
    candidates: list[ReleaseCandidate] = []

    for article in scraper.scrape_category(url, lookback_days=lookback_days, max_pages=max_pages):
        classification = classify_article(article.title, article.snippet)
        LOGGER.debug("Article %r release=%s", article.title, classification.release_article)
        if not classification.release_article:
            continue
        enrichment = enricher.enrich(article.url) if enrich_articles else None
        candidate = parse_release_candidate(article, enrichment)
        if candidate:
            candidates.append(candidate)

    return dedupe_releases(candidates)


def write_json(candidates: list[ReleaseCandidate], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump([candidate.as_dict() for candidate in candidates], handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def write_csv(candidates: list[ReleaseCandidate], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "artist",
        "track_or_project_title",
        "release_type",
        "confidence_score",
        "extraction_method",
        "source_article_title",
        "source_article_url",
        "source_name",
        "article_date",
        "embedded_music_links",
        "release_article",
    ]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for candidate in candidates:
            row = candidate.as_dict()
            row["embedded_music_links"] = " | ".join(candidate.embedded_music_links)
            writer.writerow({field: row.get(field) for field in fieldnames})


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(name)s: %(message)s")

    releases = extract_releases(
        source=args.source,
        url=args.url,
        lookback_days=args.lookback_days,
        enrich_articles=not args.skip_enrichment,
        max_pages=args.max_pages,
    )
    json_output = Path(args.output)
    csv_output = Path(args.csv_output) if args.csv_output else json_output.with_suffix(".csv")
    write_json(releases, json_output)
    write_csv(releases, csv_output)
    LOGGER.info("Wrote %d releases to %s and %s", len(releases), json_output, csv_output)


if __name__ == "__main__":
    main()
