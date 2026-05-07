from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.followed_artists import build_followed_artists, write_followed_artists_csv
from src.recent_tracks import fetch_recent_tracks_from_csv, write_json
from src.soundcloud_api import SoundCloudAPIClient

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find recent EDM tracks from SoundCloud accounts you follow.")
    parser.add_argument("--artists-output", default="followed_artists.csv")
    parser.add_argument("--artists-input", default="followed_artists.csv")
    parser.add_argument("--output", default="data/recent_tracks.json")
    parser.add_argument("--max-users", type=int, default=0, help="Optional cap for testing.")
    parser.add_argument("--track-sample-limit", type=int, default=10, help="Tracks sampled per followed user for genre detection.")
    parser.add_argument("--track-limit", type=int, default=50, help="Tracks inspected per EDM followed user for recent releases.")
    parser.add_argument("--lookback-days", type=int, default=14)
    parser.add_argument("--include-non-edm", action="store_true", help="Write all followed users instead of EDM-ish users only.")
    parser.add_argument("--skip-artist-refresh", action="store_true", help="Reuse --artists-input instead of fetching followed users.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(name)s: %(message)s")
    client = SoundCloudAPIClient()

    artists_csv = Path(args.artists_input if args.skip_artist_refresh else args.artists_output)
    if not args.skip_artist_refresh:
        artists = build_followed_artists(
            client,
            max_users=args.max_users or None,
            track_sample_limit=args.track_sample_limit,
            edm_only=not args.include_non_edm,
        )
        write_followed_artists_csv(artists, Path(args.artists_output))
        LOGGER.info("Wrote %d followed artists to %s", len(artists), args.artists_output)

    candidates = fetch_recent_tracks_from_csv(
        artists_csv,
        client=client,
        lookback_days=args.lookback_days,
        track_limit=args.track_limit,
    )
    write_json(candidates, Path(args.output))
    LOGGER.info("Wrote %d recent tracks to %s", len(candidates), args.output)


if __name__ == "__main__":
    main()
