# New Tracks From People I Follow

Builds a SoundCloud-based release feed from the accounts you follow.

The workflow:

1. Fetch accounts you follow from SoundCloud.
2. Sample each account's recent tracks to infer genre/tags.
3. Keep EDM-ish accounts by default.
4. Write `followed_artists.csv`.
5. Pull recent tracks from those followed artists.
6. Write release candidates in the same JSON schema as the other source folders.

## Run

```bash
python3 -m src.main \
  --lookback-days 14 \
  --artists-output followed_artists.csv \
  --output data/recent_tracks.json
```

For a small smoke test:

```bash
python3 -m src.main \
  --max-users 25 \
  --track-sample-limit 5 \
  --track-limit 25 \
  --output data/recent_tracks_sample.json
```

Reuse the existing artist CSV without refreshing followed users:

```bash
python3 -m src.main \
  --skip-artist-refresh \
  --artists-input followed_artists.csv \
  --output data/recent_tracks.json
```

## Output

`followed_artists.csv` contains:

```text
artist_name,soundcloud_url,soundcloud_user_id,genres,edm_match_terms,followers_count,track_count,country,city
```

`data/recent_tracks.json` uses the shared release schema:

```json
{
  "artist": "Artist",
  "track_or_project_title": "Track",
  "release_type": "track",
  "confidence_score": 0.9,
  "extraction_method": "soundcloud_followed_artist_api",
  "source_article_title": "Artist - Track",
  "source_article_url": "https://soundcloud.com/artist/track",
  "source_name": "SoundCloud Followed Artist",
  "article_date": "2026-05-03",
  "embedded_music_links": ["https://soundcloud.com/artist/track"],
  "open_graph": {},
  "release_article": true
}
```

The scraper skips obvious long DJ sets, live sets, podcasts, radio shows, and festival recordings unless SoundCloud publisher metadata has release identifiers.

## Credentials

The project loads SoundCloud credentials from this folder's `.env`, or falls back to:

```text
../SoundCloud_Playlists/.env
```

Run tests:

```bash
python3 -m pytest
```
