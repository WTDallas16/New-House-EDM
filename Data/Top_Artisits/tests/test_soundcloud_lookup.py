from src.soundcloud_lookup import SoundCloudArtistLookup, normalize_name


class FakeClient:
    can_use_api = True

    def search_users(self, artist_name, limit=8):
        return [
            {
                "id": 1,
                "username": "Unrelated",
                "permalink": "unrelated",
                "permalink_url": "https://soundcloud.com/unrelated",
                "followers_count": 100,
            },
            {
                "id": 2,
                "username": "Disclosure",
                "permalink": "disclosure",
                "permalink_url": "https://soundcloud.com/disclosure",
                "followers_count": 100000,
                "verified": True,
            },
        ]


def test_normalize_name():
    assert normalize_name("D.O.D & Friends") == "d o d and friends"


def test_soundcloud_artist_lookup_selects_best_match():
    match = SoundCloudArtistLookup(client=FakeClient()).search_artist("Disclosure")
    assert match is not None
    assert match.user_id == "2"
    assert match.url == "https://soundcloud.com/disclosure"
