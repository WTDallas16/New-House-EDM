# 1001Tracklists House Chart Extractor

Extracts track candidates from the sidebar charts on:

```text
https://www.1001tracklists.com/genre/house/index.html
```

This scraper intentionally ignores the main page list because those rows are DJ sets, radio shows, and tracklists. It only reads the sidebar chart sections:

- `Top House Newcomer Tracks`
- `Most Heard House Tracks`

The output matches the shared release-candidate schema used by the other source folders.

## Run

```bash
python -m src.main \
  --source 1001tracklists \
  --url "https://www.1001tracklists.com/genre/house/index.html" \
  --lookback-days 14 \
  --max-pages 5 \
  --output data/extracted_releases.json
```

The command also writes `data/extracted_releases.csv` unless you pass `--csv-output`.

For this source, `--max-pages` is treated as the maximum number of sidebar chart pages to request. Page 1 is the static page content; later pages are fetched from the site's chart AJAX endpoint when the page exposes the needed `StatisticUpdater` parameters.

If the genre page is blocked by Turnstile, the scraper now falls back by default to unblocked 1001Tracklists chart pages:

- `Daily Newcomer Tracks`
- `Most Heard Tracks`
- `Weekly DJ Support Tracks`

That fallback keeps the pull usable without browser automation, but it is broader than the House genre sidebar. Use `--no-chart-fallback` if you would rather fail instead of using the broader chart source.

## If You See Turnstile

1001Tracklists sometimes blocks non-browser requests with a Turnstile/human-validation page. When that happens, the scraper cannot fetch the chart anonymously from the terminal.

Recommended option: use your validated browser session.

1. Open `https://www.1001tracklists.com/genre/house/index.html` in your browser.
2. Complete the site check if prompted.
3. Open DevTools, reload the page, click the document request, and copy its `Cookie` request header.
4. Run:

```bash
export TRACKLISTS1001_COOKIE='<paste cookie here>'

python3 -m src.main \
  --source 1001tracklists \
  --url "https://www.1001tracklists.com/genre/house/index.html" \
  --lookback-days 14 \
  --max-pages 5 \
  --output data/extracted_releases.json
```

Alternative option: save the browser-rendered page.

1. Open the genre page in your browser after passing the site check.
2. Save the page HTML to something like `data/1001tracklists-house.html`.
3. Run:

```bash
python -m src.main \
  --source 1001tracklists \
  --url "https://www.1001tracklists.com/genre/house/index.html" \
  --html-input data/1001tracklists-house.html \
  --output data/extracted_releases.json
```

The saved HTML path only parses what is present in the saved page. The cookie option is better when you want `Show More` pages too.

## Source Behavior

`src/scrapers/tracklists1001.py` fetches the genre page with browser-like headers and parses document text/link tokens with BeautifulSoup. It looks for the named sidebar chart headings and only converts ranked track rows from those sections.

When static HTML includes the chart `Show More` loader parameters, the scraper calls `/ajax/get_tracks.php` for additional pages and parses those returned row fragments with the same sidebar-only logic.

If 1001Tracklists returns its Turnstile/forwarding page, the scraper exits with a clear error instead of scraping the wrong content.

With the default `--chart-fallback`, a Turnstile response from the genre page no longer stops the run; the scraper logs a warning and uses the unblocked chart pages instead.

## Output Format

Each extracted track uses the shared schema:

```json
{
  "artist": "Piem & Mat.Joe",
  "track_or_project_title": "Let The Beat",
  "release_type": "track",
  "confidence_score": 0.84,
  "extraction_method": "1001tracklists_sidebar_chart",
  "source_article_title": "Piem & Mat.Joe - Let The Beat",
  "source_article_url": "https://www.1001tracklists.com/track/...",
  "source_name": "1001Tracklists",
  "article_date": null,
  "embedded_music_links": [],
  "open_graph": {
    "chart_name": "Most Heard House Tracks",
    "chart_rank": "1",
    "chart_window": "track-player opens in the last 7 days",
    "chart_metric": "listener_track_player_opens",
    "label": "ELROW",
    "label_url": "https://www.1001tracklists.com/label/..."
  },
  "release_article": true
}
```

1001Tracklists-specific chart metadata is stored in `open_graph` so the top-level schema stays compatible across all sources.

## Tuning

Edit these values in `src/scrapers/tracklists1001.py`:

- `CHARTS` to add or remove sidebar chart sections.
- `_release_type` to change remix/rework detection.
- Chart confidence values inside `CHARTS`.
- `SECTION_STOP_PREFIXES` if the page layout changes.

Run tests after tuning:

```bash
python -m pytest
```
