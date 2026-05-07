from weraveyou.src.extraction.parser import extract_from_title, infer_release_type
from weraveyou.src.models import ArticleCard, ArticleEnrichment
from weraveyou.src.extraction.parser import parse_release_candidate


def test_extract_artist_and_title_from_deliver_single():
    parsed = extract_from_title("HIFEELINGS and Dyzzy deliver emotionally driven single ‘FRIENDS?’: Listen")
    assert parsed == ("HIFEELINGS and Dyzzy", "FRIENDS?", "regex")


def test_extract_artist_and_title_from_unveils_single():
    parsed = extract_from_title("New Wing unveils captivating new single ‘Sippin’: Listen")
    assert parsed == ("New Wing", "Sippin", "regex")


def test_extract_artist_and_title_from_continues_album_push():
    parsed = extract_from_title("John Summit continues album push with new single ‘SATA’: Listen")
    assert parsed == ("John Summit", "SATA", "regex")


def test_extract_artist_from_enlist_without_s():
    parsed = extract_from_title("The Chainsmokers enlist Oaks for new single, ‘Echo’: Listen")
    assert parsed == ("The Chainsmokers", "Echo", "regex")


def test_extract_artist_from_announces_and_unveils_clause():
    parsed = extract_from_title(
        "Roger Sanchez announces first studio album in 20 years, unveils ‘Temptation’ with Low Steppa: Listen"
    )
    assert parsed == ("Roger Sanchez", "Temptation", "regex")


def test_extract_title_from_flip_remix():
    parsed = extract_from_title(
        "DJs From Mars Flip ‘You Get What You Give’ into a high-energy remix with Van Snyder, Serena Bleu & Alexander Popov: Listen"
    )
    assert parsed == ("DJs From Mars", "You Get What You Give", "regex")


def test_release_type_detection():
    assert infer_release_type("new single ‘Sippin’") == "single"
    assert infer_release_type("drops Taylor Swift ‘Opalite’ remix") == "remix"
    assert infer_release_type("delivers pulsing new ‘Higher EP’") == "EP"
    assert infer_release_type("continues album push with new single ‘SATA’", "SATA") == "single"
    assert (
        infer_release_type(
            "unveils anthem ‘La La La’ " + ("filler " * 20) + "unrelated remix text",
            "La La La",
        )
        == "unknown"
    )


def test_parse_candidate_uses_embedded_link_and_body_confirmation():
    article = ArticleCard(
        title="Statikk channels groove and movement on new single ‘Self Control’: Listen",
        url="https://weraveyou.com/2026/04/statikk-self-control/",
        source_name="We Rave You",
        publish_date="2026-04-26",
    )
    enrichment = ArticleEnrichment(
        url=article.url,
        body_text="Statikk has released a new single ‘Self Control’ for house fans.",
        embedded_music_links=["https://open.spotify.com/track/example"],
        body_release_matches=["new single ‘Self Control’"],
    )
    candidate = parse_release_candidate(article, enrichment)
    assert candidate is not None
    assert candidate.artist == "Statikk"
    assert candidate.track_or_project_title == "Self Control"
    assert candidate.release_type == "single"
    assert candidate.confidence_score >= 0.8
    assert candidate.extraction_method == "regex+embedded_player"
