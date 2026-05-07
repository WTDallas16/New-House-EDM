# MusicMetricsVault Top Artists

Builds a deduped CSV of top artists from MusicMetricsVault genre pages.

## Run

```bash
python3 -m src.main \
  --output master_artist_list.csv
```

Default genre targets:

```text
https://www.musicmetricsvault.com/genres/house/268,100
https://www.musicmetricsvault.com/genres/edm-trap/399,70
https://www.musicmetricsvault.com/genres/afro-house/393,70
https://www.musicmetricsvault.com/genres/funky-house/669,100
https://www.musicmetricsvault.com/genres/tech-house/118,200
```

Or use a custom file:

```bash
python3 -m src.main \
  --genre-file genre_urls.txt \
  --output master_artist_list.csv
```

## Output

`master_artist_list.csv` contains:

```text
artist_name,spotify_url,soundcloud_url,soundcloud_user_id,genre,rank,monthly_listeners
```

Artists are deduplicated by Spotify ID when available. If an artist appears in multiple genres, the `genre` field is joined with ` | `, the best rank is kept, and the largest monthly listener value is kept.

## How It Works

MusicMetricsVault pages are rendered by Livewire. The initial HTML already includes a `wire:snapshot` payload with the full artist dataset for the genre, including:

- artist name
- Spotify artist ID
- original genre rank
- monthly listeners

Because the Spotify ID is already present, the script builds exact Spotify URLs directly:

```text
https://open.spotify.com/artist/{spotify_id}
```

If a future row has no Spotify ID, the script can use Spotify API search as a fallback. It loads credentials from this folder's `.env` or `../Spotify_Playlists/.env`.

Disable fallback search:

```bash
python3 -m src.main --no-spotify-search
```

Add SoundCloud profile URLs/user IDs to the artist CSV:

```bash
python3 -m src.main \
  --soundcloud-search \
  --output master_artist_list.csv
```

Test the enrichment on a small batch:

```bash
python3 -m src.main \
  --soundcloud-search \
  --limit-artists 25 \
  --output data/master_artist_list_soundcloud_sample.csv
```

SoundCloud credentials are loaded from this folder's `.env` or `../SoundCloud_Playlists/.env`. If no confident SoundCloud profile is found for an artist, the CSV keeps blank values and the SoundCloud refresh skips that artist gracefully.

Run tests:

```bash
python3 -m pytest
```

## Find Recent Tracks From Artist Profiles

Once `master_artist_list.csv` exists, scan each Spotify artist profile for new albums/singles and write release candidates in the same JSON shape as the playlist/blog projects:

```bash
python3 -m src.recent_tracks \
  --artists-csv master_artist_list.csv \
  --lookback-days 14 \
  --output data/master_recent_tracks.json
```

The script loads Spotify credentials from this folder's `.env` or `../Spotify_Playlists/.env`, then:

- reads each `spotify_url` from the CSV
- checks Spotify artist albums/singles
- keeps releases with day-precision release dates inside the lookback window
- expands recent releases into track-level records
- deduplicates by Spotify track ID
- ranks every entry and writes the JSON sorted by `ranking_score` descending
- if Spotify returns a rate-limit response, stops Spotify and continues the remaining artists through SoundCloud profile tracks when `soundcloud_user_id` or `soundcloud_url` is present

Ranking uses a 0-100 weighted score:

```text
30% MusicMetricsVault monthly listeners
15% MusicMetricsVault genre rank
20% Spotify artist popularity
10% Spotify artist followers
15% Spotify track popularity
10% recency inside the lookback window
```

Each record includes `ranking_score` and `ranking_factors` so the raw values, component scores, and weights are visible for tuning.

By default, `--ranking-mode fast` avoids extra Spotify detail calls and ranks from MusicMetricsVault monthly listeners, MusicMetricsVault rank, and recency. When API limits are healthy, use full ranking to add Spotify artist popularity/followers and Spotify track popularity:

```bash
python3 -m src.recent_tracks \
  --artists-csv master_artist_list.csv \
  --lookback-days 14 \
  --ranking-mode full \
  --output data/master_recent_tracks.json
```

If you already have a JSON file and only want to add/update rankings without calling Spotify:

```bash
python3 -m src.recent_tracks \
  --rank-existing-json data/master_recent_tracks.json \
  --lookback-days 14 \
  --output data/master_recent_tracks.json
```

Useful options:

```bash
python3 -m src.recent_tracks --limit-artists 25 --output data/test_recent_tracks.json
python3 -m src.recent_tracks --lookback-days 30 --market US
python3 -m src.recent_tracks --no-stop-on-rate-limit
python3 -m src.recent_tracks --no-soundcloud-fallback
python3 -m src.recent_tracks --soundcloud-only --artists-csv master_artist_list.csv --output data/soundcloud_recent_tracks.json
```

By default, the Spotify artist scan stops cleanly on the first `429` rate-limit response and writes whatever it collected before the limit. This avoids repeatedly calling Spotify during a long retry window.
