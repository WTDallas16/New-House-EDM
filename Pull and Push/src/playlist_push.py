from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.models import ResolvedTrack
from src.soundcloud_tools import SoundCloudTools, soundcloud_ids_from_tracks
from src.spotify_tools import SpotifyTools, spotify_uris_from_tracks

LOGGER = logging.getLogger(__name__)


def push_playlists(
    tracks: list[ResolvedTrack],
    data_root: Path,
    playlist_name: str,
    soundcloud_tracks: list[ResolvedTrack] | None = None,
    push_spotify: bool = True,
    push_soundcloud: bool = True,
    spotify_public: bool = False,
    soundcloud_sharing: str = "private",
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "playlist_name": playlist_name,
        "pushed_at": datetime.now(timezone.utc).isoformat(),
        "spotify": {"attempted": False, "playlist_id": None, "track_count": 0, "error": None},
        "soundcloud": {"attempted": False, "playlist_id": None, "track_count": 0, "error": None},
    }

    if push_spotify:
        spotify_uris = spotify_uris_from_tracks(tracks)
        report["spotify"]["attempted"] = True
        report["spotify"]["track_count"] = len(spotify_uris)
        try:
            spotify = SpotifyTools(data_root)
            playlist_id = spotify.find_or_create_playlist(playlist_name, public=spotify_public)
            spotify.replace_playlist_tracks(playlist_id, spotify_uris)
            report["spotify"]["playlist_id"] = playlist_id
            LOGGER.info("Updated Spotify playlist %s with %d tracks", playlist_name, len(spotify_uris))
        except Exception as exc:  # noqa: BLE001 - report should capture API failures without hiding other platform.
            report["spotify"]["error"] = str(exc)
            LOGGER.error("Spotify playlist update failed: %s", exc)

    if push_soundcloud:
        soundcloud_ids = soundcloud_ids_from_tracks(soundcloud_tracks or tracks)
        report["soundcloud"]["attempted"] = True
        report["soundcloud"]["track_count"] = len(soundcloud_ids)
        try:
            soundcloud = SoundCloudTools(data_root)
            playlist_id = soundcloud.find_or_create_playlist(playlist_name, sharing=soundcloud_sharing)
            soundcloud.replace_playlist_tracks(playlist_id, soundcloud_ids)
            report["soundcloud"]["playlist_id"] = playlist_id
            LOGGER.info("Updated SoundCloud playlist %s with %d tracks", playlist_name, len(soundcloud_ids))
        except Exception as exc:  # noqa: BLE001
            report["soundcloud"]["error"] = str(exc)
            LOGGER.error("SoundCloud playlist update failed: %s", exc)

    return report


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
