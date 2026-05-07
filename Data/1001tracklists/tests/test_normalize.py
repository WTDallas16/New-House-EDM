from src.extraction.normalize import dedupe_releases
from src.models import ReleaseCandidate


def _candidate(score: float) -> ReleaseCandidate:
    return ReleaseCandidate(
        artist="New Wing",
        track_or_project_title="Sippin",
        release_type="single",
        confidence_score=score,
        extraction_method="regex",
        source_article_title="New Wing unveils captivating new single ‘Sippin’: Listen",
        source_article_url=f"https://example.com/{score}",
        source_name="We Rave You",
    )


def test_dedupe_keeps_highest_confidence_candidate():
    low = _candidate(0.5)
    high = _candidate(0.9)
    deduped = dedupe_releases([low, high])
    assert len(deduped) == 1
    assert deduped[0].confidence_score == 0.9

