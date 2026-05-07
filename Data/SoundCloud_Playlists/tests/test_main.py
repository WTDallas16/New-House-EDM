from datetime import date

from src.main import filter_by_article_date, parse_article_date
from src.models import ReleaseCandidate


def candidate(article_date):
    return ReleaseCandidate(
        artist="Artist",
        track_or_project_title=f"Track {article_date}",
        release_type="track",
        confidence_score=1.0,
        extraction_method="test",
        source_article_title="Artist - Track",
        source_article_url="https://soundcloud.com/artist/track",
        source_name="SoundCloud Playlist",
        article_date=article_date,
    )


def test_parse_article_date_accepts_iso_date_prefix():
    assert parse_article_date("2026-04-24") == date(2026, 4, 24)
    assert parse_article_date("2026-04-24T00:00:00Z") == date(2026, 4, 24)
    assert parse_article_date(None) is None
    assert parse_article_date("not-a-date") is None


def test_filter_by_article_date_keeps_last_two_weeks():
    rows = [
        candidate("2026-05-01"),
        candidate("2026-04-17"),
        candidate("2026-04-16"),
        candidate(None),
    ]

    filtered = filter_by_article_date(rows, lookback_days=14, today=date(2026, 5, 1))

    assert [row.article_date for row in filtered] == ["2026-05-01", "2026-04-17"]


def test_filter_by_article_date_can_be_disabled():
    rows = [candidate("2026-04-01"), candidate(None)]
    assert filter_by_article_date(rows, lookback_days=0, today=date(2026, 5, 1)) == rows
