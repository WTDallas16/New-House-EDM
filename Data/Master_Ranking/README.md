# Master Release Ranking

Ranks release candidates from every working source folder except `1001tracklists`.

Default inputs:

```text
weraveyou/data/extracted_releases_v3.json
edmtunes/data/extracted_releases.json
edm.com/data/extracted_releases.json
submithub/data/extracted_releases.json
Spotify_Playlists/data/extracted_releasesv2.json
SoundCloud_Playlists/data/extracted_releasesv3.json
Top_Artisits/data/master_recent_tracks_v2.json
```

Run:

```bash
python3 -m src.main
```

Outputs:

```text
data/ranked_releases.json
data/ranked_releases_unique.json
```

`ranked_releases.json` keeps every original source entry and adds ranking fields. `ranked_releases_unique.json` keeps the best-scored record per duplicate group.

## Ranking

The score is API-free by default, so it will not hit Spotify rate limits. It uses signals already present in the JSON:

- existing source ranking from `Top_Artisits`, if present
- extraction confidence
- source quality
- recency
- embedded Spotify/SoundCloud/music links
- Spotify popularity fields already captured by playlist/profile scripts
- SoundCloud playback, likes, and repost counts
- SubmitHub points, likes, and chart rank
- cross-source duplicate sightings

Duplicate detection prefers stable IDs:

```text
spotify_track_id -> isrc -> soundcloud_track_id -> normalized artist/title
```

Songs appearing in multiple files/sources receive a higher `cross_source_duplicates` component and get:

```text
cross_source_duplicate_count
cross_source_source_count
cross_source_sources
duplicate_group_key
```

Custom inputs:

```bash
python3 -m src.main \
  --input ../Spotify_Playlists/data/extracted_releasesv2.json \
  --input ../SoundCloud_Playlists/data/extracted_releasesv3.json \
  --output data/playlist_ranked.json
```

Rank every JSON in a directory:

```bash
python3 -m src.main \
  --input-dir data/source_outputs \
  --output data/ranked_releases.json
```

Run tests:

```bash
python3 -m pytest
```

## Refresh Sources First

By default, this project only ranks JSON files that already exist. To rerun the working source scripts first and rank only those fresh outputs:

```bash
python3 -m src.main --refresh-sources
```

Fresh source outputs are written here:

```text
data/source_outputs/
```

Then the ranker reads only those refreshed files.

Available refresh source names:

```text
weraveyou
edmtunes
edmcom
submithub
spotify_playlists
soundcloud_playlists
top_artisits_recent
```

`top_artisits_recent` is available but no longer included in the default refresh. It uses Spotify's `/v1/artists/{artist_id}/albums` endpoint once or more per artist, which can mean thousands of calls when scanning the full artist CSV.
Before using it, build `Top_Artisits/master_artist_list.csv` with SoundCloud profile fields:

```bash
cd ../Top_Artisits
python3 -m src.main --soundcloud-search --output master_artist_list.csv
```

Then `top_artisits_recent` can continue remaining artists through SoundCloud profile tracks if Spotify stops during the scan.

Useful refresh options:

```bash
python3 -m src.main --refresh-sources --skip-api-sources
python3 -m src.main --refresh-sources --refresh-source weraveyou --refresh-source edmtunes
python3 -m src.main --refresh-sources --include-artist-profile-scan
python3 -m src.main --refresh-sources --refresh-source top_artisits_recent
python3 -m src.main --refresh-sources --continue-on-source-error
```

The ranking step itself is API-free. `--refresh-sources` can call APIs because it reruns the Spotify and SoundCloud source scripts. If Spotify is rate-limiting, use `--skip-source spotify_playlists` or `--skip-api-sources`.

For normal weekly runs, the safest refresh command is:

```bash
python3 -m src.main \
  --refresh-sources \
  --continue-on-source-error \
  --output data/ranked_releases_refreshed.json \
  --unique-output data/ranked_releases_refreshed_unique.json
```

`top_artisits_recent` is the heavy Spotify artist-profile scan. It can check hundreds of artist album pages, so it is opt-in only.
