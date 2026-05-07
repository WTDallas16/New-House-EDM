from src.main import soundcloud_playlist_tracks
from src.models import ResolvedTrack


def make_track(track_id: str | None) -> ResolvedTrack:
    return ResolvedTrack(
        rank=1,
        ranking_score=90,
        artist="Artist",
        title=f"Track {track_id}",
        source_names=["test"],
        source_record={},
        soundcloud_track_id=track_id,
    )


def test_soundcloud_playlist_tracks_backfills_unique_ids():
    tracks = [make_track("1"), make_track(None), make_track("1"), make_track("2"), make_track("3")]

    selected = soundcloud_playlist_tracks(tracks, target_count=2)

    assert [track.soundcloud_track_id for track in selected] == ["1", "2"]

