"""
news_fetcher.py — GrantMirror-AI Haber Çekici
Kaynaklar:
- EC Research & Innovation RSS
- EC R&I - Horizon Europe RSS
- UfukAvrupa scraper

Eski app.py importlarını bozmamak için backward-compatible fonksiyonlar korunmuştur.
"""

import time
import re
import hashlib
import requests
from datetime import datetime
from typing import List, Dict, Optional

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False


# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════

UFUKAVRUPA_NEWS_URL = "https://ufukavrupa.org.tr/tr/haberler"
UFUKAVRUPA_BASE = "https://ufukavrupa.org.tr"

RSS_SOURCES = [
    {
        "name": "EC Research & Innovation",
        "url": "https://research-and-innovation.ec.europa.eu/node/2/rss_en",
        "icon": "🇪🇺",
        "category": "📋 Program Güncellemesi",
        "horizon_filter": False,
    },
    {
        "name": "EC R&I - Horizon Europe",
        "url": (
            "https://research-and-innovation.ec.europa.eu/node/2/rss_en"
            "?f%5B0%5D=topic_topic%3A150"
        ),
        "icon": "🔬",
        "category": "📋 Program Güncellemesi",
        "horizon_filter": False,
    },
]

HORIZON_KEYWORDS = [
    "horizon europe", "erc", "eic", "msca", "marie sklodowska",
    "marie curie", "pathfinder", "accelerator", "widening",
    "twinning", "teaming", "cluster", "work programme",
    "call for proposals", "funding", "grant", "research and innovation",
    "r&i", "green deal", "digital transition", "eu mission",
    "cancer mission", "climate mission", "open science",
    "dissemination", "exploitation", "ria", "innovation action",
    "coordination and support", "lump sum", "proposal", "evaluation",
    "pillar", "destination", "topic", "hibe", "çağrı", "başvuru",
    "ufuk avrupa",
]


# ═══════════════════════════════════════════════════════════
# CACHE
# ═══════════════════════════════════════════════════════════

class NewsCache:
    def __init__(self, ttl_minutes: int = 15):
        self.ttl = ttl_minutes * 60
        self._store: Dict[str, dict] = {}

    def get(self, key: str):
        entry = self._store.get(key)

        if entry and (time.time() - entry["ts"]) < self.ttl:
            return entry["data"]

        return None

    def set(self, key: str, data):
        self._store[key] = {
            "data": data,
            "ts": time.time(),
        }

    def clear(self):
        self._store.clear()

    def stats(self) -> dict:
        return {
            "entries": len(self._store),
            "active": sum(
                1
                for value in self._store.values()
                if (time.time() - value["ts"]) < self.ttl
            ),
        }


_news_cache = NewsCache(ttl_minutes=15)


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def _clean_html(text: str) -> str:
    if not text:
        return ""

    if HAS_BS4:
        try:
            soup = BeautifulSoup(str(text), "html.parser")
            return soup.get_text(separator=" ", strip=True)
        except Exception:
            pass

    text = re.sub(r"<br\s*/?>", " ", str(text))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#\d+;", "", text)
    text = re.sub(r"&\w+;", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def _make_item_id(title: str, link: str = "") -> str:
    return hashlib.md5((title + link).encode("utf-8")).hexdigest()[:12]


def _parse_turkish_date(raw: str) -> Optional[str]:
    if not raw:
        return None

    text = _clean_html(raw)

    month_map = {
        "Ocak": "01",
        "Şubat": "02",
        "Mart": "03",
        "Nisan": "04",
        "Mayıs": "05",
        "Haziran": "06",
        "Temmuz": "07",
        "Ağustos": "08",
        "Eylül": "09",
        "Ekim": "10",
        "Kasım": "11",
        "Aralık": "12",
    }

    match = re.search(
        r"(\d{1,2})\s+"
        r"(Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)"
        r"\s+(\d{4})",
        text,
    )

    if match:
        day, month_tr, year = match.groups()
        return f"{year}-{month_map[month_tr]}-{day.zfill(2)}"

    match = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)

    if match:
        day, month, year = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    match = re.search(r"(\d{4}-\d{2}-\d{2})", text)

    if match:
        return match.group(1)

    return None


def _parse_rss_date(entry) -> str:
    for field in ("published_parsed", "updated_parsed"):
        time_tuple = getattr(entry, field, None)

        if time_tuple:
            try:
                return datetime(*time_tuple[:6]).strftime("%Y-%m-%d")
            except Exception:
                pass

    for field in ("published", "updated"):
        raw = getattr(entry, field, "")

        if raw:
            turkish_date = _parse_turkish_date(raw)

            if turkish_date:
                return turkish_date

            for date_format in (
                "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S",
                "%d %b %Y",
                "%d/%m/%Y",
                "%Y-%m-%d",
            ):
                try:
                    return datetime.strptime(
                        raw.strip()[:30],
                        date_format,
                    ).strftime("%Y-%m-%d")
                except Exception:
                    continue

            if len(raw) >= 10:
                return raw[:10]

    return datetime.now().strftime("%Y-%m-%d")


def _is_horizon_related(title: str, summary: str) -> bool:
    combined = f"{title} {summary}".lower()
    return any(keyword in combined for keyword in HORIZON_KEYWORDS)


def _detect_tag(title: str, summary: str, default_category: str) -> str:
    combined = f"{title} {summary}".lower()

    tag_rules = [
        (["call for proposals", "new call", "calls open", "çağrı açıldı", "yeni çağrı", "open call"], "🆕 Yeni Çağrı"),
        (["erc", "european research council"], "⭐ ERC"),
        (["eic", "pathfinder", "accelerator"], "💡 EIC"),
        (["msca", "marie sklodowska", "marie curie", "doctoral network"], "🎓 MSCA"),
        (["mission", "cancer", "ocean", "climate adaptation", "soil health", "climate-neutral"], "🌍 Missions"),
        (["widening", "twinning", "teaming", "era"], "🤝 Widening"),
        (["work programme", "update", "amendment", "güncelleme"], "📋 Program Güncellemesi"),
        (["statistics", "success rate", "evaluation result", "istatistik"], "📊 İstatistik"),
        (["guide", "guideline", "how to", "tip", "rehber"], "📝 Rehber"),
        (["cluster 4", "digital", "industry", "space"], "🔬 Cluster 4"),
        (["cluster 5", "climate", "energy", "mobility"], "🌿 Cluster 5"),
        (["cluster 1", "health"], "🏥 Cluster 1"),
        (["cluster 2", "culture", "creative", "society"], "🎭 Cluster 2"),
        (["cluster 3", "security", "civil"], "🛡️ Cluster 3"),
        (["cluster 6", "food", "bioeconomy", "natural resources"], "🌾 Cluster 6"),
        (["infrastructure", "research infrastructure"], "🏗️ Altyapı"),
    ]

    for keywords, tag in tag_rules:
        if any(keyword in combined for keyword in keywords):
            return tag

    return default_category


# ═══════════════════════════════════════════════════════════
# RSS FETCHING
# ═══════════════════════════════════════════════════════════

def _fetch_rss_feed(url: str, timeout: int = 15):
    if not HAS_FEEDPARSER:
        return None

    try:
        feed = feedparser.parse(
            url,
            agent="GrantMirror-AI/1.0",
        )

        if feed.entries:
            return feed

    except Exception:
        pass

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 GrantMirror-AI/1.0",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=timeout,
        )

        if response.status_code == 200:
            feed = feedparser.parse(response.content)

            if feed.entries:
                return feed

    except Exception:
        pass

    return None


def fetch_rss_news(
    source: dict,
    max_items: int = 30,
    horizon_only: bool = True,
) -> List[Dict]:
    cache_key = f"rss_{hashlib.md5(source['url'].encode()).hexdigest()}_{max_items}_{horizon_only}"

    cached = _news_cache.get(cache_key)

    if cached is not None:
        return cached

    items = []
    feed = _fetch_rss_feed(source["url"])

    if not feed or not feed.entries:
        _news_cache.set(cache_key, items)
        return items

    need_filter = source.get("horizon_filter", True) and horizon_only

    for entry in feed.entries[: max_items * 3]:
        title = _clean_html(getattr(entry, "title", ""))

        summary = _clean_html(
            getattr(entry, "summary", "")
            or getattr(entry, "description", "")
        )

        link = getattr(entry, "link", "")

        if not title or len(title) < 5:
            continue

        if need_filter and not _is_horizon_related(title, summary):
            continue

        if len(summary) > 400:
            summary = summary[:397] + "..."

        item = {
            "id": _make_item_id(title, link),
            "date": _parse_rss_date(entry),
            "tag": _detect_tag(title, summary, source.get("category", "📰 Haber")),
            "title": title,
            "summary": summary,
            "link": link,
            "source": source["name"],
            "source_icon": source.get("icon", "📰"),
        }

        items.append(item)

        if len(items) >= max_items:
            break

    _news_cache.set(cache_key, items)
    return items


def fetch_all_rss_news(
    max_per_source: int = 30,
    horizon_only: bool = True,
) -> List[Dict]:
    cache_key = f"all_rss_{max_per_source}_{horizon_only}_clean"

    cached = _news_cache.get(cache_key)

    if cached is not None:
        return cached

    all_items = []
    seen_titles = set()

    for source in RSS_SOURCES:
        items = fetch_rss_news(
            source=source,
            max_items=max_per_source,
            horizon_only=horizon_only,
        )

        for item in items:
            title_key = item["title"].lower()[:90]

            if title_key not in seen_titles:
                seen_titles.add(title_key)
                all_items.append(item)

    all_items.sort(key=lambda item: item.get("date", ""), reverse=True)

    _news_cache.set(cache_key, all_items)
    return all_items


# ═══════════════════════════════════════════════════════════
# UFUKAVRUPA SCRAPER — ROBUST VERSION
# ═══════════════════════════════════════════════════════════

def fetch_ufukavrupa_news(max_items: int = 30) -> List[Dict]:
    """
    Robust UfukAvrupa scraper.
    Source:
    https://ufukavrupa.org.tr/tr/haberler
    """

    cache_key = f"ufukavrupa_news_robust_{max_items}"

    cached = _news_cache.get(cache_key)

    if cached is not None:
        return cached

    items = []

    if not HAS_BS4:
        _news_cache.set(cache_key, items)
        return items

    try:
        response = requests.get(
            UFUKAVRUPA_NEWS_URL,
            timeout=25,
            headers={
                "User-Agent": "Mozilla/5.0 GrantMirror-AI/1.0",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
            },
        )

        if response.status_code != 200:
            _news_cache.set(cache_key, items)
            return items

        soup = BeautifulSoup(response.text, "html.parser")

        candidate_links = []

        for link_el in soup.find_all("a", href=True):
            title = _clean_html(link_el.get_text(" ", strip=True))
            href = link_el.get("href", "")

            if not title or len(title) < 20:
                continue

            if href.startswith("/"):
                link = UFUKAVRUPA_BASE + href
            elif href.startswith("http"):
                link = href
            else:
                continue

            if "/tr/" not in link:
                continue

            lowered = title.lower()

            skip_words = [
                "ana sayfa", "hakkımızda", "iletişim", "duyurular",
                "etkinlikler", "programlar", "başvuru", "sss",
                "e-bülten", "sosyal medya", "tümünü görüntüle",
            ]

            if any(word in lowered for word in skip_words):
                continue

            candidate_links.append((title, link, link_el))

        seen = set()

        for title, link, link_el in candidate_links:
            key = (title.lower()[:100], link)

            if key in seen:
                continue

            seen.add(key)

            container = link_el.find_parent(["div", "article", "li", "tr", "section"])

            container_text = (
                _clean_html(container.get_text(" ", strip=True))
                if container
                else title
            )

            date_str = _parse_turkish_date(container_text) or datetime.now().strftime("%Y-%m-%d")

            summary = container_text.replace(title, "").strip()

            if len(summary) > 400:
                summary = summary[:397] + "..."

            item = {
                "id": _make_item_id(title, link),
                "date": date_str,
                "tag": _detect_tag(title, summary, "📋 Program Güncellemesi"),
                "title": title,
                "summary": summary,
                "link": link,
                "source": "UfukAvrupa",
                "source_icon": "🇹🇷",
            }

            items.append(item)

            if len(items) >= max_items:
                break

    except Exception:
        pass

    _news_cache.set(cache_key, items)
    return items


# ═══════════════════════════════════════════════════════════
# MAIN NEWS FUNCTION
# ═══════════════════════════════════════════════════════════

def get_news_with_fallback(
    max_per_source: int = 30,
    horizon_only: bool = True,
    include_recent_calls: bool = False,
    include_ufukavrupa: bool = True,
    include_euresearch: bool = False,
) -> List[Dict]:
    cache_key = (
        f"news_clean_{max_per_source}_{horizon_only}_"
        f"{include_ufukavrupa}_v3"
    )

    cached = _news_cache.get(cache_key)

    if cached is not None:
        return cached

    all_news = []

    try:
        all_news.extend(fetch_all_rss_news(max_per_source, horizon_only))
    except Exception:
        pass

    if include_ufukavrupa:
        try:
            all_news.extend(fetch_ufukavrupa_news(max_per_source))
        except Exception:
            pass

    if not all_news:
        all_news = []

    seen = set()
    unique = []

    for item in all_news:
        key = item.get("title", "")[:90].lower()

        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    unique.sort(key=lambda item: item.get("date", ""), reverse=True)

    _news_cache.set(cache_key, unique)
    return unique


# ═══════════════════════════════════════════════════════════
# SOURCE STATUS — ONLY WORKING SOURCES
# ═══════════════════════════════════════════════════════════

def get_news_sources_status() -> List[Dict]:
    statuses = []

    for source in RSS_SOURCES:
        try:
            items = fetch_rss_news(
                source=source,
                max_items=30,
                horizon_only=False,
            )

            if items:
                statuses.append({
                    "name": source["name"],
                    "icon": source.get("icon", "📰"),
                    "url": source["url"],
                    "status": "✅",
                    "count": len(items),
                    "type": "RSS",
                })

        except Exception:
            pass

    try:
        ufuk_items = fetch_ufukavrupa_news(30)

        if ufuk_items:
            statuses.append({
                "name": "UfukAvrupa",
                "icon": "🇹🇷",
                "url": UFUKAVRUPA_NEWS_URL,
                "status": "✅",
                "count": len(ufuk_items),
                "type": "Scraper",
            })

    except Exception:
        pass

    return statuses


# ═══════════════════════════════════════════════════════════
# BACKWARD-COMPATIBILITY ALIASES
# ═══════════════════════════════════════════════════════════

def fetch_all_news(*args, **kwargs):
    return get_news_with_fallback(*args, **kwargs)


def get_news(*args, **kwargs):
    return get_news_with_fallback(*args, **kwargs)


def fetch_news(*args, **kwargs):
    return get_news_with_fallback(*args, **kwargs)


def fetch_all_sources_news(*args, **kwargs):
    return get_news_with_fallback(*args, **kwargs)


def get_latest_news(*args, **kwargs):
    return get_news_with_fallback(*args, **kwargs)


def get_source_status(*args, **kwargs):
    return get_news_sources_status()


def clear_news_cache():
    _news_cache.clear()


def get_cache_stats():
    return _news_cache.stats()


def filter_news(
    news: List[Dict],
    query: str = "",
    source: str = "",
) -> List[Dict]:
    filtered = news

    if query:
        q = query.lower()

        filtered = [
            item
            for item in filtered
            if q in item.get("title", "").lower()
            or q in item.get("summary", "").lower()
            or q in item.get("source", "").lower()
            or q in item.get("tag", "").lower()
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
        lines.append(f"## {item.get('title', '')}")
        lines.append(f"- Source: {item.get('source', '')}")

        if item.get("date"):
            lines.append(f"- Date: {item.get('date')}")

        if item.get("tag"):
            lines.append(f"- Tag: {item.get('tag')}")

        if item.get("link"):
            lines.append(f"- Link: {item.get('link')}")

        if item.get("summary"):
            lines.append("")
            lines.append(item.get("summary", ""))

        lines.append("")

    return "\n".join(lines)
