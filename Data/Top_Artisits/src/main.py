from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path

from src.musicmetricsvault import GenreTarget, MusicMetricsVaultScraper, dedupe_artists, load_genre_targets
from src.soundcloud_lookup import SoundCloudArtistLookup
from src.spotify_lookup import SpotifyArtistLookup

LOGGER = logging.getLogger(__name__)

DEFAULT_TARGETS = [
    GenreTarget("https://www.musicmetricsvault.com/genres/house/268", 200),
    GenreTarget("https://www.musicmetricsvault.com/genres/edm-trap/399", 100),
    GenreTarget("https://www.musicmetricsvault.com/genres/afro-house/393", 100),
    GenreTarget("https://www.musicmetricsvault.com/genres/funky-house/669", 300),
    GenreTarget("https://www.musicmetricsvault.com/genres/tech-house/118", 300),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a master artist list from MusicMetricsVault genre pages.")
    parser.add_argument("--genre-file", default=None, help="CSV-ish text file with lines: url,limit[,genre].")
    parser.add_argument("--output", default="master_artist_list.csv")
    parser.add_argument("--limit-artists", type=int, default=0, help="Optional first-N artist limit for testing/enrichment.")
    parser.add_argument("--no-spotify-search", action="store_true", help="Do not use Spotify API fallback for missing Spotify IDs.")
    parser.add_argument("--soundcloud-search", action="store_true", help="Search SoundCloud user profiles and add soundcloud_url/soundcloud_user_id columns.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def build_artist_rows(
    genre_file: str | None = None,
    use_spotify_search: bool = True,
    use_soundcloud_search: bool = False,
    limit_artists: int = 0,
):
    targets = load_genre_targets(genre_file) if genre_file else DEFAULT_TARGETS
    scraper = MusicMetricsVaultScraper()
    rows = []
    for target in targets:
        rows.extend(scraper.scrape_genre(target))
    rows = dedupe_artists(rows)
    if limit_artists:
        rows = rows[:limit_artists]
    if use_spotify_search:
        lookup = SpotifyArtistLookup()
        for row in rows:
            if not row.spotify_url:
                row.spotify_url = lookup.search_artist_url(row.artist_name)
    if use_soundcloud_search:
        soundcloud_lookup = SoundCloudArtistLookup()
        for row in rows:
            if row.soundcloud_url or row.soundcloud_user_id:
                continue
            match = soundcloud_lookup.search_artist(row.artist_name)
            if match:
                row.soundcloud_url = match.url
                row.soundcloud_user_id = match.user_id
    return rows


def write_csv(rows, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["artist_name", "spotify_url", "soundcloud_url", "soundcloud_user_id", "genre", "rank", "monthly_listeners"]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.csv_row())


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(name)s: %(message)s")
    rows = build_artist_rows(
        genre_file=args.genre_file,
        use_spotify_search=not args.no_spotify_search,
        use_soundcloud_search=args.soundcloud_search,
        limit_artists=args.limit_artists,
    )
    output = Path(args.output)
    write_csv(rows, output)
    LOGGER.info("Wrote %d artists to %s", len(rows), output)


if __name__ == "__main__":
    main()
