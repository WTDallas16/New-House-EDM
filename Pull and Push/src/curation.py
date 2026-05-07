from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from src.models import ResolvedTrack
from src.normalize import clean_text, normalize_text

VARIANT_PATTERNS = re.compile(
    r"\b("
    r"slowed|slow(?:er)?|super\s+slowed|ultra\s+slowed|"
    r"sped\s*up|speed\s*up|fast(?:er)?\s+version|nightcore|"
    r"rework|remaster(?:ed)?|remastered\s+version|anniversary\s+mix|"
    r"cover"
    r")\b",
    re.IGNORECASE,
)


def curate_playlist_tracks(
    tracks: list[ResolvedTrack],
    max_per_artist: int = 2,
    skip_variants: bool = True,
    enforce_isrc_window: bool = True,
    require_platform_link: bool = True,
    lookback_days: int = 7,
    today: date | None = None,
) -> list[ResolvedTrack]:
    kept: list[ResolvedTrack] = []
    counts: defaultdict[str, int] = defaultdict(int)
    current_day = today or date.today()

    for track in tracks:
        if skip_variants and is_unwanted_speed_variant(track):
            track.notes.append("skipped_unwanted_speed_variant")
            continue
        if enforce_isrc_window and isrc_year_is_outside_window(track, current_day=current_day, lookback_days=lookback_days):
            track.notes.append("skipped_old_isrc_year")
            continue
        if require_platform_link and not has_platform_link(track):
            track.notes.append("skipped_no_verified_platform_link")
            continue
        artist_key = primary_artist_key(track.artist)
        if artist_key and counts[artist_key] >= max_per_artist:
            track.notes.append(f"skipped_artist_cap_{max_per_artist}")
            continue
        if artist_key:
            counts[artist_key] += 1
        kept.append(track)

    for index, track in enumerate(kept, start=1):
        track.rank = index
    return kept


def is_unwanted_speed_variant(track: ResolvedTrack) -> bool:
    values = [
        track.title,
        track.source_record.get("source_article_title"),
        track.source_record.get("source_article_url"),
        track.soundcloud_url,
    ]
    open_graph = track.source_record.get("open_graph") or {}
    values.extend([open_graph.get("album_name"), open_graph.get("tag_list")])
    text = " ".join(clean_text(value) for value in values if value)
    return bool(VARIANT_PATTERNS.search(text))


def isrc_year_is_outside_window(track: ResolvedTrack, current_day: date, lookback_days: int) -> bool:
    isrc_year = isrc_release_year((track.source_record.get("open_graph") or {}).get("isrc"))
    if isrc_year is None:
        return False
    allowed_years = {current_day.year}
    if current_day.timetuple().tm_yday <= max(lookback_days, 1):
        allowed_years.add(current_day.year - 1)
    return isrc_year not in allowed_years


def isrc_release_year(isrc: object) -> int | None:
    text = clean_text(isrc).upper()
    if len(text) < 7:
        return None
    year_code = text[5:7]
    if not year_code.isdigit():
        return None
    value = int(year_code)
    return 2000 + value if value <= 79 else 1900 + value


def primary_artist_key(artist: str) -> str:
    text = clean_text(artist)
    text = re.sub(r"\([^)]*\)", " ", text)
    primary = re.split(r"\s*(?:,|&|\+|\bx\b|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b)\s*", text, maxsplit=1, flags=re.IGNORECASE)[0]
    return normalize_text(primary)


def has_platform_link(track: ResolvedTrack) -> bool:
    return bool(track.spotify_uri or track.spotify_id or track.soundcloud_track_id or track.soundcloud_url)
