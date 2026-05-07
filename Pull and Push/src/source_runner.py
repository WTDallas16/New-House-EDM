from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from src.models import SourceResult, SourceSpec

LOGGER = logging.getLogger(__name__)


def default_source_specs(
    data_root: Path,
    output_dir: Path,
    lookback_days: int = 14,
    max_pages: int = 10,
    refresh_followed_artists: bool = False,
    followed_track_limit: int = 50,
    top_artisits_soundcloud_only: bool = False,
) -> list[SourceSpec]:
    """Build source commands in the requested rate-limit-friendly order.

    The user's list had SoundCloud_Playlists twice. This workflow treats the
    fourth slot as Spotify_Playlists, which keeps the known source set complete.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    followed_args = [
        "-m",
        "src.main",
        "--lookback-days",
        str(lookback_days),
        "--track-limit",
        str(followed_track_limit),
        "--artists-output",
        "followed_artists.csv",
    ]
    if not refresh_followed_artists and (data_root / "New tracks from people I follow" / "followed_artists.csv").exists():
        followed_args.extend(["--skip-artist-refresh", "--artists-input", "followed_artists.csv"])

    top_args = [
        "-m",
        "src.recent_tracks",
        "--artists-csv",
        "master_artist_list.csv",
        "--lookback-days",
        str(lookback_days),
        "--ranking-mode",
        "fast",
        "--soundcloud-fallback",
    ]
    if top_artisits_soundcloud_only:
        top_args.append("--soundcloud-only")

    return [
        SourceSpec(
            name="edmcom",
            project_dir=data_root / "edm.com",
            output_path=output_dir / "edmcom.json",
            args=[
                "-m",
                "src.main",
                "--source",
                "edmcom",
                "--url",
                "https://edm.com/music-releases/",
                "--lookback-days",
                str(lookback_days),
                "--max-pages",
                "5",
            ],
        ),
        SourceSpec(
            name="edmtunes",
            project_dir=data_root / "edmtunes",
            output_path=output_dir / "edmtunes.json",
            args=[
                "-m",
                "src.main",
                "--source",
                "edmtunes",
                "--url",
                "https://www.edmtunes.com/music/",
                "--lookback-days",
                str(lookback_days),
                "--max-pages",
                str(max_pages),
            ],
        ),
        SourceSpec(
            name="soundcloud_playlists",
            project_dir=data_root / "SoundCloud_Playlists",
            output_path=output_dir / "soundcloud_playlists.json",
            args=[
                "-m",
                "src.main",
                "--playlists-file",
                "playlist.txt",
                "--lookback-days",
                str(lookback_days),
                "--api-only",
            ],
            api_source=True,
        ),
        SourceSpec(
            name="spotify_playlists",
            project_dir=data_root / "Spotify_Playlists",
            output_path=output_dir / "spotify_playlists.json",
            args=[
                "-m",
                "src.main",
                "--playlists-file",
                "playlists.txt",
                "--market",
                "US",
            ],
            api_source=True,
        ),
        SourceSpec(
            name="submithub",
            project_dir=data_root / "submithub",
            output_path=output_dir / "submithub.json",
            args=[
                "-m",
                "src.main",
                "--source",
                "submithub",
                "--url",
                "https://www.submithub.com/popular?genre=House%20%2F%20Techno",
                "--lookback-days",
                str(lookback_days),
                "--max-pages",
                "100",
            ],
        ),
        SourceSpec(
            name="weraveyou",
            project_dir=data_root / "weraveyou",
            output_path=output_dir / "weraveyou.json",
            args=[
                "-m",
                "src.main",
                "--source",
                "weraveyou",
                "--url",
                "https://weraveyou.com/category/music/house/",
                "--lookback-days",
                str(lookback_days),
                "--max-pages",
                str(max_pages),
            ],
        ),
        SourceSpec(
            name="1001tracklists",
            project_dir=data_root / "1001tracklists",
            output_path=output_dir / "1001tracklists.json",
            args=[
                "-m",
                "src.main",
                "--source",
                "1001tracklists",
                "--url",
                "https://www.1001tracklists.com/genre/house/index.html",
                "--lookback-days",
                str(lookback_days),
                "--max-pages",
                "3",
            ],
        ),
        SourceSpec(
            name="followed_soundcloud",
            project_dir=data_root / "New tracks from people I follow",
            output_path=output_dir / "followed_soundcloud.json",
            args=followed_args,
            api_source=True,
        ),
        SourceSpec(
            name="top_artisits_recent",
            project_dir=data_root / "Top_Artisits",
            output_path=output_dir / "top_artisits_recent.json",
            args=top_args,
            api_source=True,
        ),
    ]


def filter_specs(specs: list[SourceSpec], only: list[str], skip: list[str], skip_api_sources: bool = False) -> list[SourceSpec]:
    only_set = {value.strip() for value in only if value.strip()}
    skip_set = {value.strip() for value in skip if value.strip()}
    filtered: list[SourceSpec] = []
    for spec in specs:
        if only_set and spec.name not in only_set:
            continue
        if spec.name in skip_set:
            continue
        if skip_api_sources and spec.api_source:
            continue
        filtered.append(spec)
    return filtered


def run_sources(specs: list[SourceSpec], continue_on_error: bool = False) -> list[SourceResult]:
    results: list[SourceResult] = []
    for spec in specs:
        if not spec.project_dir.exists():
            result = SourceResult(spec.name, spec.output_path, False, 127)
            results.append(result)
            if continue_on_error:
                LOGGER.warning("Skipping %s; project directory does not exist: %s", spec.name, spec.project_dir)
                continue
            raise RuntimeError(f"{spec.name} project directory does not exist: {spec.project_dir}")

        full_command = [sys.executable, *spec.args, "--output", str(spec.output_path)]
        env = os.environ.copy()
        pythonpath_parts = [str(spec.project_dir.parent)]
        if env.get("PYTHONPATH"):
            pythonpath_parts.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)

        LOGGER.info("Refreshing %s", spec.name)
        completed = subprocess.run(full_command, cwd=spec.project_dir, env=env, check=False)
        success = completed.returncode == 0 and spec.output_path.exists()
        results.append(SourceResult(spec.name, spec.output_path, success, completed.returncode))
        if not success:
            message = f"{spec.name} failed with exit code {completed.returncode}"
            if continue_on_error:
                LOGGER.warning("%s; continuing", message)
            else:
                raise RuntimeError(message)
    return results
