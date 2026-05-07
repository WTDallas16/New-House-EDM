from datetime import date

from src.curation import curate_playlist_tracks, is_unwanted_speed_variant, isrc_release_year, primary_artist_key
from src.models import ResolvedTrack


def make_track(artist: str, title: str, score: float = 80, url: str | None = None, isrc: str = "") -> ResolvedTrack:
    return ResolvedTrack(
        rank=1,
        ranking_score=score,
        artist=artist,
        title=title,
        source_names=["test"],
        source_record={"artist": artist, "track_or_project_title": title, "open_graph": {"isrc": isrc}},
        soundcloud_url=url,
        soundcloud_track_id="1",
        spotify_uri="spotify:track:1",
    )


def make_unresolved_track(artist: str, title: str) -> ResolvedTrack:
    track = make_track(artist, title)
    track.soundcloud_url = None
    track.soundcloud_track_id = None
    track.spotify_uri = None
    track.spotify_id = None
    return track


def test_curation_keeps_max_two_per_primary_artist():
    tracks = [
        make_track("NOXIES", "Best One", 99),
        make_track("NOXIES", "Second One", 90),
        make_track("NOXIES", "Third One", 80),
        make_track("Other", "Song", 70),
    ]

    curated = curate_playlist_tracks(tracks, max_per_artist=2)

    assert [(track.artist, track.title) for track in curated] == [
        ("NOXIES", "Best One"),
        ("NOXIES", "Second One"),
        ("Other", "Song"),
    ]


def test_curation_skips_speed_variants():
    tracks = [
        make_track("AKhmedov", "Habibi - Super Slowed", 99),
        make_track("AKhmedov", "Habibi Sped Up", 98),
        make_track("Armand Van Helden", "I Want Your Soul - Avh Rework", 97),
        make_track("Test", "Old Song - 2024 Remaster", 96),
        make_track("Major Lazer", "Light It Up Cover", 95),
        make_track("AKhmedov", "Habibi", 90),
    ]

    curated = curate_playlist_tracks(tracks)

    assert [track.title for track in curated] == ["Habibi"]


def test_curation_allows_vip_versions():
    tracks = [
        make_track("Rivas", "Yes Indeed - VIP Edit", 99),
        make_track("Other", "Club Track - VIP Mix", 90),
    ]

    curated = curate_playlist_tracks(tracks)

    assert [track.title for track in curated] == ["Yes Indeed - VIP Edit", "Club Track - VIP Mix"]


def test_url_speed_variant_detection():
    track = make_track("NOXIES", "Garota Gostosa", url="https://soundcloud.com/noixes-scmusic/garota-gostosa-slowed")
    assert is_unwanted_speed_variant(track)


def test_source_url_cover_detection():
    track = make_track("Major Lazer", "Light It Up")
    track.source_record["source_article_url"] = "https://www.submithub.com/song/wildcrow-light-it-up-major-lazer-cover"
    assert is_unwanted_speed_variant(track)


def test_primary_artist_key_uses_first_collaborator():
    assert primary_artist_key("Chris Lorenzo, aMo (um)") == "chris lorenzo"


def test_isrc_release_year_parses_century_code():
    assert isrc_release_year("GBEFR2309157") == 2023
    assert isrc_release_year("USRC12600001") == 2026


def test_curation_skips_old_isrc_years():
    tracks = [
        make_track("Armand Van Helden", "Old Track", 99, isrc="GBEFR2309157"),
        make_track("Fresh Artist", "Fresh Track", 90, isrc="USRC12600001"),
    ]

    curated = curate_playlist_tracks(tracks, today=date(2026, 5, 4), lookback_days=7)

    assert [track.title for track in curated] == ["Fresh Track"]


def test_curation_skips_tracks_without_verified_platform_links():
    tracks = [
        make_unresolved_track("Major Lazer", "Light It Up"),
        make_track("Fresh Artist", "Fresh Track"),
    ]

    curated = curate_playlist_tracks(tracks)

    assert [track.title for track in curated] == ["Fresh Track"]
