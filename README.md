# Stablecoin Positive News API

FastAPI service that aggregates stablecoin-related news from CoinDesk, Cointelegraph, and CryptoSlate RSS feeds, filters for neutral/positive sentiment, and exposes them via a `/positive-news` endpoint.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Optional: improve TextBlob accuracy for sentiment
python -m textblob.download_corpora
```

## Running

```bash
uvicorn app.main:app --reload
```

The background scheduler refreshes feeds every hour. Visit `http://127.0.0.1:8000/positive-news` to retrieve the current curated articles.

### Regulator-friendly filtering

Articles are biased toward compliance/oversight themes but now strike a balance: keyword scoring prioritizes regulator language (while allowing neutral policy terms), hype/negative vocabulary is filtered unless sentiment is strongly positive, and the cache holds the last 48 hours of qualifying stories (across feeds that include BIS, IMF, FATF, Chainalysis, Elliptic, TRM Labs, MAS, FCA, and more) so you can review a broader window of news. Only items with clearly positive sentiment (TextBlob polarity ≥ 0.1) are returned, helping compliance teams focus on constructive developments.

