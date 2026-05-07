from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

from src.extraction.normalize import dedupe_releases
from src.models import ReleaseCandidate
from src.scrapers.spotify_playlists import SpotifyPlaylistScraper, playlist_values_from_file

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract release candidates from Spotify playlists.")
    parser.add_argument("--playlist", action="append", default=[], help="Spotify playlist URL, URI, or ID.")
    parser.add_argument("--playlists-file", default=None, help="Text file with one Spotify playlist URL/URI/ID per line.")
    parser.add_argument("--market", default="US", help="Spotify market code for track availability, default US.")
    parser.add_argument("--output", default="data/extracted_releases.json")
    parser.add_argument("--csv-output", default=None)
    parser.add_argument("--no-dedupe", action="store_true")
    parser.add_argument("--fail-on-playlist-error", action="store_true", help="Stop on invalid/inaccessible playlists instead of skipping them.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def extract_releases(
    playlist_values: list[str],
    playlists_file: str | None = None,
    market: str | None = "US",
    dedupe: bool = True,
    skip_playlist_errors: bool = True,
) -> list[ReleaseCandidate]:
    values = list(playlist_values)
    if playlists_file:
        values.extend(playlist_values_from_file(playlists_file))
    scraper = SpotifyPlaylistScraper(skip_playlist_errors=skip_playlist_errors)
    candidates = scraper.scrape_releases(values, market=market)
    return dedupe_releases(candidates) if dedupe else candidates


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
        market=args.market,
        dedupe=not args.no_dedupe,
        skip_playlist_errors=not args.fail_on_playlist_error,
    )
    json_output = Path(args.output)
    csv_output = Path(args.csv_output) if args.csv_output else json_output.with_suffix(".csv")
    write_json(releases, json_output)
    write_csv(releases, csv_output)
    LOGGER.info("Wrote %d releases to %s and %s", len(releases), json_output, csv_output)


if __name__ == "__main__":
    main()
