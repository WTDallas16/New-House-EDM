from weraveyou.src.scrapers.weraveyou import WeRaveYouScraper, _category_from_url, _paginated_url, _split_title_and_date


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


def test_split_title_and_date_from_discover_link():
    title, publish_date = _split_title_and_date(
        "New Wing unveils captivating new single ‘Sippin’: Listen March 20, 2026"
    )
    assert title == "New Wing unveils captivating new single ‘Sippin’: Listen"
    assert publish_date == "2026-03-20"


def test_split_title_and_date_from_latest_news_link():
    title, publish_date = _split_title_and_date(
        "Latest news April 29, 2026 Denis First unveils feel-good house anthem ‘La La La’: Listen Read more"
    )
    assert title == "Denis First unveils feel-good house anthem ‘La La La’: Listen"
    assert publish_date == "2026-04-29"


def test_paginated_url_generation():
    url = "https://weraveyou.com/category/music/house/"
    assert _paginated_url(url, 1) == "https://weraveyou.com/category/music/house/"
    assert _paginated_url(url, 2) == "https://weraveyou.com/category/music/house/page/2/"
    assert _paginated_url("https://weraveyou.com/category/music/house/page/3/", 4) == (
        "https://weraveyou.com/category/music/house/page/4/"
    )


def test_category_from_paginated_url():
    assert _category_from_url("https://weraveyou.com/category/music/house/page/2/") == "house"


def test_scrape_category_fetches_multiple_pages(monkeypatch):
    responses = {
        "https://weraveyou.com/category/music/house/": """
            <article>
              <a href="https://weraveyou.com/2026/04/artist-one-song/">
                Artist One drops new single ‘Song One’: Listen April 29, 2026
              </a>
            </article>
        """,
        "https://weraveyou.com/category/music/house/page/2/": """
            <article>
              <a href="https://weraveyou.com/2026/04/artist-two-song/">
                Artist Two unveils new track ‘Song Two’: Listen April 20, 2026
              </a>
            </article>
        """,
    }
    requested_urls = []

    def fake_get(url, headers, timeout):
        requested_urls.append(url)
        return FakeResponse(responses[url])

    monkeypatch.setattr("src.scrapers.weraveyou.requests.get", fake_get)
    cards = WeRaveYouScraper().scrape_category(
        "https://weraveyou.com/category/music/house/",
        lookback_days=None,
        max_pages=2,
    )

    assert requested_urls == [
        "https://weraveyou.com/category/music/house/",
        "https://weraveyou.com/category/music/house/page/2/",
    ]
    assert [card.track_or_project_title if hasattr(card, "track_or_project_title") else card.title for card in cards] == [
        "Artist One drops new single ‘Song One’: Listen",
        "Artist Two unveils new track ‘Song Two’: Listen",
    ]
