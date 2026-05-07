from pathlib import Path

from src.source_runner import SourceCommand, default_source_commands, filter_commands


def test_default_source_commands_include_expected_outputs(tmp_path):
    commands = default_source_commands(Path("/repo"), tmp_path, lookback_days=7, max_pages=3)
    names = [command.name for command in commands]
    assert "weraveyou" in names
    assert "top_artisits_recent" not in names
    assert all(command.output_path.parent == tmp_path for command in commands)
    soundcloud = next(command for command in commands if command.name == "soundcloud_playlists")
    assert "playlist.txt" in soundcloud.args


def test_default_source_commands_can_include_artist_profile_scan(tmp_path):
    commands = default_source_commands(Path("/repo"), tmp_path, include_artist_profile_scan=True)
    assert "top_artisits_recent" in [command.name for command in commands]


def test_filter_commands_only_skip_and_api():
    commands = [
        SourceCommand("blog", Path("."), Path("blog.json"), []),
        SourceCommand("spotify", Path("."), Path("spotify.json"), [], api_source=True),
    ]
    assert [command.name for command in filter_commands(commands, ["blog"], [], False)] == ["blog"]
    assert [command.name for command in filter_commands(commands, [], ["blog"], False)] == ["spotify"]
    assert [command.name for command in filter_commands(commands, [], [], True)] == ["blog"]
