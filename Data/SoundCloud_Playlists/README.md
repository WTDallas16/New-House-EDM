# SoundCloud Playlist Extractor

Extracts tracks from one or more SoundCloud playlists and writes the same release-candidate schema used by the other source folders.

The scraper prefers SoundCloud's API when credentials are available, then falls back to public page parsing for public playlists.

## API Setup

Create a `.env` file in this folder:

```bash
SC_CLIENT_ID=your_client_id
SC_CLIENT_SECRET=your_client_secret
SC_REDIRECT_URI=http://127.0.0.1:8000/auth-callback
SC_TOKEN_FILE=sc_token.json
```

If you already have `sc_token.json` from the weekly updater project, copy it into this folder or point to it:

```bash
SC_TOKEN_FILE=/Users/WillyTardif/Documents/Claude_SC_Weekly_Song_Updater/sc_token.json
```

The token file should look like:

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "expires_in": 3600,
  "expires_at": 1777600000.0
}
```

When the token is expired or within five minutes of expiry, the scraper refreshes it through:

```text
https://secure.soundcloud.com/oauth/token
```

and writes the refreshed token back to `sc_token.json`.

For public API access without OAuth, `SC_CLIENT_ID` alone may be enough for some endpoints. OAuth is better and more reliable.

The scraper uses the `token_type` from `sc_token.json` for the `Authorization` header. New SoundCloud tokens usually use:

```text
Authorization: Bearer <access_token>
```

You can override this with `SC_AUTH_SCHEME`, but the default should be correct for tokens created by `SC_TOK.py`.

## Create sc_token.json

If you do not already have a token file, use `SC_TOK.py`.

Generate an authorization URL:

```bash
python3 SC_TOK.py authorize-url
```

Open the printed URL, approve SoundCloud, then copy the `code=` value from the redirect URL. Put the printed verifier and fresh code in `.env`:

```bash
SC_CODE_VERIFIER=paste_printed_verifier
SC_AUTH_CODE=paste_fresh_code_value
```

Exchange the code:

```bash
python3 SC_TOK.py exchange
```

If you already have `sc_token.json` and only need to refresh it:

```bash
python3 SC_TOK.py refresh
```

Important: SoundCloud authorization codes are short-lived and single-use. If token exchange returns HTTP 400, generate a new authorization URL and use a fresh `code=` value with the exact matching `SC_CODE_VERIFIER`.

## Run

Pass playlists directly:

```bash
python3 -m src.main \
  --playlist "https://soundcloud.com/user/sets/playlist-name" \
  --playlist "another-user/sets/another-playlist" \
  --output data/extracted_releases.json
```

Or use a file:

```bash
python3 -m src.main \
  --playlists-file playlists.txt \
  --lookback-days 14 \
  --output data/extracted_releases.json
```

The command also writes `data/extracted_releases.csv` unless you pass `--csv-output`.

By default, the CLI keeps only tracks whose `article_date` is within the last 14 days. Use a different window with `--lookback-days`, or disable date filtering with:

```bash
python3 -m src.main \
  --playlists-file playlists.txt \
  --lookback-days 0 \
  --output data/extracted_releases.json
```

Force API-only mode, with no HTML fallback:

```bash
python3 -m src.main \
  --playlists-file playlists.txt \
  --api-only \
  --output data/extracted_releases.json
```

Use a specific token file:

```bash
python3 -m src.main \
  --playlists-file playlists.txt \
  --token-file /path/to/sc_token.json \
  --output data/extracted_releases.json
```

## Playlist File

Add one playlist URL or SoundCloud path per line:

```text
# playlists.txt
https://soundcloud.com/user/sets/playlist-name
another-user/sets/another-playlist
```

Public playlist URLs are easiest. Private playlists require an OAuth token that has access to them.

## Output Format

Each SoundCloud playlist track becomes a release candidate:

```json
{
  "artist": "Artist One",
  "track_or_project_title": "Warehouse Tune",
  "release_type": "track",
  "confidence_score": 0.95,
  "extraction_method": "soundcloud_playlist_api",
  "source_article_title": "Artist One - Warehouse Tune",
  "source_article_url": "https://soundcloud.com/artist-one/warehouse-tune",
  "source_name": "SoundCloud Playlist",
  "article_date": "2026-04-24",
  "embedded_music_links": [
    "https://soundcloud.com/artist-one/warehouse-tune"
  ],
  "open_graph": {
    "playlist_id": "999",
    "playlist_name": "House Finds",
    "playlist_owner": "Curator",
    "playlist_url": "https://soundcloud.com/user/sets/house-finds",
    "soundcloud_track_id": "123",
    "soundcloud_username": "Artist One",
    "genre": "House",
    "tag_list": "house tech-house",
    "label": "Night Label",
    "isrc": "USABC2600001",
    "playback_count": "1000",
    "likes_count": "77"
  },
  "release_article": true
}
```

SoundCloud-specific metadata is stored in `open_graph` so the top-level fields stay compatible with the blog, chart, and Spotify projects.

## How It Works

`src/scrapers/soundcloud_playlists.py` uses this order:

1. If API credentials are present, call `https://api.soundcloud.com/resolve` with the playlist URL.
2. If the resolved playlist needs full track hydration, call `https://api.soundcloud.com/tracks/{id}`.
3. Add `access=playable,preview,blocked` to API requests, matching the weekly updater's endpoint style.
4. If API access is unavailable or fails and `--api-only` is not set, fetch the public playlist page and parse SoundCloud's embedded hydration data.

Artist/title extraction is layered:

1. Prefer SoundCloud publisher metadata when present.
2. Parse titles like `Artist - Track`.
3. Fall back to the uploader username as artist.

Run tests:

```bash
python3 -m pytest
```
