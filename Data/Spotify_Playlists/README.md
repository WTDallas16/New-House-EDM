# Spotify Playlist Extractor

Extracts tracks from one or more Spotify playlists and writes the same release-candidate schema used by the blog/chart scrapers.

## Setup

Create a `.env` file in this folder:

```bash
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
SPOTIFY_SCOPE=playlist-read-private playlist-read-collaborative
```

The code also recognizes your existing variable names: `clientid`, `secretclientid`, `redirect_uri`, and `scope`.

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Run

Pass playlists directly:

```bash
python3 -m src.main \
  --playlist "https://open.spotify.com/playlist/PLAYLIST_ID" \
  --playlist "spotify:playlist:ANOTHER_PLAYLIST_ID" \
  --output data/extracted_releases.json
```

Or use a file:

```bash
python3 -m src.main \
  --playlists-file playlists.txt \
  --market US \
  --output data/extracted_releases.json
```

The command also writes `data/extracted_releases.csv` unless you pass `--csv-output`.

If one playlist URL is invalid, removed, private, or unavailable to your account/market, the script logs a warning and continues with the remaining playlists. To make playlist errors stop the run, add:

```bash
--fail-on-playlist-error
```

On the first run, Spotipy may open a browser authorization flow. After you approve, it caches a token in `.spotify_token_cache`.

## Output Format

Each playlist track becomes a release candidate:

```json
{
  "artist": "Artist One",
  "track_or_project_title": "House Tune",
  "release_type": "single",
  "confidence_score": 1.0,
  "extraction_method": "spotify_playlist_api",
  "source_article_title": "Artist One - House Tune",
  "source_article_url": "https://open.spotify.com/track/...",
  "source_name": "Spotify Playlist",
  "article_date": "2026-04-24",
  "embedded_music_links": [
    "https://open.spotify.com/track/..."
  ],
  "open_graph": {
    "playlist_id": "playlist123",
    "playlist_name": "House Finds",
    "playlist_owner": "Willy",
    "playlist_url": "https://open.spotify.com/playlist/...",
    "spotify_track_id": "track123",
    "album_name": "House Tune",
    "album_type": "single",
    "spotify_popularity": "71",
    "isrc": "USABC2600001",
    "added_at": "2026-04-30T10:00:00Z"
  },
  "release_article": true
}
```

Spotify-specific metadata is stored in `open_graph` so the top-level fields stay compatible with the other projects.

## Notes

- Dedupe is by normalized artist, track title, and release type.
- Use `--no-dedupe` if you want to keep duplicate tracks that appear in multiple playlists.
- `article_date` is Spotify album release date.
- `added_at` in `open_graph` is when the track was added to the playlist.

Run tests:

```bash
python3 -m pytest
```
