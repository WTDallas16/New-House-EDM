from datetime import date

from src.followed_artists import FollowedArtist
from src.recent_tracks import candidate_from_track, track_looks_like_release, track_release_date


def test_track_release_date():
    assert track_release_date({"release_date": "2026-05-01T00:00:00Z"}) == date(2026, 5, 1)
    assert track_release_date({"created_at": "2026/05/01 10:00:00 +0000"}) == date(2026, 5, 1)


def test_track_looks_like_release_filters_long_sets():
    assert not track_looks_like_release({"title": "Artist live @ Festival", "duration": 3_600_000})
    assert track_looks_like_release({"title": "Artist - New Track", "duration": 180_000})
    assert track_looks_like_release({"title": "Artist live @ Festival", "duration": 3_600_000, "publisher_metadata": {"isrc": "US123"}})


def test_candidate_from_track_shared_schema():
    artist = FollowedArtist(
        artist_name="Artist",
        soundcloud_url="https://soundcloud.com/artist",
        soundcloud_user_id="123",
        genres=["House"],
        edm_match_terms=["house"],
        followers_count=1000,
    )
    track = {
        "id": 456,
        "title": "Artist - New Track",
        "permalink_url": "https://soundcloud.com/artist/new-track",
        "duration": 180000,
        "playback_count": 100,
        "likes_count": 10,
        "user": {"username": "Artist"},
        "publisher_metadata": {"artist": "Artist", "release_title": "New Track", "isrc": "US123"},
    }
    candidate = candidate_from_track(artist, track, date(2026, 5, 1), 14, date(2026, 5, 3))
    data = candidate.as_dict()
    assert data["artist"] == "Artist"
    assert data["track_or_project_title"] == "New Track"
    assert data["source_name"] == "SoundCloud Followed Artist"
    assert data["open_graph"]["soundcloud_track_id"] == "456"
