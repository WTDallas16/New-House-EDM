# EDMTunes Release Extractor

Scrapes EDMTunes Music posts and extracts likely newly released songs, tracks, EPs, albums, remixes, and reworks. Output matches the We Rave You extractor schema so both sources can be compared or merged later.

## Run

```bash
python -m src.main \
  --source edmtunes \
  --url "https://www.edmtunes.com/music/" \
  --lookback-days 14 \
  --max-pages 10 \
  --output data/extracted_releases.json
```

The command also writes `data/extracted_releases.csv` unless you pass `--csv-output`.

For a quick parser-only smoke test without opening article pages:

```bash
python -m src.main \
  --source edmtunes \
  --url "https://www.edmtunes.com/music/" \
  --lookback-days 14 \
  --max-pages 3 \
  --output data/extracted_releases.json \
  --skip-enrichment
```

## Source Behavior

`src/scrapers/edmtunes.py` first reads the RSS feed at:

```text
https://www.edmtunes.com/music/feed/
```

RSS entries provide useful timestamps, snippets, and genre/tag labels. The scraper then walks the HTML archive pages:

```text
https://www.edmtunes.com/music/
https://www.edmtunes.com/music/page/2/
https://www.edmtunes.com/music/page/3/
```

It stops when a page has no article cards, when `--max-pages` is reached, or when it sees dated articles older than `--lookback-days`.

## Output Format

Each release candidate keeps the shared schema:

```json
{
  "artist": "GorillaT",
  "track_or_project_title": "BOOM",
  "release_type": "single",
  "confidence_score": 0.8,
  "extraction_method": "regex+embedded_player",
  "source_article_title": "GorillaT Goes Full Send with Latest Single ‘BOOM’",
  "source_article_url": "https://www.edmtunes.com/...",
  "source_name": "EDMTunes",
  "article_date": "2026-04-24",
  "embedded_music_links": [],
  "open_graph": {},
  "release_article": true
}
```

## How Extraction Works

1. The EDMTunes scraper merges RSS metadata with paginated archive cards.
2. `src/extraction/classifier.py` filters release posts using title/snippet release signals and non-release exclusions.
3. `src/enrich/article_enricher.py` opens included articles and extracts OpenGraph metadata, JSON-LD, body text, release-language matches, and embedded Spotify, SoundCloud, Apple Music, YouTube, or Beatport links.
4. `src/extraction/parser.py` extracts artist, title, release type, confidence, and extraction method using title patterns, article body patterns, and metadata.
5. `src/extraction/normalize.py` deduplicates by normalized artist, project title, and release type.

## Tune Keywords

Edit include/exclude rules in `src/extraction/classifier.py`.

Edit title/body extraction patterns and release type inference in `src/extraction/parser.py`.

Run tests after tuning:

```bash
python -m pytest
```

