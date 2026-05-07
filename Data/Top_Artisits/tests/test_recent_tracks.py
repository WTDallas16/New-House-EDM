from datetime import date

from src.recent_tracks import (
    ArtistProfile,
    build_release_candidate,
    build_soundcloud_candidate,
    calculate_ranking,
    load_artist_profiles,
    parse_spotify_release_date,
    release_type_from_album,
    soundcloud_release_date,
    soundcloud_track_looks_like_release,
    spotify_artist_id_from_url,
)


def test_spotify_artist_id_from_url():
    assert spotify_artist_id_from_url("https://open.spotify.com/artist/6nS5roXSAGhTGr34W6n7Et?si=abc") == "6nS5roXSAGhTGr34W6n7Et"
    assert spotify_artist_id_from_url("spotify:artist:6nS5roXSAGhTGr34W6n7Et") == "6nS5roXSAGhTGr34W6n7Et"


def test_parse_spotify_release_date_requires_day_precision():
    assert parse_spotify_release_date("2026-05-01", "day") == date(2026, 5, 1)
    assert parse_spotify_release_date("2026-05", "month") is None


def test_release_type_from_album():
    assert release_type_from_album({"album_type": "single", "total_tracks": 1}, "HOTS 4 U") == "single"
    assert release_type_from_album({"album_type": "single", "total_tracks": 5}, "Club Pack") == "EP"
    assert release_type_from_album({"album_type": "album", "total_tracks": 10}, "Opus") == "album"
    assert release_type_from_album({"album_type": "single", "total_tracks": 1}, "HOTS 4 U - Remix") == "remix"


def test_build_release_candidate_matches_shared_shape():
    profile = ArtistProfile(
        artist_name="Disclosure",
        spotify_url="https://open.spotify.com/artist/abc",
        genre="house",
        rank="1",
        monthly_listeners="1000",
    )
    album = {
        "id": "album1",
        "name": "New Single",
        "album_type": "single",
        "total_tracks": 1,
        "release_date_precision": "day",
        "external_urls": {"spotify": "https://open.spotify.com/album/album1"},
    }
    track = {
        "id": "track1",
        "name": "New Single",
        "artists": [{"id": "abc", "name": "Disclosure"}],
        "external_urls": {"spotify": "https://open.spotify.com/track/track1"},
        "duration_ms": 180000,
        "explicit": False,
        "track_number": 1,
        "disc_number": 1,
    }
    candidate = build_release_candidate(
        profile,
        "abc",
        album,
        track,
        date(2026, 5, 1),
        artist_stats={"popularity": 80, "followers": {"total": 500000}, "genres": ["house"]},
        track_stats={"popularity": 50, "external_ids": {"isrc": "US123"}},
        today=date(2026, 5, 1),
    ).as_dict()
    assert candidate["artist"] == "Disclosure"
    assert candidate["track_or_project_title"] == "New Single"
    assert candidate["release_type"] == "single"
    assert candidate["article_date"] == "2026-05-01"
    assert candidate["ranking_score"] > 0
    assert candidate["ranking_factors"]["raw"]["spotify_track_popularity"] == 50
    assert candidate["release_article"] is True
    assert candidate["open_graph"]["source_artist_genres"] == "house"
    assert candidate["open_graph"]["source_artist_spotify_popularity"] == "80"
    assert candidate["open_graph"]["isrc"] == "US123"


def test_calculate_ranking_rewards_stronger_signals():
    profile_low = ArtistProfile("Small Artist", "https://open.spotify.com/artist/low", rank="400", monthly_listeners="1000")
    profile_high = ArtistProfile("Big Artist", "https://open.spotify.com/artist/high", rank="1", monthly_listeners="10000000")
    low_score, _ = calculate_ranking(
        profile_low,
        date(2026, 4, 20),
        artist_stats={"popularity": 20, "followers": {"total": 1000}},
        track_stats={"popularity": 5},
        lookback_days=14,
        today=date(2026, 5, 1),
    )
    high_score, factors = calculate_ranking(
        profile_high,
        date(2026, 5, 1),
        artist_stats={"popularity": 90, "followers": {"total": 5000000}},
        track_stats={"popularity": 80},
        lookback_days=14,
        today=date(2026, 5, 1),
    )
    assert high_score > low_score
    assert factors["components"]["recency"] == 1.0


def test_load_artist_profiles_reads_soundcloud_columns(tmp_path):
    csv_path = tmp_path / "artists.csv"
    csv_path.write_text(
        "artist_name,spotify_url,soundcloud_url,soundcloud_user_id,genre,rank,monthly_listeners\n"
        "Disclosure,,https://soundcloud.com/disclosure,123,house,1,1000\n",
        encoding="utf-8",
    )
    profiles = load_artist_profiles(csv_path)
    assert len(profiles) == 1
    assert profiles[0].soundcloud_url == "https://soundcloud.com/disclosure"
    assert profiles[0].soundcloud_user_id == "123"


def test_soundcloud_release_date_and_candidate_shape():
    profile = ArtistProfile(
        artist_name="Disclosure",
        spotify_url="",
        soundcloud_url="https://soundcloud.com/disclosure",
        soundcloud_user_id="123",
        genre="house",
        rank="1",
        monthly_listeners="1000",
    )
    track = {
        "id": 456,
        "title": "Disclosure - New One",
        "permalink_url": "https://soundcloud.com/disclosure/new-one",
        "release_date": "2026-05-01T00:00:00Z",
        "duration": 180000,
        "user": {"id": 123, "username": "Disclosure"},
        "publisher_metadata": {"artist": "Disclosure", "release_title": "New One", "isrc": "US123"},
    }
    release_date = soundcloud_release_date(track)
    assert release_date == date(2026, 5, 1)
    candidate = build_soundcloud_candidate(profile, track, "123", profile.soundcloud_url, release_date, 14, date(2026, 5, 3))
    assert candidate is not None
    data = candidate.as_dict()
    assert data["source_name"] == "SoundCloud Artist Profile"
    assert data["track_or_project_title"] == "New One"
    assert data["open_graph"]["soundcloud_track_id"] == "456"


def test_soundcloud_track_looks_like_release_filters_sets():
    assert not soundcloud_track_looks_like_release({"title": "Artist live @ Festival", "duration": 3_600_000})
    assert soundcloud_track_looks_like_release({"title": "Artist - New Track", "duration": 180_000})
    assert soundcloud_track_looks_like_release(
        {
            "title": "Artist live @ Festival",
            "duration": 3_600_000,
            "publisher_metadata": {"isrc": "US123"},
        }
    )
