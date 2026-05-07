from datetime import date

from src.spotify_tools import SpotifyTools, best_spotify_match, spotify_track_id_from_record


def test_spotify_track_id_from_record_embedded_link():
    item = {"embedded_music_links": ["https://open.spotify.com/track/123abcDEF456"]}
    assert spotify_track_id_from_record(item) == "123abcDEF456"


def test_best_spotify_match_prefers_title_and_artist():
    tracks = [
        {"id": "1", "name": "Other", "artists": [{"name": "Someone"}], "popularity": 99, "album": {"release_date": "2026-05-04", "release_date_precision": "day"}},
        {"id": "2", "name": "New House Song", "artists": [{"name": "Test Artist"}], "popularity": 1, "album": {"release_date": "2026-05-04", "release_date_precision": "day"}},
    ]
    assert best_spotify_match("Test Artist", "New House Song", tracks, today=date(2026, 5, 4))["id"] == "2"


def test_best_spotify_match_rejects_short_title_substring_wrong_artist():
    tracks = [
        {"id": "old", "name": "Talking Body", "artists": [{"name": "Tove Lo"}], "popularity": 80, "album": {"release_date": "2015-01-01", "release_date_precision": "day"}},
    ]

    assert best_spotify_match("LO", "Talk", tracks, today=date(2026, 5, 4)) is None


def test_best_spotify_match_rejects_old_release_date():
    tracks = [
        {"id": "old", "name": "Light It Up", "artists": [{"name": "Major Lazer"}], "popularity": 80, "album": {"release_date": "2015-01-01", "release_date_precision": "day"}},
    ]

    assert best_spotify_match("Major Lazer", "Light It Up", tracks, today=date(2026, 5, 4), lookback_days=7) is None


def test_best_spotify_match_rejects_imprecise_release_date():
    tracks = [
        {"id": "unknown", "name": "New House Song", "artists": [{"name": "Test Artist"}], "popularity": 80, "album": {"release_date": "2026", "release_date_precision": "year"}},
    ]

    assert best_spotify_match("Test Artist", "New House Song", tracks, today=date(2026, 5, 4), lookback_days=7) is None


def test_direct_spotify_track_id_is_date_checked():
    class FakeClient:
        def track(self, track_id, market=None):
            return {
                "id": track_id,
                "name": "Light It Up",
                "artists": [{"name": "Major Lazer"}],
                "popularity": 80,
                "external_urls": {"spotify": f"https://open.spotify.com/track/{track_id}"},
                "album": {"release_date": "2015-01-01", "release_date_precision": "day"},
            }

    tool = SpotifyTools.__new__(SpotifyTools)
    tool.client = FakeClient()

    result = tool.resolve_direct_track_id(
        "old",
        {"artist": "Major Lazer", "track_or_project_title": "Light It Up"},
        today=date(2026, 5, 4),
        lookback_days=7,
    )

    assert result == {"spotify_id": None, "spotify_uri": None, "spotify_url": None}
