from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import date, timedelta
from pathlib import Path

from src.extraction.normalize import dedupe_releases
from src.models import ReleaseCandidate
from src.scrapers.soundcloud_playlists import SoundCloudPlaylistScraper, playlist_values_from_file

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract release candidates from SoundCloud playlists.")
    parser.add_argument("--playlist", action="append", default=[], help="SoundCloud playlist URL or user/sets/path.")
    parser.add_argument("--playlists-file", default=None, help="Text file with one SoundCloud playlist URL per line.")
    parser.add_argument("--output", default="data/extracted_releases.json")
    parser.add_argument("--csv-output", default=None)
    parser.add_argument("--no-dedupe", action="store_true")
    parser.add_argument("--token-file", default=None, help="Path to SoundCloud OAuth token JSON. Defaults to SC_TOKEN_FILE or sc_token.json.")
    parser.add_argument("--api-only", action="store_true", help="Disable HTML fallback if the SoundCloud API fails.")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=14,
        help="Only keep tracks with article_date on or after today minus this many days. Use 0 to disable.",
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def extract_releases(
    playlist_values: list[str],
    playlists_file: str | None = None,
    dedupe: bool = True,
    token_file: str | None = None,
    api_only: bool = False,
    lookback_days: int | None = 14,
) -> list[ReleaseCandidate]:
    values = list(playlist_values)
    if playlists_file:
        values.extend(playlist_values_from_file(playlists_file))
    scraper = SoundCloudPlaylistScraper(token_file=token_file, use_html_fallback=not api_only)
    candidates = scraper.scrape_releases(values)
    candidates = filter_by_article_date(candidates, lookback_days=lookback_days)
    return dedupe_releases(candidates) if dedupe else candidates


def filter_by_article_date(
    candidates: list[ReleaseCandidate],
    lookback_days: int | None = 14,
    today: date | None = None,
) -> list[ReleaseCandidate]:
    if not lookback_days or lookback_days <= 0:
        return candidates
    cutoff = (today or date.today()) - timedelta(days=lookback_days)
    filtered: list[ReleaseCandidate] = []
    for candidate in candidates:
        parsed_date = parse_article_date(candidate.article_date)
        if parsed_date and parsed_date >= cutoff:
            filtered.append(candidate)
    return filtered


def parse_article_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


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
        playlist_values=args.playlist,
        playlists_file=args.playlists_file,
        dedupe=not args.no_dedupe,
        token_file=args.token_file,
        api_only=args.api_only,
        lookback_days=args.lookback_days,
    )
    json_output = Path(args.output)
    csv_output = Path(args.csv_output) if args.csv_output else json_output.with_suffix(".csv")
    write_json(releases, json_output)
    write_csv(releases, csv_output)
    LOGGER.info("Wrote %d releases to %s and %s", len(releases), json_output, csv_output)


if __name__ == "__main__":
    main()
