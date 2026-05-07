from weraveyou.src.extraction.classifier import classify_article, is_release_article


def test_release_article_detection_for_listen_single():
    title = "HIFEELINGS and Dyzzy deliver emotionally driven single ‘FRIENDS?’: Listen"
    result = classify_article(title)
    assert result.release_article is True
    assert result.confidence_score >= 0.6


def test_excludes_anniversary_classic_article():
    title = "Ultra Naté’s house classic ‘Free’ has turned 29 years old"
    assert is_release_article(title) is False


def test_excludes_festival_lineup_article():
    title = "Tomorrowland announces 2026 festival lineup with house legends"
    assert is_release_article(title) is False


def test_announces_allowed_when_release_is_unveiled():
    title = "Roger Sanchez announces first studio album in 20 years, unveils ‘Temptation’ with Low Steppa: Listen"
    result = classify_article(title)
    assert result.release_article is True
    assert "announces" in result.exclusion_signals

