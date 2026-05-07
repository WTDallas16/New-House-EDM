from src.soundcloud_tools import (
    artist_aliases,
    best_soundcloud_match,
    playlist_tracks_form,
    soundcloud_url_from_record,
    soundcloud_track_date,
)
from datetime import date


def test_soundcloud_url_from_record():
    item = {"source_article_url": "https://soundcloud.com/artist-name/track-name?utm_source=test"}
    assert soundcloud_url_from_record(item) == "https://soundcloud.com/artist-name/track-name"


def test_best_soundcloud_match_prefers_title_and_artist():
    tracks = [
        {"id": 1, "title": "Nope", "user": {"username": "Other"}, "playback_count": 999999},
        {"id": 2, "title": "Artist - Track", "user": {"username": "Artist"}, "playback_count": 1},
    ]
    assert best_soundcloud_match("Artist", "Artist - Track", tracks)["id"] == 2


def test_best_soundcloud_match_handles_collaboration_artist_strings():
    tracks = [
        {"id": 10, "title": "Sidewinder", "user": {"username": "Jax Jones"}, "playback_count": 1},
    ]

    assert best_soundcloud_match("Jax Jones, D Double E", "Sidewinder", tracks)["id"] == 10


def test_artist_aliases_splits_features_and_parentheses():
    assert "Chris Lorenzo" in artist_aliases("Chris Lorenzo, aMo (um)")


def test_best_soundcloud_match_rejects_same_title_wrong_artist():
    tracks = [
        {"id": 20, "title": "Till The End", "user": {"username": "Logic"}, "playback_count": 999999},
    ]

    assert best_soundcloud_match("Daecolm", "Till the end", tracks) is None


def test_best_soundcloud_match_rejects_popular_wrong_upload():
    tracks = [
        {"id": 30, "title": "Club Muzik", "user": {"username": "chxrli333"}, "playback_count": 999999},
    ]

    assert best_soundcloud_match("Sam Divine", "Club Muzik", tracks) is None


def test_best_soundcloud_match_rejects_common_split_artist_name():
    tracks = [
        {"id": 40, "title": "You Gave Me Love", "user": {"username": "Crown Heights Affair"}, "playback_count": 999999, "created_at": "2017-09-25T00:00:00Z"},
    ]

    assert best_soundcloud_match("Block & Crown, Larrice", "You Gave Me Love", tracks, today=date(2026, 5, 4)) is None


def test_best_soundcloud_match_rejects_old_track_date():
    tracks = [
        {"id": 50, "title": "Light It Up", "user": {"username": "Major Lazer"}, "playback_count": 999999, "created_at": "2016-06-01T00:00:00Z"},
    ]

    assert best_soundcloud_match("Major Lazer", "Light It Up", tracks, today=date(2026, 5, 4), lookback_days=7) is None


def test_soundcloud_track_date_prefers_structured_release_fields():
    track = {
        "created_at": "2026/04/10 19:09:53 +0000",
        "release_year": 2026,
        "release_month": 4,
        "release_day": 30,
    }

    assert soundcloud_track_date(track) == date(2026, 4, 30)


def test_playlist_tracks_form_uses_soundcloud_nested_params():
    assert playlist_tracks_form(["123", "abc", "456", "123"]) == [
        ("playlist[tracks][][id]", "123"),
        ("playlist[tracks][][id]", "456"),
    ]
