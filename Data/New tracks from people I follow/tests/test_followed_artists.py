from src.followed_artists import FollowedArtist, edm_terms_for_user, read_followed_artists_csv, split_genre_terms, write_followed_artists_csv


def test_split_genre_terms():
    assert split_genre_terms('"Tech House", Afro House / EDM') == ["Tech House", "Afro House", "EDM"]


def test_edm_terms_for_user_matches_genres_and_description():
    user = {"username": "Label", "description": "club music"}
    terms = edm_terms_for_user(user, ["Afro House", "Pop"])
    assert "afro house" in terms
    assert "club" in terms


def test_followed_artist_csv_roundtrip(tmp_path):
    path = tmp_path / "artists.csv"
    artists = [
        FollowedArtist(
            artist_name="Artist",
            soundcloud_url="https://soundcloud.com/artist",
            soundcloud_user_id="123",
            genres=["House"],
            edm_match_terms=["house"],
            followers_count=1000,
            track_count=10,
        )
    ]
    write_followed_artists_csv(artists, path)
    loaded = read_followed_artists_csv(path)
    assert loaded[0].artist_name == "Artist"
    assert loaded[0].soundcloud_user_id == "123"
    assert loaded[0].genres == ["House"]
