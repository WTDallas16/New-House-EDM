from datetime import date

from src.ranker import SOURCE_WEIGHTS, calculate_score, duplicate_key, rank_records, unique_records, LoadedRecord


def test_duplicate_key_prefers_spotify_track_id():
    item = {
        "artist": "Chris Lake",
        "track_or_project_title": "Make You Fight",
        "open_graph": {"spotify_track_id": "abc123"},
    }
    assert duplicate_key(item) == "spotify:abc123"


def test_duplicate_key_falls_back_to_normalized_artist_title():
    item = {"artist": "Chris Lake & ATRIP", "track_or_project_title": "Make You Fight - Extended Mix", "open_graph": {}}
    assert duplicate_key(item) == "text:chris lake and atrip|make you fight"


def test_duplicate_sources_raise_score():
    base_item = {
        "artist": "Chris Lake",
        "track_or_project_title": "Make You Fight",
        "confidence_score": 1.0,
        "source_name": "Spotify Playlist",
        "article_date": "2026-05-01",
        "embedded_music_links": ["https://open.spotify.com/track/abc"],
        "open_graph": {"spotify_track_id": "abc", "spotify_popularity": "40"},
        "release_article": True,
    }
    single_context = {"duplicate_count": 1, "sources": ["Spotify Playlist"]}
    multi_context = {"duplicate_count": 3, "sources": ["Spotify Playlist", "SoundCloud Playlist", "Spotify Artist Profile"]}
    single_score, _ = calculate_score(base_item, single_context, today=date(2026, 5, 3))
    multi_score, factors = calculate_score(base_item, multi_context, today=date(2026, 5, 3))
    assert multi_score > single_score
    assert factors["components"]["cross_source_duplicates"] > 0


def test_rank_records_and_unique_records():
    spotify = {
        "artist": "Chris Lake",
        "track_or_project_title": "Make You Fight",
        "confidence_score": 1.0,
        "source_name": "Spotify Playlist",
        "article_date": "2026-05-01",
        "embedded_music_links": ["https://open.spotify.com/track/abc"],
        "open_graph": {"spotify_track_id": "abc", "spotify_popularity": "20"},
        "release_article": True,
    }
    soundcloud = {
        "artist": "Chris Lake",
        "track_or_project_title": "Make You Fight",
        "confidence_score": 0.8,
        "source_name": "SoundCloud Playlist",
        "article_date": "2026-04-30",
        "embedded_music_links": ["https://soundcloud.com/chrislake/make-you-fight"],
        "open_graph": {"spotify_track_id": "abc", "playback_count": "1000"},
        "release_article": True,
    }
    ranked = rank_records(
        [
            LoadedRecord(spotify, "spotify.json", "spotify:abc"),
            LoadedRecord(soundcloud, "soundcloud.json", "spotify:abc"),
        ],
        today=date(2026, 5, 3),
    )
    assert len(ranked) == 2
    assert ranked[0]["cross_source_duplicate_count"] == 2
    assert ranked[0]["cross_source_sources"] == ["SoundCloud Playlist", "Spotify Playlist"]
    assert len(unique_records(ranked)) == 1


def test_rank_records_connects_platform_id_to_text_alias():
    spotify = {
        "artist": "Chris Lake",
        "track_or_project_title": "Make You Fight",
        "confidence_score": 1.0,
        "source_name": "Spotify Playlist",
        "article_date": "2026-05-01",
        "embedded_music_links": ["https://open.spotify.com/track/abc"],
        "open_graph": {"spotify_track_id": "abc"},
        "release_article": True,
    }
    blog = {
        "artist": "Chris Lake",
        "track_or_project_title": "Make You Fight",
        "confidence_score": 0.8,
        "source_name": "EDM.com",
        "article_date": "2026-05-01",
        "embedded_music_links": [],
        "open_graph": {},
        "release_article": True,
    }
    ranked = rank_records(
        [
            LoadedRecord(spotify, "spotify.json", "spotify:abc"),
            LoadedRecord(blog, "blog.json", "text:chris lake|make you fight"),
        ],
        today=date(2026, 5, 3),
    )
    assert {item["cross_source_duplicate_count"] for item in ranked} == {2}
    assert {item["duplicate_group_key"] for item in ranked} == {"spotify:abc"}


def test_1001tracklists_scores_above_editorial_blog_with_same_signals():
    base = {
        "artist": "Chris Lorenzo",
        "track_or_project_title": "HOTS 4 U",
        "confidence_score": 0.8,
        "article_date": "2026-05-01",
        "embedded_music_links": [],
        "open_graph": {"chart_rank": "3"},
        "release_article": True,
    }
    context = {"duplicate_count": 1, "sources": ["1001Tracklists"]}
    tracklists_score, tracklists_factors = calculate_score(
        {**base, "source_name": "1001Tracklists"},
        context,
        today=date(2026, 5, 3),
    )
    blog_score, _ = calculate_score(
        {**base, "source_name": "EDM.com"},
        {"duplicate_count": 1, "sources": ["EDM.com"]},
        today=date(2026, 5, 3),
    )

    assert SOURCE_WEIGHTS["1001Tracklists"] > SOURCE_WEIGHTS["EDM.com"]
    assert tracklists_factors["components"]["source_chart"] > 0
    assert tracklists_score > blog_score
