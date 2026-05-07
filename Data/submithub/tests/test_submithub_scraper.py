from src.scrapers.submithub import (
    ChartSummary,
    _chart_summaries,
    _date_from_ejson,
    _genre_from_url,
    _clean_track_title,
    _popular_query,
    _release_candidates_from_chart,
    _subgenres_for_parent,
)


def test_genre_from_url_decodes_house_techno():
    assert _genre_from_url("https://www.submithub.com/popular?genre=House%20%2F%20Techno") == "House / Techno"


def test_subgenres_for_parent_returns_child_genres():
    genres = [
        {"name": "Deep House", "parent": "House / Techno"},
        {"name": "Indie Pop", "parent": "Pop"},
    ]
    assert _subgenres_for_parent(genres, "House / Techno") == ["Deep House"]


def test_popular_query_filters_by_subgenres_and_recent_week():
    query = _popular_query(["Deep House", "Tech House"])
    assert query["top_3"] == {"$in": ["Deep House", "Tech House"]}
    assert query["hidden"] == {"$ne": True}
    assert "$or" in query


def test_chart_summaries_extract_points_likes_and_tags():
    summaries = _chart_summaries(
        [
            {
                "_id": "abc",
                "tracks": ["abc"],
                "points": 72,
                "approved": 91,
                "rgb": 3,
                "complete": 143,
                "country": "GB",
                "tags": [["Tribal / Afro House", "Melodic House"]],
            }
        ]
    )
    assert summaries == [
        ChartSummary(
            track_id="abc",
            points=72.0,
            approved=91,
            rgb=3,
            complete=143,
            country="GB",
            tags=["Tribal / Afro House", "Melodic House"],
        )
    ]


def test_date_from_ejson():
    assert _date_from_ejson({"$date": 1776988800000}) == "2026-04-23"


def test_clean_track_title_strips_outer_quotes():
    assert _clean_track_title('"Iraya"') == "Iraya"


def test_release_candidates_keep_shared_schema_and_chart_metadata():
    summaries = [
        ChartSummary(
            track_id="abc",
            points=72,
            approved=91,
            rgb=3,
            complete=143,
            country="GB",
            tags=["Tribal / Afro House", "Melodic House"],
        )
    ]
    tracks = [
        {
            "_id": "abc",
            "artist": "Dr. Chaii",
            "title": "Designer",
            "released": {"$date": 1776988800000},
            "slug": "dr-chaii-designer-1",
            "label": "Soundtuary Music",
            "source": [{"url": "https://open.spotify.com/track/7GYjO2zack2FIFvVkFOfdL"}],
            "unoriginal": [],
        }
    ]
    candidate = _release_candidates_from_chart(summaries, tracks)[0]
    row = candidate.as_dict()
    assert row["artist"] == "Dr. Chaii"
    assert row["track_or_project_title"] == "Designer"
    assert row["release_type"] == "track"
    assert row["extraction_method"] == "submithub_chart"
    assert row["source_article_url"] == "https://www.submithub.com/song/dr-chaii-designer-1"
    assert row["article_date"] == "2026-04-23"
    assert row["embedded_music_links"] == ["https://open.spotify.com/track/7GYjO2zack2FIFvVkFOfdL"]
    assert row["open_graph"]["popular_points"] == "72"
    assert row["open_graph"]["hot_or_not_likes"] == "91"


def test_release_candidates_skip_future_release_dates():
    summaries = [
        ChartSummary(
            track_id="abc",
            points=72,
            approved=91,
            rgb=3,
            complete=143,
            country="GB",
            tags=["Deep House"],
        )
    ]
    tracks = [{"_id": "abc", "artist": "Future Artist", "title": "Tomorrow", "released": {"$date": 4102444800000}}]
    assert _release_candidates_from_chart(summaries, tracks) == []
