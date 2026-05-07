from src.musicmetricsvault import (
    ArtistRow,
    decode_livewire_artist_collection,
    dedupe_artists,
    genre_from_url,
    parse_artists_from_html,
    spotify_id_from_mmv_artist_url,
)


def test_genre_from_url():
    assert genre_from_url("https://www.musicmetricsvault.com/genres/tech-house/118") == "tech house"


def test_spotify_id_from_mmv_artist_url():
    assert (
        spotify_id_from_mmv_artist_url("https://www.musicmetricsvault.com/artists/disclosure/6nS5roXSAGhTGr34W6n7Et")
        == "6nS5roXSAGhTGr34W6n7Et"
    )


def test_decode_livewire_artist_collection():
    payload = [
        [
            [{"name": "Disclosure", "spotify_id": "abc1234567890123", "_original_rank": 1}, {"s": "arr"}],
            [{"name": "FISHER", "spotify_id": "def1234567890123", "_original_rank": 2}, {"s": "arr"}],
        ],
        {"s": "arr"},
    ]
    rows = decode_livewire_artist_collection(payload)
    assert [row["name"] for row in rows] == ["Disclosure", "FISHER"]


def test_parse_artists_from_livewire_snapshot():
    html = """
    <div wire:snapshot='{"data":{"allArtists":[[[{"name":"Disclosure","spotify_id":"6nS5roXSAGhTGr34W6n7Et","listeners":22246843,"_original_rank":1},{"s":"arr"}]],{"s":"arr"}]},"memo":{"name":"components.artist-table"}}'></div>
    """
    rows = parse_artists_from_html(html, genre="house")
    assert len(rows) == 1
    assert rows[0].artist_name == "Disclosure"
    assert rows[0].spotify_url == "https://open.spotify.com/artist/6nS5roXSAGhTGr34W6n7Et"
    assert rows[0].monthly_listeners == 22246843
    assert rows[0].rank == 1


def test_dedupe_artists_merges_genres_and_keeps_best_rank():
    rows = [
        ArtistRow("Disclosure", "https://open.spotify.com/artist/abc", "house", rank=10, monthly_listeners=100, spotify_id="abc", genres=["house"]),
        ArtistRow("Disclosure", "https://open.spotify.com/artist/abc", "tech house", rank=2, monthly_listeners=80, spotify_id="abc", genres=["tech house"]),
    ]
    deduped = dedupe_artists(rows)
    assert len(deduped) == 1
    assert deduped[0].rank == 2
    assert deduped[0].monthly_listeners == 100
    assert deduped[0].csv_row()["genre"] == "house | tech house"
