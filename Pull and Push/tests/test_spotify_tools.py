from datetime import date

from spotipy.exceptions import SpotifyException

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


def test_find_or_create_playlist_uses_known_id_without_name_lookup():
    class FakeClient:
        def playlist(self, playlist_id, fields=None):
            return {"id": playlist_id}

        def current_user(self):
            raise AssertionError("should not need to look up the current user when the known id is valid")

        def current_user_playlists(self, limit=50):
            raise AssertionError("should not search playlists by name when the known id is valid")

    tool = SpotifyTools.__new__(SpotifyTools)
    tool.client = FakeClient()

    playlist_id = tool.find_or_create_playlist("New House Fridays", known_playlist_id="known-id")

    assert playlist_id == "known-id"


def test_find_or_create_playlist_falls_back_to_name_when_known_id_invalid():
    class FakeClient:
        def playlist(self, playlist_id, fields=None):
            raise SpotifyException(404, -1, "Not Found")

        def current_user(self):
            return {"id": "user-1"}

        def current_user_playlists(self, limit=50):
            return {"items": [{"id": "matched-id", "name": "New House Fridays"}], "next": None}

        def next(self, page):
            return None

    tool = SpotifyTools.__new__(SpotifyTools)
    tool.client = FakeClient()

    playlist_id = tool.find_or_create_playlist("New House Fridays", known_playlist_id="stale-id")

    assert playlist_id == "matched-id"


def test_find_or_create_playlist_creates_when_name_not_found():
    created = {}

    class FakeClient:
        def current_user(self):
            return {"id": "user-1"}

        def current_user_playlists(self, limit=50):
            return {"items": [], "next": None}

        def next(self, page):
            return None

        def user_playlist_create(self, user, name, public, description):
            created.update(user=user, name=name, public=public, description=description)
            return {"id": "new-id"}

    tool = SpotifyTools.__new__(SpotifyTools)
    tool.client = FakeClient()

    playlist_id = tool.find_or_create_playlist("New House Fridays")

    assert playlist_id == "new-id"
    assert created["name"] == "New House Fridays"
