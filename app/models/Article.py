from datetime import datetime


class Article:
    def __init__(self, title, url, sentiment, published, summary=None, image_url=None, source=None):
        self.title = title
        self.url = url
        self.published = published
        self.summary = summary
        self.image_url = image_url
        self.source = source,
        self. sentiment = sentiment
        self.fetched_at = datetime.utcnow().isoformat(),


