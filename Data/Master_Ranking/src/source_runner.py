from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SourceCommand:
    name: str
    project_dir: Path
    output_path: Path
    args: list[str]
    api_source: bool = False


@dataclass(frozen=True, slots=True)
class SourceRunResult:
    name: str
    output_path: Path
    success: bool
    returncode: int


def default_source_commands(
    repo_root: Path,
    output_dir: Path,
    lookback_days: int = 14,
    max_pages: int = 10,
    include_artist_profile_scan: bool = False,
) -> list[SourceCommand]:
    output_dir.mkdir(parents=True, exist_ok=True)
    commands = [
        SourceCommand(
            name="weraveyou",
            project_dir=repo_root / "weraveyou",
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
        SourceCommand(
            name="edmtunes",
            project_dir=repo_root / "edmtunes",
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
        SourceCommand(
            name="edmcom",
            project_dir=repo_root / "edm.com",
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
        SourceCommand(
            name="submithub",
            project_dir=repo_root / "submithub",
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
        SourceCommand(
            name="spotify_playlists",
            project_dir=repo_root / "Spotify_Playlists",
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
        SourceCommand(
            name="soundcloud_playlists",
            project_dir=repo_root / "SoundCloud_Playlists",
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
    ]
    if include_artist_profile_scan:
        commands.append(
            SourceCommand(
                name="top_artisits_recent",
                project_dir=repo_root / "Top_Artisits",
                output_path=output_dir / "top_artisits_recent.json",
                args=[
                    "-m",
                    "src.recent_tracks",
                    "--artists-csv",
                    "master_artist_list.csv",
                    "--lookback-days",
                    str(lookback_days),
                ],
                api_source=True,
            )
        )
    return commands


def filter_commands(
    commands: list[SourceCommand],
    only_sources: list[str],
    skip_sources: list[str],
    skip_api_sources: bool,
) -> list[SourceCommand]:
    only = {source.strip() for source in only_sources if source.strip()}
    skip = {source.strip() for source in skip_sources if source.strip()}
    filtered = []
    for command in commands:
        if only and command.name not in only:
            continue
        if command.name in skip:
            continue
        if skip_api_sources and command.api_source:
            continue
        filtered.append(command)
    return filtered


def run_source_commands(commands: list[SourceCommand], continue_on_error: bool = False) -> list[SourceRunResult]:
    results: list[SourceRunResult] = []
    for command in commands:
        full_command = [sys.executable, *command.args, "--output", str(command.output_path)]
        LOGGER.info("Refreshing %s", command.name)
        env = os.environ.copy()
        pythonpath_parts = [str(command.project_dir.parent)]
        if env.get("PYTHONPATH"):
            pythonpath_parts.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
        completed = subprocess.run(full_command, cwd=command.project_dir, check=False, env=env)
        success = completed.returncode == 0 and command.output_path.exists()
        results.append(
            SourceRunResult(
                name=command.name,
                output_path=command.output_path,
                success=success,
                returncode=completed.returncode,
            )
        )
        if not success:
            message = f"{command.name} failed with exit code {completed.returncode}"
            if continue_on_error:
                LOGGER.warning("%s; continuing", message)
            else:
                raise RuntimeError(message)
    return results
