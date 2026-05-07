from bs4 import BeautifulSoup

from src.scrapers.edmcom import (
    EDMComScraper,
    _category_from_url,
    _extract_cards_from_feed,
    _extract_cards_from_page,
    _feed_url,
    _find_load_more_url,
    _soup_from_load_more_response,
    _split_title_and_date,
)


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


def test_split_title_and_date_from_card_text():
    title, publish_date = _split_title_and_date(
        "TroyBoi and Daya Let the Groove Do the Talking on New Single, ‘HUSH’ April 24, 2026"
    )
    assert title == "TroyBoi and Daya Let the Groove Do the Talking on New Single, ‘HUSH’"
    assert publish_date == "2026-04-24"


def test_feed_url_generation():
    assert _feed_url("https://edm.com/music-releases/") == "https://edm.com/.rss/full/"


def test_category_from_url():
    assert _category_from_url("https://edm.com/music-releases/") == "music-releases"


def test_extract_cards_from_rss_filters_to_music_releases():
    feed = """
    <rss><channel>
      <item>
        <title>TroyBoi and Daya Let the Groove Do the Talking on New Single, ‘HUSH’</title>
        <link>https://edm.com/music-releases/troyboi-daya-hush/?utm_source=rss</link>
        <pubDate>Fri, 24 Apr 2026 16:30:00 +0000</pubDate>
        <category>Music Releases</category>
        <description><![CDATA[The track arrives after its electrifying debut.]]></description>
      </item>
      <item>
        <title>Festival Lineup Announced</title>
        <link>https://edm.com/events/festival-lineup/</link>
        <pubDate>Fri, 24 Apr 2026 16:30:00 +0000</pubDate>
      </item>
    </channel></rss>
    """
    cards = _extract_cards_from_feed(feed, cutoff=None)
    assert len(cards) == 1
    assert cards[0].source_name == "EDM.com"
    assert cards[0].url == "https://edm.com/music-releases/troyboi-daya-hush/"
    assert cards[0].publish_date == "2026-04-24"


def test_extract_cards_from_archive_page():
    soup = BeautifulSoup(
        """
        <article>
          <h2><a href="/music-releases/nghtmre-viperactive-earthquake/">
            NGHTMRE and Viperactive Bring the Thunder on Nostalgic Trap Banger, “Earthquake”
          </a></h2>
          <p>The track arrives eight months after their first collaboration.</p>
          <span>April 24, 2026</span>
        </article>
        """,
        "html.parser",
    )
    cards, reached_cutoff = _extract_cards_from_page(
        soup,
        "https://edm.com/music-releases/",
        "music-releases",
        "EDM.com",
        cutoff=None,
    )
    assert reached_cutoff is False
    assert len(cards) == 1
    assert cards[0].url == "https://edm.com/music-releases/nghtmre-viperactive-earthquake/"
    assert cards[0].publish_date == "2026-04-24"


def test_find_explicit_load_more_url():
    soup = BeautifulSoup(
        '<button data-url="/wp-json/ajaxloadmore/posts?page=2">Load More</button>',
        "html.parser",
    )
    assert _find_load_more_url(soup, "https://edm.com/music-releases/", 2) == (
        "https://edm.com/wp-json/ajaxloadmore/posts?page=2"
    )


def test_soup_from_json_load_more_response():
    soup = _soup_from_load_more_response(
        '{"html": "<article><h2><a href=\\"/music-releases/vanco-repeat/\\">Listen to Vanco’s Sultry Afro-Tech Track, ‘Repeat’</a></h2></article>"}'
    )
    assert soup.select_one("h2 a").get_text(strip=True).startswith("Listen to Vanco")


def test_scrape_category_fetches_feed_archive_and_load_more(monkeypatch):
    responses = {
        "https://edm.com/.rss/full/": """
            <rss><channel>
              <item>
                <title>TroyBoi and Daya Let the Groove Do the Talking on New Single, ‘HUSH’</title>
                <link>https://edm.com/music-releases/troyboi-daya-hush/?utm_source=rss</link>
                <pubDate>Fri, 24 Apr 2026 16:30:00 +0000</pubDate>
                <category>Music Releases</category>
              </item>
            </channel></rss>
        """,
        "https://edm.com/music-releases/": """
            <article>
              <h2><a href="/music-releases/nghtmre-viperactive-earthquake/">
                NGHTMRE and Viperactive Bring the Thunder on Nostalgic Trap Banger, “Earthquake”
              </a></h2>
              <span>April 24, 2026</span>
            </article>
            <button data-url="/load-more/music-releases/2">Load More</button>
        """,
        "https://edm.com/load-more/music-releases/2": """
            <article>
              <h2><a href="/music-releases/vanco-repeat/">
                Listen to Vanco’s Sultry Afro-Tech Track, ‘Repeat’
              </a></h2>
              <span>April 23, 2026</span>
            </article>
        """,
    }
    requested_urls = []

    def fake_get(url, headers, timeout):
        requested_urls.append(url)
        return FakeResponse(responses[url])

    monkeypatch.setattr("src.scrapers.edmcom.requests.get", fake_get)
    cards = EDMComScraper().scrape_category(
        "https://edm.com/music-releases/",
        lookback_days=None,
        max_pages=2,
    )

    assert requested_urls == [
        "https://edm.com/.rss/full/",
        "https://edm.com/music-releases/",
        "https://edm.com/load-more/music-releases/2",
    ]
    assert [card.title for card in cards] == [
        "TroyBoi and Daya Let the Groove Do the Talking on New Single, ‘HUSH’",
        "NGHTMRE and Viperactive Bring the Thunder on Nostalgic Trap Banger, “Earthquake”",
        "Listen to Vanco’s Sultry Afro-Tech Track, ‘Repeat’",
    ]
