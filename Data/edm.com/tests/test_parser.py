from src.extraction.parser import extract_from_title, infer_release_type
from src.models import ArticleCard, ArticleEnrichment
from src.extraction.parser import parse_release_candidate


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


def test_extract_edmtunes_colon_title():
    parsed = extract_from_title("Armin van Buuren & Argy: ‘Like a Child’")
    assert parsed == ("Armin van Buuren & Argy", "Like a Child", "regex")


def test_extract_edmtunes_collide_for_title():
    parsed = extract_from_title("Roddy Lima and Suraya Collide For House Groover ‘SIDE2SIDE’")
    assert parsed == ("Roddy Lima and Suraya", "SIDE2SIDE", "regex")


def test_extract_edmtunes_unquoted_album_title():
    parsed = extract_from_title("ZHU Returns to the Dancefloor With New Album BLACK MIDAS")
    assert parsed == ("ZHU", "BLACK MIDAS", "regex")


def test_extract_edmtunes_unite_on_title():
    parsed = extract_from_title("Jason Ross & William Black Unite on Emotional New Single ‘Mirage’ ft. Oaks")
    assert parsed == ("Jason Ross & William Black", "Mirage", "regex")


def test_extract_edmtunes_apostrophe_inside_curly_quotes():
    parsed = extract_from_title("Devault Quickly Returns to Experts Only with ‘Can’t Wait No More’")
    assert parsed == ("Devault Quickly", "Can’t Wait No More", "regex")


def test_extract_edmtunes_unquoted_debut_album_title():
    parsed = extract_from_title("WHIPPED CREAM Unveils Debut Album, HOME WAS ALWAYS ME")
    assert parsed == ("WHIPPED CREAM", "HOME WAS ALWAYS ME", "regex")


def test_extract_edmtunes_joins_with_title():
    parsed = extract_from_title("DJ Susan Joins Dirtybird Records With ‘Transformation’ Single")
    assert parsed == ("DJ Susan", "Transformation", "regex")


def test_extract_edmtunes_unleash_title():
    parsed = extract_from_title("Malaa’s Alter Ego and YDG Unleash ‘STFU’")
    assert parsed == ("Malaa’s Alter Ego and YDG", "STFU", "regex")


def test_skip_ambiguous_unquoted_announcement_tail():
    parsed = extract_from_title("Brutalismus 3000 Shares Latest Single and Announces New Album Harmony")
    assert parsed is None


def test_extract_edmtunes_goes_quoted_title_on_new_single():
    parsed = extract_from_title("Riot Ten Goes ‘WONKY SHIT’ on New Single with J. Plaza")
    assert parsed == ("Riot Ten", "WONKY SHIT", "regex")


def test_extract_straight_quoted_title_with_apostrophe():
    parsed = extract_from_title("Mozambo & Antdot Rework Angie Stone Classic 'Wish I Didn't Miss You'")
    assert parsed == ("Mozambo & Antdot", "Wish I Didn't Miss You", "regex")


def test_extract_edmcom_return_with_artist():
    parsed = extract_from_title("G Jones and Eprom Return With Mind-Bending EP, ‘Break of Dawn’")
    assert parsed == ("G Jones and Eprom", "Break of Dawn", "regex")


def test_extract_edmcom_listen_to_possessive_artist():
    parsed = extract_from_title("Listen to Vanco’s Sultry Afro-Tech Track, ‘Repeat’")
    assert parsed == ("Vanco", "Repeat", "regex")


def test_extract_edmcom_on_possessive_artist():
    parsed = extract_from_title("Two Worlds Collide on Armin van Buuren and Argy’s ‘Like a Child:’ Listen")
    assert parsed == ("Armin van Buuren and Argy", "Like a Child", "regex")


def test_extract_edmcom_in_possessive_artist():
    parsed = extract_from_title(
        "Love Becomes Life Support in Sarah de Warren and CIRCA96’s Trance Anthem, ‘Breathing Underwater’"
    )
    assert parsed == ("Sarah de Warren and CIRCA96", "Breathing Underwater", "regex")


def test_extract_edmcom_announcement_with_released_single():
    parsed = extract_from_title("k?d Announces Sophomore Album With Release of Lead Single, ‘close your eyes’")
    assert parsed == ("k?d", "close your eyes", "regex")


def test_extract_edmcom_exclusive_prefix_removed():
    parsed = extract_from_title("Exclusive: Ghastly Returns With Vintage Comeback Mix, ‘Dopamine Machine Vol. 1’")
    assert parsed == ("Ghastly", "Dopamine Machine Vol. 1", "regex")


def test_extract_edmcom_pull_pin_title():
    parsed = extract_from_title("Madeon and Slayyyter Pull the Pin on Electropop Grenade, ‘Fire Away’: Listen")
    assert parsed == ("Madeon and Slayyyter", "Fire Away", "regex")


def test_extract_edmcom_bring_thunder_title():
    parsed = extract_from_title("NGHTMRE and Viperactive Bring the Thunder on Nostalgic Trap Banger, “Earthquake”")
    assert parsed == ("NGHTMRE and Viperactive", "Earthquake", "regex")


def test_extract_edmcom_new_single_listen_to_title():
    parsed = extract_from_title("Of The Trees to Donate Royalties From New Single to Environmental Causes: Listen to ‘Amanita’")
    assert parsed == ("Of The Trees", "Amanita", "regex")


def test_extract_edmcom_possessive_album_title():
    parsed = extract_from_title("Deorro’s ‘Botas & Rave’ Album Fuses Mexican Tradition With the Global Dancefloor")
    assert parsed == ("Deorro", "Botas & Rave", "regex")


def test_extract_edmcom_unclosed_quote_ep_title():
    parsed = extract_from_title("Getter Serves Up a Double Dose of Dread in New EP, ‘DOOM 2")
    assert parsed == ("Getter", "DOOM 2", "regex")


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
