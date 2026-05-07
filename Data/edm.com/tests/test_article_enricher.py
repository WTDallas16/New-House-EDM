from bs4 import BeautifulSoup

from src.enrich.article_enricher import extract_music_links


def test_extract_music_links_ignores_site_social_profiles():
    soup = BeautifulSoup(
        """
        <main>
          <a href="https://open.spotify.com/album/5dtrV6pAh4Fuaw3Ravv67G">Spotify</a>
          <a href="https://open.spotify.com/user/weraveyou">Profile</a>
          <a href="https://www.youtube.com/user/WeRaveYou">YouTube profile</a>
          <a href="https://soundcloud.com/weraveyou">SoundCloud profile</a>
          <iframe src="https://soundcloud.com/rob-laniado/rob-laniado-falling-under-rome"></iframe>
        </main>
        """,
        "html.parser",
    )
    links = extract_music_links(soup, "https://weraveyou.com/example/")
    assert links == [
        "https://open.spotify.com/album/5dtrV6pAh4Fuaw3Ravv67G",
        "https://soundcloud.com/rob-laniado/rob-laniado-falling-under-rome",
    ]

