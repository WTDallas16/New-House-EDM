# New House Music Pipeline

This repository collects new house and EDM releases from blogs, playlist sources, artist profiles, SoundCloud follows, and chart-style sources, then ranks the candidates and optionally refreshes Spotify and SoundCloud playlists named `New House`.

The main entrypoint is:

```text
Pull and Push/
```

Most folders under `Data/` are standalone source extractors. Each source writes JSON in the same shared release-candidate format so the final ranking step can compare songs across sources.

## What It Does

1. Pulls new releases from supported sources.
2. Normalizes them into a shared JSON schema.
3. Deduplicates songs across sources.
4. Scores each song using source quality, recency, popularity, artist metrics, chart metadata, confidence, and cross-source sightings.
5. Resolves Spotify and SoundCloud links.
6. Builds curated playlist payloads.
7. Optionally clears and repopulates Spotify/SoundCloud playlists named `New House`.

The default final workflow uses a 7-day lookback window.

## Repository Layout

```text
Data/
  1001tracklists/                  1001Tracklists house chart/sidebar extractor
  edm.com/                         EDM.com music releases scraper
  edmtunes/                        EDMTunes music scraper/RSS extractor
  Master_Ranking/                  Shared ranking engine
  New tracks from people I follow/ SoundCloud followed-artist extractor
  SoundCloud_Playlists/            SoundCloud playlist extractor
  Spotify_Playlists/               Spotify playlist extractor
  submithub/                       SubmitHub popular House/Techno extractor
  Top_Artisits/                    MusicMetricsVault top-artist and recent-track tools
  weraveyou/                       We Rave You house category scraper

Pull and Push/                     Final orchestration, ranking, resolving, and playlist push
.github/workflows/                Weekly GitHub Actions workflow
```

`Top_Artisits` is intentionally spelled that way because the existing folder and scripts use that name.

## Quick Start

Install dependencies for the final workflow:

```bash
cd "/Users/WillyTardif/Documents/New House/Pull and Push"
python3 -m pip install -r requirements.txt
```

Run a dry run:

```bash
python3 -m src.main
```

Push the current ranked songs to Spotify and SoundCloud:

```bash
python3 -m src.main --push
```

Use existing source JSONs without refreshing every source:

```bash
python3 -m src.main --skip-refresh
```

Tune the SoundCloud backfill pool:

```bash
python3 -m src.main --candidate-pool-size 250 --soundcloud-target-count 50
```

## Main Outputs

The final workflow writes:

```text
Pull and Push/data/source_outputs/*.json
Pull and Push/data/ranked_releases.json
Pull and Push/data/ranked_releases_unique.json
Pull and Push/data/top_50_resolved.json
Pull and Push/data/soundcloud_resolved.json
Pull and Push/data/spotify_link_backlog.json
Pull and Push/data/push_report.json
```

Each source folder also writes its own local outputs, usually under `data/`.

## Shared Release Format

Source outputs use a common shape like:

```json
{
  "artist": "Artist Name",
  "track_or_project_title": "Track Title",
  "release_type": "track",
  "confidence_score": 0.9,
  "extraction_method": "source_specific_method",
  "source_article_title": "Original source title",
  "source_article_url": "https://example.com/item",
  "source_name": "Source Name",
  "article_date": "2026-05-01",
  "embedded_music_links": [],
  "open_graph": {},
  "release_article": true
}
```

Some sources include additional metadata such as Spotify IDs, SoundCloud IDs, chart ranks, monthly listeners, likes, points, or popularity values.

## Ranking and Curation

The ranking system considers:

- source quality
- recency inside the lookback window
- extraction confidence
- Spotify popularity and artist metrics when available
- SoundCloud playback, likes, reposts, and release dates when available
- SubmitHub points and hearts when available
- 1001Tracklists chart metadata
- duplicate sightings across different sources

Final playlist curation also:

- keeps at most 2 tracks per primary artist
- excludes slowed, sped-up, nightcore, rework, remaster, and cover-style variants by default
- keeps VIP edits and VIP mixes
- skips tracks whose ISRC year predates the current release window by default

Useful options:

```bash
python3 -m src.main --max-per-artist 2
python3 -m src.main --allow-speed-variants
python3 -m src.main --allow-old-isrc-years
```

## Credentials

Local credentials live in source-specific `.env` files. The final workflow reuses:

```text
Data/Spotify_Playlists/.env
Data/SoundCloud_Playlists/.env
```

Spotify playlist writing needs scopes similar to:

```text
playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public
```

SoundCloud uses:

```text
Data/SoundCloud_Playlists/sc_token.json
```

That token file is treated as the canonical SoundCloud token for the final workflow.

## GitHub Actions

The weekly workflow is:

```text
.github/workflows/new-house-weekly.yml
```

It runs Friday at 10:07 AM America/New_York and can also be triggered manually from the GitHub Actions tab.

Scheduled runs use `--continue-on-source-error`, so one flaky source does not stop the full weekly playlist update. This is especially useful for 1001Tracklists, which can occasionally time out or challenge GitHub-hosted runners.

Required repository secrets:

```text
SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET
SPOTIFY_REDIRECT_URI
SPOTIFY_SCOPE
SC_CLIENT_ID
SC_CLIENT_SECRET
SPOTIFY_TOKEN_CACHE_B64
SC_TOKEN_B64
REPO_SECRETS_TOKEN
```

`REPO_SECRETS_TOKEN` is used only so the workflow can write refreshed token cache files back into GitHub Secrets after each run. Without it, the workflow can still run, but refreshed tokens will not persist to the next scheduled run.

Create the initial base64 token secrets locally:

```bash
base64 -i "Pull and Push/.spotify_token_cache" | tr -d '\n'
base64 -i "Data/SoundCloud_Playlists/sc_token.json" | tr -d '\n'
```

Base64 values may end in `=` or `==`. They should not end in `%`. If your terminal shows a trailing `%`, that is usually the shell prompt/missing-newline marker and should not be copied into the GitHub secret.

To avoid accidentally copying the prompt marker on macOS, copy directly to the clipboard:

```bash
base64 -i "Pull and Push/.spotify_token_cache" | tr -d '\n' | pbcopy
base64 -i "Data/SoundCloud_Playlists/sc_token.json" | tr -d '\n' | pbcopy
```

Paste those values into:

```text
SPOTIFY_TOKEN_CACHE_B64
SC_TOKEN_B64
```

## Source Docs

Each source has its own README with setup and source-specific commands:

- `Data/1001tracklists/README.md`
- `Data/edm.com/README.md`
- `Data/edmtunes/README.md`
- `Data/Master_Ranking/README.md`
- `Data/New tracks from people I follow/README.md`
- `Data/SoundCloud_Playlists/README.md`
- `Data/Spotify_Playlists/README.md`
- `Data/submithub/README.md`
- `Data/Top_Artisits/README.md`
- `Data/weraveyou/README.md`
- `Pull and Push/README.md`

## Tests

Run tests inside an individual project folder:

```bash
cd "/Users/WillyTardif/Documents/New House/Data/weraveyou"
python3 -m pytest
```

Or run a source-specific test suite from any other source folder that has tests.

## Notes

- The final ranking step is designed to reuse cached link matches where possible.
- Spotify rate limits are handled by stopping extra Spotify lookup calls for that run and writing unresolved items to `spotify_link_backlog.json`.
- SoundCloud requests include `access=playable,preview,blocked` where the API supports it.
- 1001Tracklists may time out or return a browser challenge from GitHub Actions; scheduled runs continue without that source if it fails.
- `Data/Top_Artisits/master_artist_list.csv` is ignored from git because it is generated data. If it is missing in GitHub Actions, the final workflow rebuilds it before scanning recent artist tracks.
