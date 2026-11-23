import calendar
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests

STOP = set("about after against amid and are before could for from has have into its more new over says that the their this under was were what when where will with would".split())
TOPICS = {
    "Public affairs": "government parliament minister election vote court policy senate",
    "Business": "economy market trade bank inflation company tariff jobs",
    "Science & tech": "science space research nasa technology ai satellite",
    "Climate & weather": "weather storm climate rain flood cyclone heat",
    "Sport": "cricket tennis soccer football olympics match league",
}


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    source: str
    group: str
    region: str
    seen_at: str
    discovered: bool = False


def canonical(url):
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            return ""
        query = sorted((key, value) for key, value in parse_qsl(parts.query)
                       if not key.lower().startswith("utm_") and key not in {"fbclid", "gclid"})
        return urlunsplit(("https", parts.netloc.lower(), parts.path.rstrip("/") or "/", urlencode(query), ""))
    except ValueError:
        return ""


def clean(value):
    return " ".join(re.sub(r"<[^>]*>", "", unescape(value)).split())


def words(value):
    return set(re.findall(r"[a-z0-9]{3,}", value.lower())) - STOP


def similar(first, second):
    left, right = words(first), words(second)
    shared = left & right
    return (left == right and len(left) >= 3) or (
        len(shared) >= 4 and len(shared) / len(left | right) >= .58
    )


def read_bytes(session, url, **params):
    chunks = bytearray()
    with session.get(url, params=params, timeout=(4, 8), stream=True) as response:
        response.raise_for_status()
        for chunk in response.iter_content(32768):
            chunks.extend(chunk)
            if len(chunks) > 2_000_000:
                raise ValueError("response exceeded size limit")
    return bytes(chunks)


def ingest(settings, now, session=None):
    session = session or requests.Session()
    session.headers["User-Agent"] = "FLASHWIRE/1.0 editorial RSS reader"
    items, failures = [], []
    cutoff = now - timedelta(hours=48)
    for feed in settings["rss"]:
        try:
            parsed = feedparser.parse(read_bytes(session, feed["url"]))
            if not parsed.entries:
                raise ValueError("no entries")
            for entry in parsed.entries[:20]:
                stamp = entry.get("published_parsed") or entry.get("updated_parsed")
                url = canonical(entry.get("link", ""))
                title = clean(entry.get("title", ""))[:300]
                if stamp and url and title:
                    date = datetime.fromtimestamp(calendar.timegm(stamp), UTC)
                    if cutoff <= date <= now + timedelta(minutes=10):
                        items.append(Article(title, url, feed["name"], feed["group"], feed["region"], date.isoformat()))
        except (requests.RequestException, ValueError, OverflowError) as error:
            failures.append(f'{feed["name"]}: {type(error).__name__}')
    try:
        result = json.loads(read_bytes(session, "https://api.gdeltproject.org/api/v2/doc/doc",
                                      query=settings["gdelt"], mode="artlist", format="json",
                                      timespan="24h", maxrecords=25, sort="DateDesc"))
        for entry in result.get("articles", [])[:25]:
            url, title = canonical(entry.get("url", "")), clean(entry.get("title", ""))[:300]
            try:
                date = datetime.strptime(entry.get("seendate", ""), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            except ValueError:
                continue
            if url and title and cutoff <= date <= now + timedelta(minutes=10):
                host = urlsplit(url).hostname
                items.append(Article(title, url, host, host, "World", date.isoformat(), True))
    except (requests.RequestException, ValueError, AttributeError, TypeError) as error:
        failures.append(f"GDELT: {type(error).__name__}")
    return items, failures


def update_queue(state, articles, now, limit=12):
    added = 0
    known = {}
    for story in state["stories"]:
        for item in story["sources"]:
            known.setdefault(item["url"], []).append(item)
    for article in sorted(articles, key=lambda item: (not item.discovered, item.seen_at), reverse=True):
        if article.url in known:
            if not article.discovered:
                for existing in known[article.url]:
                    if existing["discovered"]:
                        existing.update(asdict(article))
            continue
        match = next((story for story in state["stories"]
                      if any(abs(datetime.fromisoformat(src["seen_at"]) -
                                 datetime.fromisoformat(article.seen_at)) <= timedelta(hours=48)
                             and similar(src["title"], article.title) for src in story["sources"])), None)
        if match:
            if len(match["sources"]) < 12:
                source = asdict(article)
                match["sources"].append(source)
                known[article.url] = [source]
            continue
        if added >= limit:
            continue
        topic = next((label for label, terms in TOPICS.items() if words(article.title) & set(terms.split())), "News")
        source_id = hashlib.sha256(article.url.encode()).hexdigest()[:16]
        source = asdict(article)
        state["stories"].insert(0, {
            "id": source_id, "type": "Story", "parent": None, "status": "review",
            "headline": f"{article.region} {topic.lower()} briefing",
            "caption": f"A {topic.lower()} story is developing in our {article.region.lower()} coverage. Check the linked reporting for the latest details.",
            "topic": topic, "region": article.region, "sources": [source],
            "created": now.isoformat(), "due": None, "media_id": None,
            "note": "Draft needs a factual headline and a short sourced caption.",
        })
        known[article.url] = [source]
        added += 1
    return added


def source_groups(story):
    return {item["group"] for item in story["sources"] if not item["discovered"]}


def demo(now):
    return [
        Article("Demo city opens riverside library after renovation", "https://example.org/civic/library",
                "Demo Civic Desk", "demo-civic", "India", now.isoformat()),
        Article("Demo city opens riverside library after renovation", "https://example.com/local/library",
                "Demo Local Wire", "demo-local", "India", now.isoformat()),
        Article("Demo scientists map new coral reef habitats", "https://example.org/science/reef",
                "Demo Science Desk", "demo-civic", "World", now.isoformat()),
    ]
