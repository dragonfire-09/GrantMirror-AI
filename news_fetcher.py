"""
GrantMirror-AI News Fetcher

Sources:
- EC Research & Innovation RSS
- EC Horizon Europe / Funding & Tenders RSS
- UfukAvrupa news scraper
- Optional RSS sources with safe fallback

Output:
fetch_all_news() -> {
    "news": [...],
    "source_status": [...],
    "updated_at": "HH:MM:SS",
}
"""

import re
import time
import requests
from datetime import datetime
from typing import List, Dict, Optional

try:
    import feedparser
    HAS_FEEDPARSER = True
except Exception:
    HAS_FEEDPARSER = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except Exception:
    HAS_BS4 = False


CACHE_TTL_SECONDS = 15 * 60

_news_cache = {
    "timestamp": 0,
    "data": None,
}


RSS_SOURCES = [
    {
        "name": "🇪🇺 EC Research & Innovation",
        "type": "RSS",
        "url": "https://research-and-innovation.ec.europa.eu/news/all-research-and-innovation-news_en/rss.xml",
        "limit": 30,
        "enabled": True,
    },
    {
        "name": "🔬 EC R&I - Horizon Europe",
        "type": "RSS",
        "url": "https://research-and-innovation.ec.europa.eu/funding/funding-opportunities/funding-programmes-and-open-calls/horizon-europe_en/rss.xml",
        "limit": 30,
        "enabled": True,
    },
    {
        "name": "⭐ ERC News",
        "type": "RSS",
        "url": "https://erc.europa.eu/news-events/news/rss.xml",
        "limit": 20,
        "enabled": False,
    },
    {
        "name": "💡 EIC News",
        "type": "RSS",
        "url": "https://eic.ec.europa.eu/news/rss.xml",
        "limit": 20,
        "enabled": False,
    },
    {
        "name": "🎓 MSCA News",
        "type": "RSS",
        "url": "https://marie-sklodowska-curie-actions.ec.europa.eu/news/rss.xml",
        "limit": 20,
        "enabled": False,
    },
]


UFUKAVRUPA_URL = "https://ufukavrupa.org.tr/tr/haberler"
BASE_UFUKAVRUPA_URL = "https://ufukavrupa.org.tr"


def clean_html(text: str) -> str:
    if not text:
        return ""

    text = re.sub(r"<[^>]+>", " ", str(text))
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def parse_date_safe(value: str) -> str:
    if not value:
        return ""

    text = clean_html(str(value))

    patterns = [
        r"(\d{1,2}\s+[A-Za-zÇĞİÖŞÜçğıöşü]+\s+\d{4})",
        r"(\d{4}-\d{2}-\d{2})",
    ]

    month_map_tr = {
        "Ocak": "January",
        "Şubat": "February",
        "Mart": "March",
        "Nisan": "April",
        "Mayıs": "May",
        "Haziran": "June",
        "Temmuz": "July",
        "Ağustos": "August",
        "Eylül": "September",
        "Ekim": "October",
        "Kasım": "November",
        "Aralık": "December",
    }

    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue

        raw = match.group(1)

        raw_en = raw
        for tr, en in month_map_tr.items():
            raw_en = raw_en.replace(tr, en)

        for fmt in ("%d %B %Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw_en, fmt).strftime("%Y-%m-%d")
            except Exception:
                pass

    return text[:30]


def fetch_rss_news(url: str, source_name: str, limit: int = 20) -> List[Dict]:
    if not HAS_FEEDPARSER:
        return []

    try:
        feed = feedparser.parse(url)
        entries = feed.entries or []

        news = []

        for entry in entries[:limit]:
            title = clean_html(entry.get("title", ""))
            link = entry.get("link", "")
            summary = clean_html(
                entry.get("summary", "")
                or entry.get("description", "")
                or entry.get("subtitle", "")
            )

            published = (
                entry.get("published", "")
                or entry.get("updated", "")
                or entry.get("created", "")
            )

            date_value = parse_date_safe(published)

            if not title:
                continue

            news.append(
                {
                    "title": title,
                    "link": link,
                    "date": date_value,
                    "summary": summary,
                    "source": source_name,
                    "source_type": "RSS",
                }
            )

        return news

    except Exception:
        return []


def fetch_ufukavrupa_news(limit: int = 30) -> List[Dict]:
    """
    Scrape UfukAvrupa news page:
    https://ufukavrupa.org.tr/tr/haberler
    """

    if not HAS_BS4:
        return []

    try:
        response = requests.get(
            UFUKAVRUPA_URL,
            timeout=25,
            headers={
                "User-Agent": "Mozilla/5.0 GrantMirror-AI/1.0",
                "Accept": "text/html",
            },
        )

        if response.status_code != 200:
            return []

        soup = BeautifulSoup(response.text, "html.parser")

        news = []

        # Primary strategy: collect visible news links from the page.
        for a in soup.find_all("a", href=True):
            title = clean_html(a.get_text(" ", strip=True))
            href = a.get("href", "")

            if not title:
                continue

            # Avoid navigation links.
            if len(title) < 15:
                continue

            if href.startswith("/"):
                link = BASE_UFUKAVRUPA_URL + href
            elif href.startswith("http"):
                link = href
            else:
                continue

            if "/tr/haberler" not in link and "/tr/" not in link:
                continue

            # Extract nearby text for date/category.
            parent_text = clean_html(
                a.parent.get_text(" ", strip=True) if a.parent else title
            )

            # Sometimes date is in the next siblings / parent block.
            container = a.find_parent(["div", "article", "li", "tr"])
            container_text = clean_html(
                container.get_text(" ", strip=True) if container else parent_text
            )

            date_value = parse_date_safe(container_text)

            # Category: after date often appears as extra text; keep short signal.
            category = ""
            if date_value:
                category_candidate = container_text.replace(title, "").replace(date_value, "")
                category = clean_html(category_candidate)[:120]

            item = {
                "title": title,
                "link": link,
                "date": date_value,
                "summary": category,
                "source": "🇹🇷 UfukAvrupa",
                "source_type": "Scraper",
            }

            news.append(item)

        # Deduplicate
        seen = set()
        unique = []

        for item in news:
            key = (item["title"].lower(), item["link"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)

        return unique[:limit]

    except Exception:
        return []


def fetch_all_news(force_refresh: bool = False) -> Dict:
    now = time.time()

    if (
        not force_refresh
        and _news_cache["data"] is not None
        and now - _news_cache["timestamp"] < CACHE_TTL_SECONDS
    ):
        return _news_cache["data"]

    all_news = []
    source_status = []

    for source in RSS_SOURCES:
        if not source.get("enabled", True):
            source_status.append(
                {
                    "name": source["name"],
                    "type": source["type"],
                    "count": 0,
                    "ok": False,
                    "enabled": False,
                    "message": "Disabled",
                }
            )
            continue

        items = fetch_rss_news(
            source["url"],
            source["name"],
            limit=source.get("limit", 20),
        )

        all_news.extend(items)

        source_status.append(
            {
                "name": source["name"],
                "type": source["type"],
                "count": len(items),
                "ok": len(items) > 0,
                "enabled": True,
                "message": "OK" if items else "No items",
            }
        )

    ufuk_items = fetch_ufukavrupa_news(limit=30)
    all_news.extend(ufuk_items)

    source_status.append(
        {
            "name": "🇹🇷 UfukAvrupa",
            "type": "Scraper",
            "count": len(ufuk_items),
            "ok": len(ufuk_items) > 0,
            "enabled": True,
            "message": "OK" if ufuk_items else "No items",
        }
    )

    # Deduplicate all news
    seen = set()
    unique_news = []

    for item in all_news:
        key = (item.get("title", "").lower(), item.get("link", ""))
        if key in seen:
            continue
        seen.add(key)
        unique_news.append(item)

    # Sort by date descending if possible
    def sort_key(item):
        date_str = item.get("date", "")
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            return datetime.min

    unique_news.sort(key=sort_key, reverse=True)

    result = {
        "news": unique_news,
        "source_status": source_status,
        "updated_at": datetime.now().strftime("%H:%M:%S"),
        "cache_ttl_minutes": int(CACHE_TTL_SECONDS / 60),
    }

    _news_cache["timestamp"] = now
    _news_cache["data"] = result

    return result


def filter_news(news: List[Dict], query: str = "", source: str = "") -> List[Dict]:
    filtered = news

    if query:
        q = query.lower()
        filtered = [
            item
            for item in filtered
            if q in item.get("title", "").lower()
            or q in item.get("summary", "").lower()
            or q in item.get("source", "").lower()
        ]

    if source:
        filtered = [
            item
            for item in filtered
            if source.lower() in item.get("source", "").lower()
        ]

    return filtered


def news_to_markdown(news: List[Dict]) -> str:
    lines = ["# GrantMirror-AI News Digest\n"]

    for item in news:
        title = item.get("title", "")
        link = item.get("link", "")
        date_value = item.get("date", "")
        source = item.get("source", "")
        summary = item.get("summary", "")

        lines.append(f"## {title}")
        lines.append(f"- Source: {source}")
        if date_value:
            lines.append(f"- Date: {date_value}")
        if link:
            lines.append(f"- Link: {link}")
        if summary:
            lines.append(f"\n{summary}")
        lines.append("")

    return "\n".join(lines)
