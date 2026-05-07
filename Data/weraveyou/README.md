# EDM Release Extractor

Scrapes EDM/house music blog category pages and extracts only likely new music releases: singles, tracks, EPs, albums, remixes, and reworks. The initial source is We Rave You's House category.

## Run

```bash
python -m src.main \
  --source weraveyou \
  --url "https://weraveyou.com/category/music/house/" \
  --lookback-days 14 \
  --max-pages 10 \
  --output data/extracted_releases.json
```

The command also writes `data/extracted_releases.csv` unless you pass `--csv-output`.

For a quick parser-only smoke test without opening article pages:

```bash
python -m src.main --source weraveyou --url "https://weraveyou.com/category/music/house/" --skip-enrichment
```

The We Rave You scraper follows category pagination at `/page/<number>/`. It stops when a page has no new article cards, when `--max-pages` is reached, or when it sees a dated article older than the `--lookback-days` cutoff.

## How Extraction Works

The pipeline is layered on purpose:

1. `src/scrapers/weraveyou.py` fetches the category page and extracts article cards with title, URL, source, category, date, and nearby snippet.
2. `src/extraction/classifier.py` scores release intent using include signals such as `new single`, `drops`, `unveils`, `remix`, and `Listen`.
3. The same classifier blocks non-release topics such as festivals, lineups, interviews, anniversaries, rankings, business news, playlists, radio shows, and live sets. Exclusion terms are allowed only when the title also clearly says a release was dropped/shared/unveiled.
4. `src/enrich/article_enricher.py` opens included article pages and extracts OpenGraph metadata, JSON-LD, body text, release-language matches, and embedded Spotify, SoundCloud, Apple Music, YouTube, or Beatport links.
5. `src/extraction/parser.py` combines title regexes, body patterns, metadata, embedded-player evidence, release-type inference, and confidence scoring.
6. `src/extraction/normalize.py` deduplicates by normalized artist, project title, and release type.

## Confidence Score

The score follows the requested idea:

- `+0.25` for `Listen`
- `+0.25` for release keywords
- `+0.20` for quoted song/project title
- `+0.20` for embedded music links
- `+0.10` for body release confirmation
- `-0.30` for exclusion signals unless the article clearly says a release was dropped/shared/unveiled

Scores are capped from `0.0` to `1.0`.

## Example Output

```json
[
  {
    "artist": "New Wing",
    "track_or_project_title": "Sippin",
    "release_type": "single",
    "confidence_score": 0.8,
    "extraction_method": "regex+embedded_player",
    "source_article_title": "New Wing unveils captivating new single ‘Sippin’: Listen",
    "source_article_url": "https://weraveyou.com/...",
    "source_name": "We Rave You",
    "article_date": "2026-03-20"
  }
]
```

## Add A New Blog Source

Create a scraper in `src/scrapers/` that subclasses `BaseScraper` and returns `ArticleCard` instances from `scrape_category`. Then register it in `SCRAPERS` inside `src/main.py`.

Keep source-specific HTML parsing in the scraper. Keep release classification and parsing in `src/extraction/` so new sources benefit from the same tuned rules.

## Tune Keywords

Edit `RELEASE_KEYWORDS`, `EXCLUDE_KEYWORDS`, and `CLEAR_DROP_PATTERNS` in `src/extraction/classifier.py`.

Edit title/body extraction patterns and release type inference in `src/extraction/parser.py`.

Run tests after tuning:

```bash
python -m pytest
```
