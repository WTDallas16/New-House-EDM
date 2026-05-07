from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.ranker import DEFAULT_INPUTS, load_records, rank_records, unique_records, write_json
from src.source_runner import default_source_commands, filter_commands, run_source_commands

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rank release candidates across all working music sources.")
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="Input JSON path. Can be passed multiple times. Defaults to the known source outputs.",
    )
    parser.add_argument("--input-dir", action="append", default=[], help="Read all *.json files from this directory. Can be repeated.")
    parser.add_argument("--output", default="data/ranked_releases.json")
    parser.add_argument("--unique-output", default="data/ranked_releases_unique.json")
    parser.add_argument("--no-unique-output", action="store_true")
    parser.add_argument("--refresh-sources", action="store_true", help="Run source extractors first, then rank only their fresh outputs.")
    parser.add_argument("--refresh-output-dir", default="data/source_outputs")
    parser.add_argument("--refresh-lookback-days", type=int, default=14)
    parser.add_argument("--refresh-max-pages", type=int, default=10)
    parser.add_argument("--refresh-source", action="append", default=[], help="Only refresh this source name. Can be repeated.")
    parser.add_argument("--skip-source", action="append", default=[], help="Skip this source name during refresh. Can be repeated.")
    parser.add_argument("--skip-api-sources", action="store_true", help="Skip Spotify/SoundCloud API-backed refresh commands.")
    parser.add_argument(
        "--include-artist-profile-scan",
        action="store_true",
        help="Opt into the heavy Top_Artisits Spotify artist-albums scan. Disabled by default to avoid rate limits.",
    )
    parser.add_argument("--continue-on-source-error", action="store_true", help="Rank successful refresh outputs even if one source fails.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def resolve_inputs(raw_inputs: list[str]) -> list[Path]:
    inputs = raw_inputs or DEFAULT_INPUTS
    return [Path(value).expanduser().resolve() for value in inputs]


def resolve_input_dirs(raw_dirs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for raw_dir in raw_dirs:
        directory = Path(raw_dir).expanduser().resolve()
        paths.extend(sorted(directory.glob("*.json")))
    return paths


def resolve_all_inputs(raw_inputs: list[str], raw_dirs: list[str]) -> list[Path]:
    paths = resolve_input_dirs(raw_dirs)
    paths.extend(Path(value).expanduser().resolve() for value in raw_inputs)
    if not paths:
        paths = resolve_inputs([])
    return paths


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(name)s: %(message)s")

    paths = resolve_all_inputs(args.input, args.input_dir)
    if args.refresh_sources:
        repo_root = Path(__file__).resolve().parents[2]
        output_dir = Path(args.refresh_output_dir).resolve()
        include_artist_profile_scan = args.include_artist_profile_scan or "top_artisits_recent" in set(args.refresh_source)
        commands = default_source_commands(
            repo_root=repo_root,
            output_dir=output_dir,
            lookback_days=args.refresh_lookback_days,
            max_pages=args.refresh_max_pages,
            include_artist_profile_scan=include_artist_profile_scan,
        )
        commands = filter_commands(
            commands,
            only_sources=args.refresh_source,
            skip_sources=args.skip_source,
            skip_api_sources=args.skip_api_sources,
        )
        results = run_source_commands(commands, continue_on_error=args.continue_on_source_error)
        paths = [result.output_path for result in results if result.success]
        LOGGER.info("Ranking %d refreshed source outputs", len(paths))

    records = load_records(paths)
    ranked = rank_records(records)
    output = Path(args.output)
    write_json(ranked, output)
    LOGGER.info("Wrote %d ranked records to %s", len(ranked), output)

    if not args.no_unique_output:
        unique = unique_records(ranked)
        unique_output = Path(args.unique_output)
        write_json(unique, unique_output)
        LOGGER.info("Wrote %d unique ranked records to %s", len(unique), unique_output)


if __name__ == "__main__":
    main()
