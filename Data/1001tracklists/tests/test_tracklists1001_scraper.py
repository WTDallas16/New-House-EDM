import pytest

from src.scrapers.tracklists1001 import (
    Tracklists1001AccessError,
    Tracklists1001Scraper,
    _extract_sidebar_chart_tracks,
    _extract_chart_page_tracks,
    _genre_from_url,
    _looks_like_turnstile_challenge,
    _parse_artist_and_title,
    _parse_js_object,
    _request_headers,
    _statistic_updater_params_for_chart,
)


SAMPLE_HTML = """
<html>
  <body>
    <main>
      <h1>Genre House Tracklists</h1>
      <a href="/tracklist/not-a-tracklist.html">Oliver Heldens - Heldeep Radio 536</a>
    </main>
    <aside>
      <h2>Top House Newcomer Tracks</h2>
      <span>1</span>
      <a href="/track/abc/chris-lake-disclosure-in2minds/index.html">Chris Lake & Disclosure - in2minds</a>
      <a href="/label/black-book/index.html">BLACK BOOK</a>
      <span>2</span>
      <a href="/track/def/deadmau5-westend-animal-rights-westend-remix/index.html">deadmau5 & Wolfgang Gartner - Animal Rights (Westend Remix)</a>
      <a href="/label/mau5trap/index.html">MAU5TRAP</a>
      <p>This chart displays how many unique DJs played a track within the last 21 days.</p>

      <h2>Most Heard House Tracks</h2>
      <span>1</span>
      <a href="/track/ghi/piem-mat-joe-let-the-beat/index.html">Piem & Mat.Joe - Let The Beat</a>
      <a href="/label/elrow/index.html">ELROW</a>
      <span>2</span>
      <a href="/track/jkl/riordan-ellis-moss-getaway/index.html">Riordan & Ellis Moss - GETAWAY</a>
      <a href="/label/realm/index.html">REALM</a>
      <p>This chart is based on the opened track players by our users.</p>
    </aside>
  </body>
</html>
"""


def test_genre_from_url():
    assert _genre_from_url("https://www.1001tracklists.com/genre/house/index.html") == "House"
    assert _genre_from_url("https://www.1001tracklists.com/genre/melodic-house-techno/index.html") == "Melodic House Techno"


def test_parse_artist_and_title():
    assert _parse_artist_and_title("Piem & Mat.Joe - Let The Beat") == ("Piem & Mat.Joe", "Let The Beat")
    assert _parse_artist_and_title("No separator") is None


def test_turnstile_detection():
    assert _looks_like_turnstile_challenge("Please wait, you will be forwarded to the requested page")
    assert _looks_like_turnstile_challenge('<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>')


def test_extract_sidebar_chart_tracks_ignores_main_tracklists():
    tracks = _extract_sidebar_chart_tracks(
        SAMPLE_HTML,
        base_url="https://www.1001tracklists.com/genre/house/index.html",
        genre="House",
    )
    titles = {(track.artist, track.title, track.chart_name) for track in tracks}
    assert ("Oliver Heldens", "Heldeep Radio 536", "Top House Newcomer Tracks") not in titles
    assert ("Chris Lake & Disclosure", "in2minds", "Top House Newcomer Tracks") in titles
    assert ("Piem & Mat.Joe", "Let The Beat", "Most Heard House Tracks") in titles


def test_extract_sidebar_chart_tracks_preserves_rank_label_and_urls():
    tracks = _extract_sidebar_chart_tracks(
        SAMPLE_HTML,
        base_url="https://www.1001tracklists.com/genre/house/index.html",
        genre="House",
    )
    first = tracks[0]
    assert first.rank == 1
    assert first.label == "BLACK BOOK"
    assert first.track_url == "https://www.1001tracklists.com/track/abc/chris-lake-disclosure-in2minds/index.html"
    assert first.label_url == "https://www.1001tracklists.com/label/black-book/index.html"


def test_extract_sidebar_chart_tracks_marks_remixes():
    tracks = _extract_sidebar_chart_tracks(
        SAMPLE_HTML,
        base_url="https://www.1001tracklists.com/genre/house/index.html",
        genre="House",
    )
    remix = tracks[1]
    assert remix.title == "Animal Rights (Westend Remix)"


def test_parse_statistic_updater_params_for_show_more():
    html = """
    <h2>Most Heard House Tracks</h2>
    <button onclick="new StatisticUpdater(this,{mode:9,params:'mh',destElement:'stat_mh'}).update()">Show More</button>
    """
    assert _statistic_updater_params_for_chart(html, "Most Heard House Tracks") == {
        "mode": "9",
        "params": "mh",
        "destElement": "stat_mh",
    }


def test_parse_js_object_handles_bare_values():
    assert _parse_js_object("{mode:9, params:'nc', showRank:true}") == {
        "mode": "9",
        "params": "nc",
        "showRank": "true",
    }


def test_request_headers_include_optional_cookie():
    assert _request_headers("guid=abc; session=def")["Cookie"] == "guid=abc; session=def"


def test_scraper_can_parse_saved_html_input(tmp_path):
    html_path = tmp_path / "tracklists.html"
    html_path.write_text(SAMPLE_HTML, encoding="utf-8")
    scraper = Tracklists1001Scraper(html_input=html_path)

    candidates = scraper.scrape_releases(
        "https://www.1001tracklists.com/genre/house/index.html",
        max_pages=5,
    )

    assert candidates[0].artist == "Chris Lake & Disclosure"
    assert candidates[0].track_or_project_title == "in2minds"
    assert candidates[0].open_graph["chart_name"] == "Top House Newcomer Tracks"


def test_saved_html_input_rejects_challenge_page(tmp_path):
    html_path = tmp_path / "challenge.html"
    html_path.write_text("Please wait, you will be forwarded to the requested page", encoding="utf-8")
    scraper = Tracklists1001Scraper(html_input=html_path)

    with pytest.raises(Tracklists1001AccessError):
        scraper.scrape_releases("https://www.1001tracklists.com/genre/house/index.html")


def test_extract_chart_page_tracks_from_unblocked_chart_rows():
    html = """
    <div class="bItm oItm" data-id="79x8ys85">
      <div class="bPlay"><div class="bRank">3</div></div>
      <div class="fontL">
        <a href="/track/79x8ys85/chris-lorenzo-amo-hots-4-u/index.html">Chris Lorenzo &amp; aMo - HOTS 4 U</a>
        <span class="trackLabel"><a href="/label/817s3g7/tszr/index.html">TSZR</a></span>
      </div>
      <div class="mt5">Unique DJ Support: <span class="badge playC"><span>32</span></span></div>
    </div>
    """

    tracks = _extract_chart_page_tracks(
        html,
        base_url="https://www.1001tracklists.com/charts/weekly/index.html",
        chart_name="Weekly DJ Support Tracks",
        chart_window="unique DJ support in the last 4 weeks",
        chart_metric="unique_dj_support_rank",
        confidence=0.78,
    )

    assert len(tracks) == 1
    assert tracks[0].rank == 3
    assert tracks[0].artist == "Chris Lorenzo & aMo"
    assert tracks[0].title == "HOTS 4 U"
    assert tracks[0].label == "TSZR"
    assert tracks[0].chart_metric == "unique_dj_support_rank:32"
