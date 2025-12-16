import logging
from datetime import datetime, timedelta
from threading import Lock
from typing import Dict, List
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
import requests
from textblob import TextBlob
import nest_asyncio
import uvicorn
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
import os
from pymongo import MongoClient

from utils import parse_description

load_dotenv()

logger = logging.getLogger("stablecoin_news")
logging.basicConfig(level=logging.INFO)


client = MongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017/"))
db = client[os.getenv("MONGODB_DB_NAME", "news_db")]
mongo_db_client = db[os.getenv("MONGODB_COLLECTION_NAME", "articles")]

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
    "ECB News": "https://www.ecb.europa.eu/rss/press.xml",
    "Chainalysis": "https://blog.chainalysis.com/rss/",
    "Elliptic": "https://www.elliptic.co/blog/rss.xml",
    "FCA News": "https://www.fca.org.uk/news/rss.xml",
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
        print("Running for Source", url)
        response = requests.get(url)
        response.raise_for_status()   # ensure request succeeded

        # Parse XML text
        root = ET.fromstring(response.text)
        channel = root.find("channel")

        # Get all <item> tags
        items = channel.findall("item")

        print("Found", len(items), "items")
        for item in items:
            title = item.find("title").text if item.find("title") is not None else None
            if not title or title.lower() in seen_titles:
                continue

            link = item.find("link").text if item.find("link") is not None else None
            summary = item.find("description").text if item.find("description") is not None else None
            summary, image_url = parse_description(summary)
            
            print("setting summary", summary)

            pubDate = item.find("pubDate").text if item.find("pubDate") is not None else None
            
            ns = {"media": "http://search.yahoo.com/mrss/"}

            image = item.find("media:content",ns) if item.find("media:content",ns) is not None else None
            if image is not None:
                image_url = image.attrib.get("url")

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
                "url": link,
                'image_url': image_url,
                "source": source,
                "published": pubDate,
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
    
    for article in new_articles:
        mongo_db_client.find_one_and_update(
            {"title": article["title"], "source": article["source"]},
            {"$set": article},
            upsert=True,)

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
    

nest_asyncio.apply()
uvicorn.run(app, port=8001)

