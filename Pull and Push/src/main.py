from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.curation import curate_playlist_tracks
from src.playlist_push import push_playlists, write_report
from src.ranking_bridge import filter_records_by_lookback, rank_inputs, write_json
from src.resolver import resolve_top_tracks, write_resolved
from src.source_runner import default_source_specs, filter_specs, run_sources

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pull source releases, rank the best tracks, and update New House playlists.")
    parser.add_argument("--data-root", default="../Data", help="Path containing the source project folders.")
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--candidate-pool-size", type=int, default=150, help="Resolve this many ranked candidates before final curation.")
    parser.add_argument("--soundcloud-target-count", type=int, default=50, help="Backfill SoundCloud playlist from the candidate pool until this many tracks are available.")
    parser.add_argument("--max-per-artist", type=int, default=2)
    parser.add_argument("--allow-speed-variants", action="store_true", help="Allow slowed/sped-up/nightcore style variants into the final playlist.")
    parser.add_argument("--allow-old-isrc-years", action="store_true", help="Allow tracks whose ISRC year predates the current release window.")
    parser.add_argument("--playlist-name", default="New House")
    parser.add_argument("--source-output-dir", default="data/source_outputs")
    parser.add_argument("--ranked-output", default="data/ranked_releases.json")
    parser.add_argument("--unique-output", default="data/ranked_releases_unique.json")
    parser.add_argument("--resolved-output", default="data/top_50_resolved.json")
    parser.add_argument("--soundcloud-resolved-output", default="data/soundcloud_resolved.json")
    parser.add_argument("--push-report", default="data/push_report.json")
    parser.add_argument("--link-cache", default="data/link_cache.json")
    parser.add_argument("--spotify-backlog", default="data/spotify_link_backlog.json")
    parser.add_argument("--skip-refresh", action="store_true", help="Use existing JSON files in --source-output-dir.")
    parser.add_argument("--refresh-source", action="append", default=[], help="Only refresh this source. Can be repeated.")
    parser.add_argument("--skip-source", action="append", default=[], help="Skip this source. Can be repeated.")
    parser.add_argument("--skip-api-sources", action="store_true")
    parser.add_argument("--continue-on-source-error", action="store_true")
    parser.add_argument("--refresh-followed-artists", action="store_true", help="Rebuild the SoundCloud followed artists CSV before fetching tracks.")
    parser.add_argument("--followed-track-limit", type=int, default=50)
    parser.add_argument("--top-artisits-soundcloud-only", action="store_true", help="Run Top_Artisits recent scan through SoundCloud profiles only.")
    parser.add_argument("--skip-spotify-resolution", action="store_true")
    parser.add_argument("--skip-soundcloud-resolution", action="store_true")
    parser.add_argument("--push", action="store_true", help="Actually empty/create and update Spotify/SoundCloud playlists.")
    parser.add_argument("--skip-spotify-push", action="store_true")
    parser.add_argument("--skip-soundcloud-push", action="store_true")
    parser.add_argument("--spotify-public", action="store_true")
    parser.add_argument("--soundcloud-sharing", default="private", choices=["private", "public"])
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(name)s: %(message)s")

    project_root = Path(__file__).resolve().parents[1]
    data_root = (project_root / args.data_root).resolve()
    source_output_dir = (project_root / args.source_output_dir).resolve()

    if args.skip_refresh:
        input_paths = sorted(source_output_dir.glob("*.json"))
        LOGGER.info("Using %d existing source outputs from %s", len(input_paths), source_output_dir)
    else:
        specs = default_source_specs(
            data_root=data_root,
            output_dir=source_output_dir,
            lookback_days=args.lookback_days,
            max_pages=args.max_pages,
            refresh_followed_artists=args.refresh_followed_artists,
            followed_track_limit=args.followed_track_limit,
            top_artisits_soundcloud_only=args.top_artisits_soundcloud_only,
        )
        specs = filter_specs(specs, only=args.refresh_source, skip=args.skip_source, skip_api_sources=args.skip_api_sources)
        results = run_sources(specs, continue_on_error=args.continue_on_source_error)
        input_paths = [result.output_path for result in results if result.success]
        LOGGER.info("Collected %d refreshed source outputs", len(input_paths))

    ranked, unique = rank_inputs(data_root, input_paths)
    ranked = filter_records_by_lookback(ranked, args.lookback_days)
    unique = filter_records_by_lookback(unique, args.lookback_days)
    ranked_output = project_root / args.ranked_output
    unique_output = project_root / args.unique_output
    write_json(ranked_output, ranked)
    write_json(unique_output, unique)
    LOGGER.info("Wrote %d ranked records and %d unique records", len(ranked), len(unique))

    resolved_pool = resolve_top_tracks(
        unique,
        top_n=max(args.top_n, args.candidate_pool_size),
        data_root=data_root,
        cache_path=project_root / args.link_cache,
        backlog_path=project_root / args.spotify_backlog,
        resolve_spotify=not args.skip_spotify_resolution,
        resolve_soundcloud=not args.skip_soundcloud_resolution,
        lookback_days=args.lookback_days,
    )
    curated_pool = curate_playlist_tracks(
        resolved_pool,
        max_per_artist=args.max_per_artist,
        skip_variants=not args.allow_speed_variants,
        enforce_isrc_window=not args.allow_old_isrc_years,
        lookback_days=args.lookback_days,
    )
    resolved = curated_pool[: args.top_n]
    soundcloud_resolved = soundcloud_playlist_tracks(curated_pool, args.soundcloud_target_count)
    write_resolved(project_root / args.resolved_output, resolved)
    write_resolved(project_root / args.soundcloud_resolved_output, soundcloud_resolved)
    LOGGER.info("Resolved platform links for top %d tracks", len(resolved))
    LOGGER.info("Prepared %d SoundCloud playlist tracks", len(soundcloud_resolved))

    if args.push:
        report = push_playlists(
            resolved,
            soundcloud_tracks=soundcloud_resolved,
            data_root=data_root,
            playlist_name=args.playlist_name,
            push_spotify=not args.skip_spotify_push,
            push_soundcloud=not args.skip_soundcloud_push,
            spotify_public=args.spotify_public,
            soundcloud_sharing=args.soundcloud_sharing,
        )
    else:
        report = {
            "playlist_name": args.playlist_name,
            "dry_run": True,
            "message": "No playlists were changed. Pass --push to empty/create and update playlists.",
            "spotify_tracks_ready": len([track for track in resolved if track.spotify_uri]),
            "soundcloud_tracks_ready": len([track for track in soundcloud_resolved if track.soundcloud_track_id]),
        }
    write_report(project_root / args.push_report, report)
    LOGGER.info("Wrote push report to %s", project_root / args.push_report)


def soundcloud_playlist_tracks(tracks, target_count: int):
    selected = []
    seen = set()
    for track in tracks:
        track_id = str(track.soundcloud_track_id or "").strip()
        if not track_id or track_id in seen:
            continue
        seen.add(track_id)
        selected.append(track)
        if len(selected) >= target_count:
            break
    return selected


if __name__ == "__main__":
    main()
