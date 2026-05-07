from src.scrapers.edmtunes import (
    EDMTunesScraper,
    _category_from_url,
    _extract_cards_from_feed,
    _feed_url,
    _paginated_url,
    _split_title_and_date,
)


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


def test_split_title_and_date_from_archive_card():
    title, publish_date = _split_title_and_date("GorillaT Goes Full Send with Latest Single ‘BOOM’ April 24, 2026")
    assert title == "GorillaT Goes Full Send with Latest Single ‘BOOM’"
    assert publish_date == "2026-04-24"


def test_paginated_url_generation():
    url = "https://www.edmtunes.com/music/"
    assert _paginated_url(url, 1) == "https://www.edmtunes.com/music/"
    assert _paginated_url(url, 2) == "https://www.edmtunes.com/music/page/2/"
    assert _paginated_url("https://www.edmtunes.com/music/page/3/", 4) == (
        "https://www.edmtunes.com/music/page/4/"
    )


def test_feed_url_generation():
    assert _feed_url("https://www.edmtunes.com/music/") == "https://www.edmtunes.com/music/feed/"
    assert _feed_url("https://www.edmtunes.com/music/page/2/") == "https://www.edmtunes.com/music/feed/"


def test_category_from_paginated_url():
    assert _category_from_url("https://www.edmtunes.com/music/page/2/") == "music"


def test_extract_cards_from_rss_feed():
    feed = """
    <rss><channel>
      <item>
        <title>Paradoks Reveals Powerful New Single ‘Granular’</title>
        <link>https://www.edmtunes.com/2026/04/paradoks-granular/</link>
        <pubDate>Fri, 24 Apr 2026 16:30:00 +0000</pubDate>
        <category>Progressive House</category>
        <category>Music</category>
        <description><![CDATA[Paradoks has released his new single 'Granular'.]]></description>
      </item>
    </channel></rss>
    """
    cards = _extract_cards_from_feed(feed, cutoff=None)
    assert len(cards) == 1
    assert cards[0].title == "Paradoks Reveals Powerful New Single ‘Granular’"
    assert cards[0].source_name == "EDMTunes"
    assert cards[0].publish_date == "2026-04-24"
    assert cards[0].category == "Progressive House, Music"
    assert cards[0].snippet == "Paradoks has released his new single 'Granular'."


def test_scrape_category_fetches_feed_and_multiple_pages(monkeypatch):
    responses = {
        "https://www.edmtunes.com/music/feed/": """
            <rss><channel>
              <item>
                <title>Paradoks Reveals Powerful New Single ‘Granular’</title>
                <link>https://www.edmtunes.com/2026/04/paradoks-granular/</link>
                <pubDate>Fri, 24 Apr 2026 16:30:00 +0000</pubDate>
                <category>Progressive House</category>
                <description>Paradoks has released his new single.</description>
              </item>
            </channel></rss>
        """,
        "https://www.edmtunes.com/music/": """
            <article>
              <h3><a href="https://www.edmtunes.com/2026/04/gorillat-boom/">
                GorillaT Goes Full Send with Latest Single ‘BOOM’
              </a></h3>
              <span>Kevin Ng - April 24, 2026</span>
              <p>GorillaT drops his latest single.</p>
            </article>
        """,
        "https://www.edmtunes.com/music/page/2/": """
            <article>
              <h3><a href="https://www.edmtunes.com/2026/04/barkin-energy-up/">
                Barkin Drops New Bass House Banger ‘Energy Up’
              </a></h3>
              <span>April 20, 2026</span>
            </article>
        """,
    }
    requested_urls = []

    def fake_get(url, headers, timeout):
        requested_urls.append(url)
        return FakeResponse(responses[url])

    monkeypatch.setattr("src.scrapers.edmtunes.requests.get", fake_get)
    cards = EDMTunesScraper().scrape_category(
        "https://www.edmtunes.com/music/",
        lookback_days=None,
        max_pages=2,
    )

    assert requested_urls == [
        "https://www.edmtunes.com/music/feed/",
        "https://www.edmtunes.com/music/",
        "https://www.edmtunes.com/music/page/2/",
    ]
    assert [card.title for card in cards] == [
        "Paradoks Reveals Powerful New Single ‘Granular’",
        "GorillaT Goes Full Send with Latest Single ‘BOOM’",
        "Barkin Drops New Bass House Banger ‘Energy Up’",
    ]
