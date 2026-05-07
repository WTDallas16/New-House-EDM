from datetime import date

from src.ranking_bridge import filter_records_by_lookback


def test_filter_records_by_lookback_keeps_only_recent_dates():
    records = [
        {"article_date": "2026-05-04", "track_or_project_title": "today"},
        {"article_date": "2026-04-27", "track_or_project_title": "seven-days"},
        {"article_date": "2026-04-26", "track_or_project_title": "old"},
        {"article_date": None, "track_or_project_title": "unknown"},
    ]

    filtered = filter_records_by_lookback(records, 7, today=date(2026, 5, 4))

    assert [record["track_or_project_title"] for record in filtered] == ["today", "seven-days"]

