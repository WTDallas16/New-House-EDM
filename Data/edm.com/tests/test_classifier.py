from src.extraction.classifier import classify_article, is_release_article


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


def test_announce_only_album_article_is_excluded():
    title = "Thomas Bangalter Announces New Album: ‘Mirage – Ballet For 16 Dancers’"
    result = classify_article(title)
    assert result.release_article is False
    assert result.confidence_score <= 0.25


def test_watch_video_article_is_excluded_even_with_release_words():
    title = "[WATCH] Le Youth Shares Intimate Release Pop Up Video For “who are you really?”"
    assert classify_article(title).release_article is False


def test_edmcom_roundup_articles_are_excluded():
    assert is_release_article("EDM.com Fresh Picks: DJ Susan, Discip, jigitz & More") is False
    assert is_release_article("EDM.com On-Deck Circle: Baauer, Armin van Buuren x Argy, The Glitch Mob & More") is False


def test_edmcom_next_single_preview_is_excluded():
    assert is_release_article("Kygo’s Next Single Is a Tribute to Avicii, Features the Voice Behind ‘Hey Brother’") is False
