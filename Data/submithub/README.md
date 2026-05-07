# SubmitHub Popular Chart Extractor

Extracts popular House / Techno tracks from SubmitHub's popular chart and writes the same release-candidate schema used by the We Rave You, EDMTunes, and EDM.com projects.

SubmitHub is not a blog, so this scraper does not classify article cards or open article pages. It reads the chart data directly, then converts each charted song into a release candidate.

## Run

```bash
python -m src.main \
  --source submithub \
  --url "https://www.submithub.com/popular?genre=House%20%2F%20Techno" \
  --lookback-days 14 \
  --max-pages 100 \
  --output data/extracted_releases.json
```

The command also writes `data/extracted_releases.csv` unless you pass `--csv-output`.

For SubmitHub, `--max-pages` is used as the maximum number of chart songs to request. The site has no normal pagination for this chart.

## Source Behavior

SubmitHub renders the popular chart with its client app, so the song rows are not available in the static HTML. `src/scrapers/submithub.py` connects to SubmitHub's Meteor DDP endpoint and calls the same chart methods used by the page:

- `clientGenres` to find child genres for the selected parent genre.
- `newPopular` to fetch ranked chart summaries with points, approvals, RGB bonus, response counts, and tags.
- `popularTracks` to hydrate those chart rows into song metadata such as artist, title, release date, label, slug, and streaming URL.

The default URL targets:

```text
House / Techno
```

If the URL has a different `genre=` query value, the scraper uses that genre instead.

## Output Format

Each row keeps the shared schema:

```json
{
  "artist": "Jordan Arts",
  "track_or_project_title": "Moving On",
  "release_type": "track",
  "confidence_score": 0.95,
  "extraction_method": "submithub_chart",
  "source_article_title": "Jordan Arts - Moving On",
  "source_article_url": "https://www.submithub.com/song/jordan-arts-moving-on",
  "source_name": "SubmitHub",
  "article_date": "2026-04-23",
  "embedded_music_links": [
    "https://open.spotify.com/track/1amm9C91oshwWRbsDwtcaf"
  ],
  "open_graph": {
    "chart_rank": "1",
    "popular_points": "72",
    "hot_or_not_likes": "91",
    "curator_approvals": "91",
    "rgb_bonus": "0",
    "approval_responses": "143",
    "country": "GB",
    "genres": "Tribal / Afro House, Melodic House",
    "label": "Artscape Records",
    "submitHub_track_id": "Fswbhi7NojNqoF6xb"
  },
  "release_article": true
}
```

SubmitHub-specific chart details are stored inside `open_graph` so later analysis can compare all sources without changing the shared top-level fields.

## How Extraction Works

1. Decode the `genre=` value from the chart URL.
2. Fetch SubmitHub's genre list and map the parent genre to its child genres.
3. Request popular chart rows for those child genres.
4. Request hydrated song data for the chart track IDs.
5. Build release candidates from artist, title, release date, source URL, label, chart rank, points, likes, and tags.
6. Drop rows with missing artist/title or future release dates.
7. Deduplicate by normalized artist, track title, and release type.

## Tuning

Edit these helpers in `src/scrapers/submithub.py`:

- `_popular_query` for chart filters such as minimum points or recent activity window.
- `_popular_tracks_query` for release-date window filtering.
- `_confidence` for confidence scoring.
- `_release_type` if SubmitHub exposes more release-type metadata in the future.

Run tests after tuning:

```bash
python -m pytest
```
