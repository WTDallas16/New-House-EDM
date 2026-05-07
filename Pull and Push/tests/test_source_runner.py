from pathlib import Path

from src.source_runner import default_source_specs


def test_default_source_order(tmp_path):
    specs = default_source_specs(data_root=Path("Data"), output_dir=tmp_path)
    assert [spec.name for spec in specs] == [
        "edmcom",
        "edmtunes",
        "soundcloud_playlists",
        "spotify_playlists",
        "submithub",
        "weraveyou",
        "1001tracklists",
        "followed_soundcloud",
        "top_artisits_recent",
    ]
