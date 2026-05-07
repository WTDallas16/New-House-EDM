# Pull and Push

Final workflow for the New House pipeline:

1. Refresh every working music source in a rate-limit-friendly order.
2. Rank all fresh JSON outputs with the shared `Data/Master_Ranking` scorer.
3. Resolve Spotify and SoundCloud links for the top tracks.
4. Optionally empty and repopulate the `New House` playlists on Spotify and SoundCloud.

By default this tool is a dry run. It writes rankings and link-resolution reports, but it does not modify playlists unless you pass `--push`.

The default lookback window is the past 7 days. The final ranking step also filters by `article_date`, so older tracks are excluded even if a source returns more history than requested.

## Run

```bash
cd "/Users/WillyTardif/Documents/New House/Pull and Push"
python3 -m src.main
```

Change the window if needed:

```bash
python3 -m src.main --lookback-days 7
```

Outputs:

- `data/source_outputs/*.json`
- `data/ranked_releases.json`
- `data/ranked_releases_unique.json`
- `data/top_50_resolved.json`
- `data/soundcloud_resolved.json`
- `data/spotify_link_backlog.json`
- `data/push_report.json`

## Push to Playlists

```bash
python3 -m src.main --push
```

This finds or creates playlists named `New House`, clears their current tracks, then adds the resolved top 50.

## Source Order

The default refresh order is:

1. `edmcom`
2. `edmtunes`
3. `soundcloud_playlists`
4. `spotify_playlists`
5. `submithub`
6. `weraveyou`
7. `1001tracklists`
8. `followed_soundcloud`
9. `top_artisits_recent`

The original source list had `SoundCloud_Playlists` twice, so slot 4 is treated as `Spotify_Playlists` to keep all current sources included.

## Useful Options

Use existing source output JSONs:

```bash
python3 -m src.main --skip-refresh
```

Run only some sources:

```bash
python3 -m src.main --refresh-source edmcom --refresh-source edmtunes
```

Skip a source:

```bash
python3 -m src.main --skip-source top_artisits_recent
```

Avoid API-backed refreshes:

```bash
python3 -m src.main --skip-api-sources
```

Run Top_Artisits through SoundCloud profile data only:

```bash
python3 -m src.main --top-artisits-soundcloud-only
```

Tune final playlist curation:

```bash
python3 -m src.main --max-per-artist 2 --candidate-pool-size 150
```

The Spotify playlist uses the curated top 50. The SoundCloud playlist uses those same ranked candidates first, then backfills from the larger candidate pool until it has up to 50 valid SoundCloud track IDs. Increase the pool if SoundCloud still has fewer than 50:

```bash
python3 -m src.main --candidate-pool-size 250 --soundcloud-target-count 50
```

By default, the final playlist excludes slowed/sped-up/nightcore/rework/remaster/cover style variants, skips tracks whose ISRC year predates the current release window, and keeps at most 2 tracks per primary artist. VIP edits/mixes are allowed. To disable the speed-variant filter:

```bash
python3 -m src.main --allow-speed-variants
```

To allow older ISRC years:

```bash
python3 -m src.main --allow-old-isrc-years
```

Rebuild the SoundCloud-followed artist CSV:

```bash
python3 -m src.main --refresh-followed-artists
```

## Spotify Rate Limits

If Spotify rate limits link resolution, the tool stops making extra Spotify search calls for that run, keeps any direct Spotify IDs it already has, and writes unresolved items to:

```text
data/spotify_link_backlog.json
```

The next run reuses `data/link_cache.json`, so already resolved links do not need another API call.

## SoundCloud Link Matching

SoundCloud requests include:

```text
access=playable,preview,blocked
```

For missing SoundCloud links, the resolver tries multiple search queries, including the full artist string, primary artist aliases, and title-only searches. This helps collaboration strings like `Jax Jones, D Double E` match uploader profiles like `Jax Jones`.

## Credentials

The tool reuses credentials from:

- `Data/Spotify_Playlists/.env`
- `Data/SoundCloud_Playlists/.env`

Spotify playlist writing needs scopes:

```text
playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public
```

SoundCloud playlist writing uses the OAuth token file configured by `SC_TOKEN_FILE` or `sc_token.json`.

## GitHub Actions Token Refresh

The weekly workflow restores token caches from GitHub Secrets before the run:

- `SPOTIFY_TOKEN_CACHE_B64`
- `SC_TOKEN_B64`

At the end of the run, it writes the refreshed token files back to those same secrets. To allow that final write-back step, add a repository secret named:

```text
REPO_SECRETS_TOKEN
```

Use a fine-grained GitHub personal access token that can update Actions secrets for this repository. If `REPO_SECRETS_TOKEN` is not set, the workflow still runs, but refreshed Spotify/SoundCloud token files are only available inside that one temporary runner and will not be saved for the next week.

On macOS, you can create the initial base64 secret values with:

```bash
base64 -i "Pull and Push/.spotify_token_cache" | tr -d '\n'
base64 -i "Data/SoundCloud_Playlists/sc_token.json" | tr -d '\n'
```

Paste those into `SPOTIFY_TOKEN_CACHE_B64` and `SC_TOKEN_B64`. After that, the workflow updates them automatically after each run.
