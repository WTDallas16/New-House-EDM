from datetime import datetime, timedelta, timezone
import json
import requests

from src.scrapers.soundcloud_playlists import (
    ACCESS_VALUES,
    SoundCloudAPIClient,
    SoundCloudPlaylist,
    SoundCloudTokenManager,
    _artist_and_title,
    _candidate_from_track,
    _extract_sc_hydration,
    _playlist_from_api_data,
    _playlist_from_html,
    _playlist_url,
    _release_date,
    playlist_values_from_file,
)


def sample_track():
    return {
        "id": 123,
        "title": "Artist One - Warehouse Tune (Club Mix)",
        "permalink_url": "https://soundcloud.com/artist-one/warehouse-tune",
        "created_at": "2026/04/20 12:00:00 +0000",
        "release_date": "2026-04-24T00:00:00Z",
        "duration": 185000,
        "genre": "House",
        "tag_list": "house tech-house",
        "label_name": "Night Label",
        "playback_count": 1000,
        "likes_count": 77,
        "reposts_count": 5,
        "license": "all-rights-reserved",
        "publisher_metadata": {
            "artist": "Artist One",
            "release_title": "Warehouse Tune (Club Mix)",
            "isrc": "USABC2600001",
            "album_title": "Warehouse Tune",
            "publisher": "Night Label",
            "explicit": False,
        },
        "user": {"id": 456, "username": "Artist One", "permalink_url": "https://soundcloud.com/artist-one"},
    }


def test_playlist_url_accepts_full_url_and_path():
    assert _playlist_url("https://soundcloud.com/user/sets/house-finds") == "https://soundcloud.com/user/sets/house-finds"
    assert _playlist_url("soundcloud.com/user/sets/house-finds") == "https://soundcloud.com/user/sets/house-finds"
    assert _playlist_url("user/sets/house-finds") == "https://soundcloud.com/user/sets/house-finds"


def test_playlist_values_from_file_skips_comments(tmp_path):
    path = tmp_path / "playlists.txt"
    path.write_text("# comment\n\nhttps://soundcloud.com/user/sets/house-finds\n", encoding="utf-8")
    assert playlist_values_from_file(path) == ["https://soundcloud.com/user/sets/house-finds"]


def test_extract_sc_hydration_playlist():
    payload = [
        {
            "hydratable": "playlist",
            "data": {
                "id": 999,
                "kind": "playlist",
                "title": "House Finds",
                "permalink_url": "https://soundcloud.com/user/sets/house-finds",
                "track_count": 1,
                "likes_count": 10,
                "reposts_count": 2,
                "user": {"username": "Curator"},
                "tracks": [sample_track()],
            },
        }
    ]
    html = f"<script>window.__sc_hydration = {json.dumps(payload)};</script>"
    hydration = _extract_sc_hydration(html)
    assert hydration[0]["data"]["title"] == "House Finds"
    playlist = _playlist_from_html(html, fallback_url="https://soundcloud.com/user/sets/house-finds")
    assert playlist.title == "House Finds"
    assert playlist.owner == "Curator"
    assert playlist.tracks[0]["id"] == 123


def test_artist_and_title_prefers_publisher_metadata():
    assert _artist_and_title(sample_track()) == ("Artist One", "Warehouse Tune (Club Mix)")


def test_artist_and_title_parses_dash_title_without_metadata():
    track = {"title": "DJ Two - Late Night", "user": {"username": "Uploader"}}
    assert _artist_and_title(track) == ("DJ Two", "Late Night")


def test_release_date_prefers_release_date():
    assert _release_date(sample_track()) == "2026-04-24"
    assert _release_date({"created_at": "2026/04/20 12:00:00 +0000"}) == "2026-04-20"


def test_candidate_from_track_keeps_shared_schema():
    playlist = SoundCloudPlaylist(
        title="House Finds",
        url="https://soundcloud.com/user/sets/house-finds",
        owner="Curator",
        playlist_id="999",
        track_count="1",
        likes_count="10",
        reposts_count="2",
        tracks=[sample_track()],
    )
    candidate = _candidate_from_track(sample_track(), playlist)
    assert candidate is not None
    row = candidate.as_dict()
    assert row["artist"] == "Artist One"
    assert row["track_or_project_title"] == "Warehouse Tune (Club Mix)"
    assert row["release_type"] == "track"
    assert row["extraction_method"] == "soundcloud_playlist_page"
    assert row["source_article_url"] == "https://soundcloud.com/artist-one/warehouse-tune"
    assert row["article_date"] == "2026-04-24"
    assert row["embedded_music_links"] == ["https://soundcloud.com/artist-one/warehouse-tune"]
    assert row["open_graph"]["playlist_name"] == "House Finds"
    assert row["open_graph"]["isrc"] == "USABC2600001"


def test_api_playlist_marks_extraction_method():
    playlist = _playlist_from_api_data(
        {
            "id": 999,
            "kind": "playlist",
            "title": "House Finds",
            "permalink_url": "https://soundcloud.com/user/sets/house-finds",
            "user": {"username": "Curator"},
            "tracks": [sample_track()],
        },
        fallback_url="https://soundcloud.com/user/sets/house-finds",
    )
    candidate = _candidate_from_track(sample_track(), playlist)
    assert candidate is not None
    assert candidate.extraction_method == "soundcloud_playlist_api"


def test_token_manager_refreshes_and_saves_token(tmp_path, monkeypatch):
    token_file = tmp_path / "sc_token.json"
    token_file.write_text(
        json.dumps(
            {
                "access_token": "old-token",
                "refresh_token": "refresh-token",
                "expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SC_CLIENT_ID", "client-id")
    monkeypatch.setenv("SC_CLIENT_SECRET", "client-secret")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"access_token": "new-token", "expires_in": 3600}

    calls = {}

    def fake_post(url, data, timeout):
        calls["url"] = url
        calls["data"] = data
        calls["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("src.scrapers.soundcloud_playlists.requests.post", fake_post)

    manager = SoundCloudTokenManager(token_file=token_file)
    assert manager.get_valid_token() == "new-token"
    saved = json.loads(token_file.read_text(encoding="utf-8"))
    assert saved["access_token"] == "new-token"
    assert saved["refresh_token"] == "refresh-token"
    assert calls["data"]["grant_type"] == "refresh_token"
    assert calls["data"]["client_id"] == "client-id"


def test_api_client_uses_resolve_endpoint_headers_and_access_params(tmp_path, monkeypatch):
    monkeypatch.setenv("SC_CLIENT_ID", "client-id")
    monkeypatch.setenv("SC_ACCESS_TOKEN", "access-token")
    token_file = tmp_path / "missing-token.json"

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": 999,
                "kind": "playlist",
                "title": "House Finds",
                "permalink_url": "https://soundcloud.com/user/sets/house-finds",
                "user": {"username": "Curator"},
                "tracks": [sample_track()],
            }

    calls = []

    def fake_request(method, url, headers, params, timeout):
        calls.append({"method": method, "url": url, "headers": headers, "params": params, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("src.scrapers.soundcloud_playlists.requests.request", fake_request)

    client = SoundCloudAPIClient(token_file=token_file)
    playlist = client.resolve_playlist("https://soundcloud.com/user/sets/house-finds")
    assert playlist.title == "House Finds"
    assert calls[0]["url"] == "https://api.soundcloud.com/resolve"
    assert calls[0]["headers"]["Authorization"] == "Bearer access-token"
    assert "client_id" not in calls[0]["params"]
    assert calls[0]["params"]["access"] == ACCESS_VALUES
    assert calls[0]["params"]["url"] == "https://soundcloud.com/user/sets/house-finds"


def test_api_client_retries_without_oauth_after_401(tmp_path, monkeypatch):
    monkeypatch.setenv("SC_CLIENT_ID", "client-id")
    monkeypatch.setenv("SC_ACCESS_TOKEN", "bad-token")
    token_file = tmp_path / "missing-token.json"

    class FakeResponse:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(f"{self.status_code} error", response=self)

        def json(self):
            return self._payload

    calls = []

    def fake_request(method, url, headers, params, timeout):
        calls.append({"headers": headers, "params": params})
        if len(calls) == 1:
            return FakeResponse(401, text='{"error":"invalid_token"}')
        return FakeResponse(
            200,
            {
                "id": 999,
                "kind": "playlist",
                "title": "House Finds",
                "permalink_url": "https://soundcloud.com/user/sets/house-finds",
                "user": {"username": "Curator"},
                "tracks": [sample_track()],
            },
        )

    monkeypatch.setattr("src.scrapers.soundcloud_playlists.requests.request", fake_request)

    client = SoundCloudAPIClient(token_file=token_file)
    playlist = client.resolve_playlist("https://soundcloud.com/user/sets/house-finds")
    assert playlist.title == "House Finds"
    assert calls[0]["headers"]["Authorization"] == "Bearer bad-token"
    assert "Authorization" not in calls[1]["headers"]
    assert calls[1]["params"]["client_id"] == "client-id"


def test_api_client_error_includes_response_body(tmp_path, monkeypatch):
    monkeypatch.setenv("SC_CLIENT_ID", "client-id")
    token_file = tmp_path / "missing-token.json"

    class FakeResponse:
        status_code = 403
        text = '{"error":"not_allowed"}'

        def raise_for_status(self):
            raise requests.HTTPError("403 error", response=self)

    def fake_request(method, url, headers, params, timeout):
        return FakeResponse()

    monkeypatch.setattr("src.scrapers.soundcloud_playlists.requests.request", fake_request)

    client = SoundCloudAPIClient(token_file=token_file)
    try:
        client.get("/resolve", url="https://soundcloud.com/user/sets/house-finds")
    except requests.HTTPError as exc:
        assert "not_allowed" in str(exc)
    else:
        raise AssertionError("Expected HTTPError")
