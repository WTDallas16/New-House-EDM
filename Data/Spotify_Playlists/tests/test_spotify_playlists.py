from src.scrapers.spotify_playlists import (
    _candidate_from_playlist_item,
    _playlist_id_from_value,
    _release_type,
    _spotify_error_summary,
    playlist_values_from_file,
)
from spotipy.exceptions import SpotifyException


def test_playlist_id_from_url_uri_and_raw_id():
    assert _playlist_id_from_value("https://open.spotify.com/playlist/37i9dQZF1DXa8NOEUWPn9W?si=abc") == "37i9dQZF1DXa8NOEUWPn9W"
    assert _playlist_id_from_value("spotify:playlist:37i9dQZF1DXa8NOEUWPn9W") == "37i9dQZF1DXa8NOEUWPn9W"
    assert _playlist_id_from_value("37i9dQZF1DXa8NOEUWPn9W") == "37i9dQZF1DXa8NOEUWPn9W"


def test_playlist_values_from_file_skips_comments(tmp_path):
    path = tmp_path / "playlists.txt"
    path.write_text("# comment\n\nspotify:playlist:abc1234567890123\n", encoding="utf-8")
    assert playlist_values_from_file(path) == ["spotify:playlist:abc1234567890123"]


def test_release_type_from_album_metadata():
    assert _release_type({"album_type": "single", "total_tracks": 1}) == "single"
    assert _release_type({"album_type": "single", "total_tracks": 5}) == "EP"
    assert _release_type({"album_type": "album", "total_tracks": 12}) == "album"
    assert _release_type({"album_type": "album", "total_tracks": 4}) == "EP"


def test_candidate_from_playlist_item_keeps_shared_schema():
    item = {
        "added_at": "2026-04-30T10:00:00Z",
        "added_by": {"id": "user123"},
        "track": {
            "id": "track123",
            "name": "House Tune",
            "type": "track",
            "is_local": False,
            "explicit": False,
            "popularity": 71,
            "duration_ms": 180000,
            "preview_url": "https://p.scdn.co/mp3-preview/example",
            "track_number": 1,
            "disc_number": 1,
            "external_ids": {"isrc": "USABC2600001"},
            "external_urls": {"spotify": "https://open.spotify.com/track/track123"},
            "artists": [
                {"id": "artist123", "name": "Artist One", "external_urls": {"spotify": "https://open.spotify.com/artist/artist123"}},
                {"id": "artist456", "name": "Artist Two", "external_urls": {"spotify": "https://open.spotify.com/artist/artist456"}},
            ],
            "album": {
                "id": "album123",
                "name": "House Tune",
                "album_type": "single",
                "total_tracks": 1,
                "release_date": "2026-04-24",
                "release_date_precision": "day",
                "external_urls": {"spotify": "https://open.spotify.com/album/album123"},
            },
        },
    }
    playlist_meta = {
        "playlist_id": "playlist123",
        "playlist_name": "House Finds",
        "playlist_owner": "Willy",
        "playlist_url": "https://open.spotify.com/playlist/playlist123",
    }

    candidate = _candidate_from_playlist_item(item, playlist_meta)
    assert candidate is not None
    row = candidate.as_dict()
    assert row["artist"] == "Artist One"
    assert row["track_or_project_title"] == "House Tune"
    assert row["release_type"] == "single"
    assert row["extraction_method"] == "spotify_playlist_api"
    assert row["source_article_url"] == "https://open.spotify.com/track/track123"
    assert row["article_date"] == "2026-04-24"
    assert row["embedded_music_links"] == ["https://open.spotify.com/track/track123"]
    assert row["open_graph"]["playlist_name"] == "House Finds"
    assert row["open_graph"]["all_artists"] == "Artist One, Artist Two"
    assert row["open_graph"]["isrc"] == "USABC2600001"


def test_candidate_skips_local_and_non_track_items():
    assert _candidate_from_playlist_item({"track": {"type": "episode", "is_local": False}}, {}) is None
    assert _candidate_from_playlist_item({"track": {"type": "track", "is_local": True}}, {}) is None


def test_spotify_error_summary_includes_status_and_reason():
    exc = SpotifyException(404, -1, "Resource not found", reason="None")
    assert _spotify_error_summary(exc) == "HTTP 404: Resource not found (None)"
