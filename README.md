# Stage Scraper

Python script to automate internship hunting in France. Scrapes job listings from **Welcome to the Jungle** and **HelloWork**, filters by city (Paris & Strasbourg), removes duplicates across platforms, and exports a clean CSV.

Built for my own search (summer 2026 internship) because manually checking multiple job boards every morning isn't sustainable.

## How it works

Two different approaches depending on the site:

- **WTTJ**: the site is a React app — the raw HTML is empty on load. By inspecting network requests (Chrome DevTools → Network tab), I found their internal API. We query JSON directly → no headless browser needed, much faster and more reliable.

- **HelloWork**: classic server-rendered site (HTML contains the listings). Parsed with BeautifulSoup.

The script includes random delays between requests and a realistic User-Agent to avoid getting blocked.

## Installation

```bash
git clone https://github.com/[YOUR-USERNAME]/stage-scraper.git
cd stage-scraper
pip install -r requirements.txt
```

## Usage

```bash
# default search (stage opérateur, Paris + Strasbourg)
python scraper.py

# custom search
python scraper.py -q "stage logistique"

# more results
python scraper.py -p 5

# filter results by keywords
python scraper.py -f production usine maintenance

# single source
python scraper.py -s wttj
```

Results are exported to `output/` as CSV (Excel-compatible).

## Project structure

```
stage-scraper/
├── scraper.py          # all the code (scraping, dedup, export)
├── output/             # generated CSVs (gitignored)
├── requirements.txt
└── README.md
```

## Stack

- Python 3.10+
- requests (HTTP requests)
- BeautifulSoup4 (HTML parsing for HelloWork)
- pandas (CSV export)

## TODO

- [ ] Add France Travail (they have a public API)
- [ ] Email notifications when new listings match
- [ ] Add a --watch mode that re-runs the scraper every X hours
