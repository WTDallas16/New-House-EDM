# EDM.com Release Extractor

Scrapes EDM.com Music Releases posts and extracts likely newly released songs, tracks, EPs, albums, remixes, and reworks. Output matches the We Rave You and EDMTunes extractors so all sources can be compared or merged later.

## Run

```bash
python -m src.main \
  --source edmcom \
  --url "https://edm.com/music-releases/" \
  --lookback-days 14 \
  --max-pages 5 \
  --output data/extracted_releases.json
```

The command also writes `data/extracted_releases.csv` unless you pass `--csv-output`.

For a quick parser-only smoke test without opening article pages:

```bash
python -m src.main \
  --source edmcom \
  --url "https://edm.com/music-releases/" \
  --lookback-days 14 \
  --max-pages 5 \
  --output data/extracted_releases.json \
  --skip-enrichment
```

## Source Behavior

`src/scrapers/edmcom.py` first tries EDM.com's published RSS feed:

```text
https://edm.com/.rss/full/
```

The feed is sitewide, so the scraper keeps only URLs under `/music-releases/`. It then fetches the archive page:

```text
https://edm.com/music-releases/
```

EDM.com has a "Load More" button rather than ordinary pagination. The scraper supports explicit load-more links or data endpoints when they are present in the returned HTML, and it can parse HTML or JSON load-more responses. `--max-pages` is treated as the maximum number of archive/load-more batches.

## Output Format

Each release candidate keeps the shared schema:

```json
{
  "artist": "TroyBoi",
  "track_or_project_title": "HUSH",
  "release_type": "single",
  "confidence_score": 0.6,
  "extraction_method": "regex",
  "source_article_title": "TroyBoi and Daya Let the Groove Do the Talking on New Single, ‘HUSH’",
  "source_article_url": "https://edm.com/music-releases/troyboi-daya-hush/",
  "source_name": "EDM.com",
  "article_date": "2026-04-24",
  "embedded_music_links": [],
  "open_graph": {},
  "release_article": true
}
```

## How Extraction Works

1. The EDM.com scraper merges RSS items with archive/load-more article cards.
2. `src/extraction/classifier.py` filters release posts using title/snippet signals and excludes roundups like Fresh Picks and On-Deck Circle.
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

