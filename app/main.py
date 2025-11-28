import logging
from datetime import datetime, timedelta
from threading import Lock
from typing import Dict, List

import feedparser
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from textblob import TextBlob


logger = logging.getLogger("stablecoin_news")
logging.basicConfig(level=logging.INFO)

STABLECOIN_KEYWORDS = [
    "stablecoin",
    "usdc",
    "usdt",
    "tether",
    "dai",
    "circle",
]

REGULATOR_POSITIVE_KEYWORDS = [
    "regulation",
    "compliance",
    "oversight",
    "policy",
    "risk management",
    "aml",
    "anti-money laundering",
    "kyc",
    "licence",
    "license",
    "central bank",
    "cbdc",
    "basel",
    "governance",
    "guidance",
    "framework",
    "supervision",
    "report",
    "consultation",
    "pilot",
    "sandbox",
    "disclosure",
    "transparency",
    "prudential",
    "enforcement",
    "regulator",
    "settlement",
    "comptroller",
    "treasury",
]

GENERAL_POLICY_TERMS = [
    "policy",
    "law",
    "bill",
    "legislation",
    "standard",
    "guideline",
    "consultation",
    "supervisory",
    "oversight",
    "risk",
    "framework",
    "white paper",
    "report",
    "discussion paper",
    "consultation paper",
    "governance",
    "auditing",
    "settlement",
]

NEGATIVE_TERMS = [
    "hack",
    "scam",
    "fraud",
    "ban",
    "collapse",
    "lawsuit",
    "pump",
    "dump",
    "moon",
]

CACHE_WINDOW_HOURS = 48

RSS_FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "CryptoSlate": "https://cryptoslate.com/feed/",
    "IMF Fintech": "https://www.imf.org/external/rss/feeds.aspx?category=FINTECH",
    "BIS Innovation Hub": "https://www.bis.org/bcbs/rss/index.xml",
    "ECB News": "https://www.ecb.europa.eu/rss/press.xml",
    "FATF News": "https://www.fatf-gafi.org/rss/en/morenews/",
    "Treasury FinCEN": "https://home.treasury.gov/rss/finCEN",
    "Chainalysis": "https://blog.chainalysis.com/rss/",
    "Elliptic": "https://www.elliptic.co/blog/rss.xml",
    "TRM Labs": "https://www.trmlabs.com/blog?format=rss",
    "BIS Speeches": "https://www.bis.org/list/speeches_rss.page",
    "MAS News": "https://www.mas.gov.sg/rss?type=all",
    "FCA News": "https://www.fca.org.uk/news/rss.xml",
    "HKMA News": "https://www.hkma.gov.hk/media/eng/rss/rss.xml",
    "OFAC Updates": "https://home.treasury.gov/rss/press-center/press-releases",
}


curated_articles: List[Dict] = []
article_lock = Lock()
scheduler = BackgroundScheduler(timezone="UTC")

app = FastAPI(title="Stablecoin Positive News API", version="1.0.0")


def includes_stablecoin_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in STABLECOIN_KEYWORDS)


def includes_regulator_positive_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in REGULATOR_POSITIVE_KEYWORDS)


def has_regulator_context(text: str) -> bool:
    lowered = text.lower()
    if includes_regulator_positive_keyword(lowered):
        return True
    hits = sum(term in lowered for term in GENERAL_POLICY_TERMS)
    return hits >= 2


def contains_negative_term(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in NEGATIVE_TERMS)


def analyze_sentiment(text: str) -> float:
    return TextBlob(text).sentiment.polarity


def fetch_and_filter_articles() -> List[Dict]:
    articles: List[Dict] = []
    seen_titles = set()

    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
        except Exception as exc:  # pragma: no cover - network errors
            logger.warning("Failed to fetch %s: %s", source, exc)
            continue

        for entry in feed.entries:
            title = entry.get("title", "").strip()
            if not title or title.lower() in seen_titles:
                continue

            summary = entry.get("summary", "").strip()
            content_for_filter = f"{title} {summary}"

            if not includes_stablecoin_keyword(content_for_filter):
                continue

            sentiment = analyze_sentiment(content_for_filter)
            if sentiment < 0.1:
                continue

            if contains_negative_term(content_for_filter) and sentiment < 0.3:
                continue

            if not has_regulator_context(content_for_filter):
                continue

            article = {
                "title": title,
                "summary": summary,
                "url": entry.get("link", "").strip(),
                "source": source,
                "published": entry.get("published", datetime.utcnow().isoformat()),
                "sentiment": sentiment,
                "fetched_at": datetime.utcnow().isoformat(),
            }
            articles.append(article)
            seen_titles.add(title.lower())

    return articles


def update_articles():
    logger.info("Refreshing stablecoin articles")
    new_articles = fetch_and_filter_articles()
    with article_lock:
        cutoff = datetime.utcnow() - timedelta(hours=CACHE_WINDOW_HOURS)
        curated_articles[:] = [
            article
            for article in curated_articles
            if datetime.fromisoformat(article.get("fetched_at", datetime.utcnow().isoformat()))
            >= cutoff
        ]
        existing_titles = {article["title"].lower() for article in curated_articles}
        for article in new_articles:
            title_key = article["title"].lower()
            if title_key in existing_titles:
                continue
            curated_articles.append(article)
            existing_titles.add(title_key)
    logger.info("Stored %d articles", len(new_articles))


@app.on_event("startup")
async def startup_event():
    if not scheduler.running:
        scheduler.add_job(update_articles, "interval", hours=1, next_run_time=datetime.utcnow())
        scheduler.start()
    await run_in_threadpool(update_articles)


@app.on_event("shutdown")
async def shutdown_event():
    if scheduler.running:
        scheduler.shutdown(wait=False)


@app.get("/positive-news")
def get_positive_news():
    with article_lock:
        return {"count": len(curated_articles), "articles": curated_articles}

