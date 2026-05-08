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
    max_per_associated_artist: int = 3,
    skip_variants: bool = True,
    enforce_isrc_window: bool = True,
    require_platform_link: bool = True,
    lookback_days: int = 7,
    today: date | None = None,
) -> list[ResolvedTrack]:
    kept: list[ResolvedTrack] = []
    counts: defaultdict[str, int] = defaultdict(int)
    associated_counts: defaultdict[str, int] = defaultdict(int)
    current_day = today or date.today()
    preferred_track_ids = preferred_version_track_ids(tracks)

    for track in tracks:
        if id(track) not in preferred_track_ids:
            track.notes.append("skipped_duplicate_version")
            continue
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
        associated_keys = associated_artist_keys(track)
        capped_key = next((key for key in associated_keys if associated_counts[key] >= max_per_associated_artist), "")
        if capped_key:
            track.notes.append(f"skipped_associated_artist_cap_{max_per_associated_artist}:{capped_key}")
            continue
        if artist_key:
            counts[artist_key] += 1
        for key in associated_keys:
            associated_counts[key] += 1
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


def preferred_version_track_ids(tracks: list[ResolvedTrack]) -> set[int]:
    selected: dict[str, ResolvedTrack] = {}
    for track in tracks:
        key = duplicate_version_key(track)
        if not key:
            selected[str(id(track))] = track
            continue
        current = selected.get(key)
        if current is None or version_preference(track) > version_preference(current):
            selected[key] = track
    return {id(track) for track in selected.values()}


def duplicate_version_key(track: ResolvedTrack) -> str:
    artist_key = primary_artist_key(track.artist)
    title_key = base_version_title_key(track.title)
    return f"{artist_key}|{title_key}" if artist_key and title_key else ""


def version_preference(track: ResolvedTrack) -> tuple[int, int, float]:
    return (
        0 if is_extended_or_edit_version(track) else 1,
        1 if has_platform_link(track) else 0,
        track.ranking_score,
    )


def is_extended_or_edit_version(track: ResolvedTrack) -> bool:
    text = " ".join(
        clean_text(value)
        for value in [
            track.title,
            track.source_record.get("source_article_title"),
            (track.source_record.get("open_graph") or {}).get("album_name"),
        ]
        if value
    )
    return bool(re.search(r"\b(extended|extended\s+mix|radio\s+edit|club\s+mix|original\s+mix|edit)\b", text, flags=re.IGNORECASE))


def base_version_title_key(title: str) -> str:
    text = normalize_text(title)
    text = re.sub(
        r"\b("
        r"extended|extended version|extended mix|radio edit|club mix|original mix|"
        r"edit|mix|version"
        r")\b",
        " ",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


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


def associated_artist_keys(track: ResolvedTrack) -> list[str]:
    open_graph = track.source_record.get("open_graph") or {}
    values = [
        track.artist,
        open_graph.get("all_artists"),
        open_graph.get("source_artist_name"),
    ]
    keys: list[str] = []
    for value in values:
        keys.extend(split_artist_keys(clean_text(value)))
    seen: set[str] = set()
    unique: list[str] = []
    for key in keys:
        if key and key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def split_artist_keys(value: str) -> list[str]:
    text = re.sub(r"\([^)]*\)", " ", value)
    return [
        normalize_text(part)
        for part in re.split(r"\s*(?:,|&|\+|\bx\b|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b)\s*", text, flags=re.IGNORECASE)
        if normalize_text(part)
    ]


def has_platform_link(track: ResolvedTrack) -> bool:
    return bool(track.spotify_uri or track.spotify_id or track.soundcloud_track_id or track.soundcloud_url)
