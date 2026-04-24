"""
news_fetcher.py — GrantMirror-AI Horizon Europe Canlı Haber Çekici
RSS + Web Scraper + EC API + UfukAvrupa + Euresearch

Backward-compatible version.
"""

import time
import re
import hashlib
import requests
from datetime import datetime, timedelta
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

EC_SEARCH_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"

EURESEARCH_NEWS_URLS = [
    "https://www.euresearch.ch/en/news",
    "https://www.euresearch.ch/en/our-services/inform",
]

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
    {
        "name": "CORDIS EU News",
        "url": "https://cordis.europa.eu/news/rss",
        "icon": "📡",
        "category": "🔬 Araştırma",
        "horizon_filter": True,
    },
    {
        "name": "CORDIS Results",
        "url": "https://cordis.europa.eu/article/rss",
        "icon": "📊",
        "category": "🔬 Araştırma Sonuçları",
        "horizon_filter": True,
    },
    {
        "name": "ERC News",
        "url": "https://erc.europa.eu/news/rss.xml",
        "icon": "⭐",
        "category": "⭐ ERC",
        "horizon_filter": False,
    },
    {
        "name": "EIC News",
        "url": "https://eic.ec.europa.eu/news/rss.xml",
        "icon": "💡",
        "category": "💡 EIC",
        "horizon_filter": False,
    },
    {
        "name": "MSCA News",
        "url": "https://marie-sklodowska-curie-actions.ec.europa.eu/news/rss.xml",
        "icon": "🎓",
        "category": "🎓 MSCA",
        "horizon_filter": False,
    },
]

ALT_RSS_SOURCES = [
    {
        "name": "EC R&I Blog",
        "url": "https://research-and-innovation.ec.europa.eu/news/all/rss_en",
        "icon": "🇪🇺",
        "category": "📋 Program Güncellemesi",
        "horizon_filter": False,
    },
    {
        "name": "CORDIS Wire",
        "url": "https://cordis.europa.eu/wire/rss",
        "icon": "📡",
        "category": "🔬 Araştırma",
        "horizon_filter": True,
    },
]


HORIZON_KEYWORDS = [
    "horizon europe", "horizon 2020", "framework programme",
    "erc", "eic", "msca", "marie sklodowska", "marie curie",
    "pathfinder", "accelerator", "widening", "twinning", "teaming",
    "cluster 1", "cluster 2", "cluster 3", "cluster 4", "cluster 5", "cluster 6",
    "work programme", "call for proposals", "funding", "grant",
    "research and innovation", "r&i", "r&d",
    "green deal", "digital transition", "twin transition",
    "eu mission", "cancer mission", "climate mission",
    "open science", "dissemination", "exploitation",
    "ria", "innovation action", "coordination and support",
    "lump sum", "proposal", "evaluation",
    "pillar", "destination", "topic",
    "hibe", "çağrı", "başvuru", "ufuk avrupa",
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
        self._store[key] = {"data": data, "ts": time.time()}

    def clear(self):
        self._store.clear()

    def stats(self) -> dict:
        return {
            "entries": len(self._store),
            "active": sum(
                1 for v in self._store.values()
                if (time.time() - v["ts"]) < self.ttl
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

    match2 = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if match2:
        day, month, year = match2.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    match3 = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if match3:
        return match3.group(1)

    return None


def _parse_date(entry) -> str:
    for field in ("published_parsed", "updated_parsed"):
        tp = getattr(entry, field, None)
        if tp:
            try:
                return datetime(*tp[:6]).strftime("%Y-%m-%d")
            except Exception:
                pass

    for field in ("published", "updated"):
        raw = getattr(entry, field, "")
        if raw:
            tr_date = _parse_turkish_date(raw)
            if tr_date:
                return tr_date

            for fmt in (
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
                        raw.strip()[:30], fmt
                    ).strftime("%Y-%m-%d")
                except Exception:
                    continue

            if len(raw) >= 10:
                return raw[:10]

    return datetime.now().strftime("%Y-%m-%d")


def _is_horizon_related(title: str, summary: str) -> bool:
    combined = (title + " " + summary).lower()
    return any(keyword in combined for keyword in HORIZON_KEYWORDS)


def _detect_tag(title: str, summary: str, default_category: str) -> str:
    combined = (title + " " + summary).lower()

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


def _make_item_id(title: str, link: str = "") -> str:
    return hashlib.md5((title + link).encode("utf-8")).hexdigest()[:12]


# ═══════════════════════════════════════════════════════════
# RSS
# ═══════════════════════════════════════════════════════════

def _fetch_rss_feed(url: str, timeout: int = 15):
    if not HAS_FEEDPARSER:
        return None

    try:
        feed = feedparser.parse(url, agent="GrantMirror-AI/1.0")
        if feed.entries:
            return feed
    except Exception:
        pass

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 GrantMirror-AI/1.0",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            feed = feedparser.parse(response.content)
            if feed.entries:
                return feed
    except Exception:
        pass

    return None


def fetch_rss_news(source: dict, max_items: int = 20, horizon_only: bool = True) -> List[Dict]:
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

        date_str = _parse_date(entry)
        tag = _detect_tag(title, summary, source.get("category", "📰 Haber"))

        items.append({
            "id": _make_item_id(title, link),
            "date": date_str,
            "tag": tag,
            "title": title,
            "summary": summary,
            "link": link,
            "source": source["name"],
            "source_icon": source.get("icon", "📰"),
        })

        if len(items) >= max_items:
            break

    _news_cache.set(cache_key, items)
    return items


def fetch_all_rss_news(max_per_source: int = 15, horizon_only: bool = True) -> List[Dict]:
    cache_key = f"all_rss_{max_per_source}_{horizon_only}"
    cached = _news_cache.get(cache_key)
    if cached is not None:
        return cached

    all_items = []
    seen_titles = set()
    working_sources = 0

    for source in RSS_SOURCES:
        items = fetch_rss_news(source, max_per_source, horizon_only)
        if items:
            working_sources += 1

        for item in items:
            title_key = item["title"].lower()[:80]
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                all_items.append(item)

    if working_sources < 2:
        for source in ALT_RSS_SOURCES:
            items = fetch_rss_news(source, max_per_source, horizon_only)
            for item in items:
                title_key = item["title"].lower()[:80]
                if title_key not in seen_titles:
                    seen_titles.add(title_key)
                    all_items.append(item)

    all_items.sort(key=lambda x: x.get("date", ""), reverse=True)
    _news_cache.set(cache_key, all_items)
    return all_items


# ═══════════════════════════════════════════════════════════
# UFUKAVRUPA
# ═══════════════════════════════════════════════════════════

def fetch_ufukavrupa_news(max_items: int = 30) -> List[Dict]:
    cache_key = f"ufukavrupa_news_{max_items}"
    cached = _news_cache.get(cache_key)
    if cached is not None:
        return cached

    items = []

    if not HAS_BS4:
        _news_cache.set(cache_key, items)
        return items

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 GrantMirror-AI/1.0",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
        }

        response = requests.get(UFUKAVRUPA_NEWS_URL, headers=headers, timeout=20)

        if response.status_code != 200:
            _news_cache.set(cache_key, items)
            return items

        soup = BeautifulSoup(response.text, "html.parser")

        containers = (
            soup.select(".view-content .views-row")
            or soup.select(".views-row")
            or soup.select("article")
            or soup.select(".node")
            or soup.select(".card")
            or soup.select(".news-item")
            or soup.select(".list-item")
        )

        if not containers:
            containers = []
            for link in soup.find_all("a", href=True):
                title = _clean_html(link.get_text(" ", strip=True))
                href = link.get("href", "")

                if len(title) < 15:
                    continue

                if "/tr/haberler" in href or "/tr/" in href:
                    parent = link.find_parent(["div", "article", "li", "tr"])
                    containers.append(parent or link)

        for item_el in containers[: max_items * 3]:
            news = _parse_ufukavrupa_news_item(item_el)

            if news and news.get("title") and len(news["title"]) > 10:
                items.append(news)

            if len(items) >= max_items:
                break

    except Exception:
        pass

    # Deduplicate
    seen = set()
    unique = []

    for item in items:
        key = (item.get("title", "").lower()[:100], item.get("link", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    _news_cache.set(cache_key, unique)
    return unique


def _parse_ufukavrupa_news_item(item) -> Optional[Dict]:
    try:
        if item is None:
            return None

        title_el = (
            item.select_one("h2 a, h3 a, h4 a, .title a, .field--name-title a")
            if hasattr(item, "select_one")
            else None
        )

        if not title_el and hasattr(item, "select_one"):
            title_el = item.select_one("h2, h3, h4, .title, .field--name-title, a")

        if not title_el:
            return None

        title = _clean_html(title_el.get_text(" ", strip=True))

        if not title or len(title) < 10:
            return None

        link = ""

        if getattr(title_el, "name", "") == "a":
            link = title_el.get("href", "")
        else:
            a = title_el.find("a") if hasattr(title_el, "find") else None
            if a:
                link = a.get("href", "")

        if link and link.startswith("/"):
            link = f"{UFUKAVRUPA_BASE}{link}"
        elif not link:
            link = UFUKAVRUPA_NEWS_URL

        container_text = _clean_html(item.get_text(" ", strip=True)) if hasattr(item, "get_text") else title
        parsed_date = _parse_turkish_date(container_text)

        date_str = parsed_date or datetime.now().strftime("%Y-%m-%d")

        summary = ""
        if hasattr(item, "select_one"):
            summary_el = item.select_one(
                ".summary, .body, .teaser, .description, "
                ".field--name-body, p, .text, "
                "[class*='summary'], [class*='ozet']"
            )
            if summary_el:
                summary = _clean_html(summary_el.get_text(" ", strip=True))

        if not summary:
            summary = container_text.replace(title, "").strip()

        if len(summary) > 400:
            summary = summary[:397] + "..."

        tag = _detect_tag(title, summary, "📋 Program Güncellemesi")

        return {
            "id": _make_item_id(title, link),
            "date": date_str,
            "tag": tag,
            "title": title,
            "summary": summary,
            "link": link,
            "source": "UfukAvrupa",
            "source_icon": "🇹🇷",
        }

    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# EC API CALLS AS NEWS
# ═══════════════════════════════════════════════════════════

def _extract_meta_field(metadata: dict, field: str) -> str:
    for key, values in metadata.items():
        if field.lower() in key.lower():
            if isinstance(values, list) and values:
                value = values[0]
                if isinstance(value, dict):
                    return str(value.get("value", ""))
                return str(value)
            if isinstance(values, str):
                return values
    return ""


def fetch_recent_calls_as_news(days: int = 30, max_items: int = 10) -> List[Dict]:
    cache_key = f"recent_calls_news_{days}_{max_items}"
    cached = _news_cache.get(cache_key)
    if cached is not None:
        return cached

    items = []

    try:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        params = {
            "apiKey": "SEDIA",
            "text": "frameworkProgramme/HORIZON AND status/code/31094501",
            "type": "1",
            "pageSize": str(min(max_items * 2, 50)),
            "pageNumber": "1",
            "sort": "sortStatus asc,deadlineDate asc",
        }

        response = requests.get(EC_SEARCH_URL, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()

            for result in data.get("results", [])[:max_items]:
                meta = result.get("metadata", {})

                title = _clean_html(_extract_meta_field(meta, "title"))
                call_id = _clean_html(_extract_meta_field(meta, "identifier"))
                deadline = _clean_html(_extract_meta_field(meta, "deadlineDate"))
                status = _clean_html(_extract_meta_field(meta, "status"))
                start_date = _clean_html(_extract_meta_field(meta, "startDate"))

                if not title:
                    continue

                if start_date and len(start_date) >= 10:
                    if start_date[:10] < since:
                        continue

                link = ""
                if call_id:
                    link = (
                        "https://ec.europa.eu/info/funding-tenders/opportunities/"
                        f"portal/screen/opportunities/topic-details/{call_id}"
                    )

                summary_parts = []
                if call_id:
                    summary_parts.append(f"Çağrı ID: {call_id}")
                if deadline:
                    summary_parts.append(f"Son tarih: {deadline[:10]}")
                if status:
                    summary_parts.append(f"Durum: {status}")

                display_title = f"{call_id}: {title}" if call_id else title

                items.append({
                    "id": _make_item_id(display_title, link),
                    "date": start_date[:10] if start_date and len(start_date) >= 10 else datetime.now().strftime("%Y-%m-%d"),
                    "tag": "🆕 Yeni Çağrı",
                    "title": display_title,
                    "summary": " | ".join(summary_parts),
                    "link": link,
                    "source": "EC F&T Portal",
                    "source_icon": "🇪🇺",
                })

    except Exception:
        pass

    _news_cache.set(cache_key, items)
    return items


# ═══════════════════════════════════════════════════════════
# EURESEARCH
# ═══════════════════════════════════════════════════════════

def fetch_euresearch_news(max_items: int = 15) -> List[Dict]:
    cache_key = f"euresearch_news_{max_items}"
    cached = _news_cache.get(cache_key)
    if cached is not None:
        return cached

    items = []

    if not HAS_BS4:
        _news_cache.set(cache_key, items)
        return items

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 GrantMirror-AI/1.0",
            "Accept": "text/html,application/xhtml+xml",
        }

        for url in EURESEARCH_NEWS_URLS:
            try:
                response = requests.get(url, headers=headers, timeout=15)

                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(response.text, "html.parser")

                containers = (
                    soup.select(".view-content .views-row")
                    or soup.select("article")
                    or soup.select(".news-item")
                    or soup.select(".card")
                    or soup.select(".teaser")
                )

                if not containers:
                    containers = []
                    for a in soup.find_all("a", href=True):
                        text = a.get_text(strip=True)
                        href = a.get("href", "")
                        if len(text) >= 20 and any(
                            kw in (text + href).lower()
                            for kw in ["news", "event", "call", "horizon"]
                        ):
                            containers.append(a.parent if a.parent else a)

                for container in containers[:max_items]:
                    news = _parse_euresearch_news_item(container)
                    if news and news.get("title") and len(news["title"]) > 10:
                        items.append(news)
                    if len(items) >= max_items:
                        break

                if items:
                    break

            except Exception:
                continue

    except Exception:
        pass

    _news_cache.set(cache_key, items)
    return items


def _parse_euresearch_news_item(item) -> Optional[Dict]:
    try:
        title_el = (
            item.select_one("h2 a, h3 a, h4 a, .title a, a")
            if hasattr(item, "select_one")
            else None
        )

        if not title_el:
            return None

        title = _clean_html(title_el.get_text(" ", strip=True))

        if not title or len(title) < 10:
            return None

        link = ""

        if getattr(title_el, "name", "") == "a":
            link = title_el.get("href", "")

        if link and link.startswith("/"):
            link = f"https://www.euresearch.ch{link}"
        elif not link:
            link = "https://www.euresearch.ch"

        container_text = _clean_html(item.get_text(" ", strip=True)) if hasattr(item, "get_text") else title
        date_str = _parse_turkish_date(container_text) or datetime.now().strftime("%Y-%m-%d")

        summary = ""
        summary_el = item.select_one(".summary, .teaser, .body, p, .description") if hasattr(item, "select_one") else None
        if summary_el:
            summary = _clean_html(summary_el.get_text(" ", strip=True))

        if len(summary) > 400:
            summary = summary[:397] + "..."

        tag = _detect_tag(title, summary, "📋 Program Güncellemesi")

        return {
            "id": _make_item_id(title, link),
            "date": date_str,
            "tag": tag,
            "title": title,
            "summary": summary,
            "link": link,
            "source": "Euresearch",
            "source_icon": "🇨🇭",
        }

    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# FALLBACK
# ═══════════════════════════════════════════════════════════

FALLBACK_NEWS = [
    {
        "id": "fb1",
        "date": "2025-01-15",
        "tag": "🆕 Yeni Çağrı",
        "title": "Cluster 5 — Climate, Energy and Mobility 2025 çağrıları açıldı",
        "summary": "Enerji dönüşümü, sürdürülebilir ulaşım ve iklim bilimi alanlarında çağrılar başvuruya açıldı.",
        "link": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-search",
        "source": "Statik",
        "source_icon": "📌",
    },
    {
        "id": "fb2",
        "date": "2025-01-10",
        "tag": "📋 Program Güncellemesi",
        "title": "Horizon Europe Work Programme güncellemeleri yayınlandı",
        "summary": "İş programlarında yeni topic'ler ve deadline güncellemeleri takip edilmelidir.",
        "link": "https://research-and-innovation.ec.europa.eu/funding/funding-opportunities/funding-programmes-and-open-calls/horizon-europe/horizon-europe-work-programmes_en",
        "source": "Statik",
        "source_icon": "📌",
    },
]


# ═══════════════════════════════════════════════════════════
# MAIN FUNCTIONS
# ═══════════════════════════════════════════════════════════

def get_news_with_fallback(
    max_per_source: int = 15,
    horizon_only: bool = True,
    include_recent_calls: bool = True,
    include_ufukavrupa: bool = True,
    include_euresearch: bool = True,
) -> List[Dict]:
    cache_key = (
        f"all_news_{max_per_source}_{horizon_only}_"
        f"{include_recent_calls}_{include_ufukavrupa}_{include_euresearch}_v2"
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

    if include_euresearch:
        try:
            all_news.extend(fetch_euresearch_news(max_per_source))
        except Exception:
            pass

    if include_recent_calls:
        try:
            all_news.extend(fetch_recent_calls_as_news(days=30, max_items=10))
        except Exception:
            pass

    if not all_news:
        all_news = FALLBACK_NEWS.copy()

    seen = set()
    unique = []

    for item in all_news:
        key = item.get("title", "")[:90].lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    unique.sort(key=lambda x: x.get("date", ""), reverse=True)

    _news_cache.set(cache_key, unique)
    return unique


def get_news_sources_status() -> List[Dict]:
    statuses = []

    for source in RSS_SOURCES:
        try:
            feed = _fetch_rss_feed(source["url"])
            ok = feed is not None and bool(getattr(feed, "entries", []))
            count = len(feed.entries) if ok else 0

            statuses.append({
                "name": source["name"],
                "icon": source.get("icon", "📰"),
                "url": source["url"],
                "status": "✅" if ok else "⚠️",
                "count": count,
                "type": "RSS",
            })

        except Exception:
            statuses.append({
                "name": source["name"],
                "icon": source.get("icon", "📰"),
                "url": source["url"],
                "status": "❌",
                "count": 0,
                "type": "RSS",
            })

    try:
        ua_items = fetch_ufukavrupa_news(30)
        statuses.append({
            "name": "UfukAvrupa",
            "icon": "🇹🇷",
            "url": UFUKAVRUPA_NEWS_URL,
            "status": "✅" if ua_items else "⚠️",
            "count": len(ua_items),
            "type": "Scraper",
        })
    except Exception:
        statuses.append({
            "name": "UfukAvrupa",
            "icon": "🇹🇷",
            "url": UFUKAVRUPA_NEWS_URL,
            "status": "❌",
            "count": 0,
            "type": "Scraper",
        })

    try:
        eur_items = fetch_euresearch_news(15)
        statuses.append({
            "name": "Euresearch",
            "icon": "🇨🇭",
            "url": "https://www.euresearch.ch/en/news",
            "status": "✅" if eur_items else "⚠️",
            "count": len(eur_items),
            "type": "Scraper",
        })
    except Exception:
        statuses.append({
            "name": "Euresearch",
            "icon": "🇨🇭",
            "url": "https://www.euresearch.ch/en/news",
            "status": "❌",
            "count": 0,
            "type": "Scraper",
        })

    try:
        params = {
            "apiKey": "SEDIA",
            "text": "frameworkProgramme/HORIZON",
            "type": "1",
            "pageSize": "1",
            "pageNumber": "1",
        }
        response = requests.get(EC_SEARCH_URL, params=params, timeout=10)
        total = 0
        if response.status_code == 200:
            total = response.json().get("totalResults", 0)

        statuses.append({
            "name": "EC F&T API",
            "icon": "🇪🇺",
            "url": EC_SEARCH_URL,
            "status": "✅" if response.status_code == 200 else "⚠️",
            "count": total,
            "type": "API",
        })

    except Exception:
        statuses.append({
            "name": "EC F&T API",
            "icon": "🇪🇺",
            "url": EC_SEARCH_URL,
            "status": "❌",
            "count": 0,
            "type": "API",
        })

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


def filter_news(news: List[Dict], query: str = "", source: str = "") -> List[Dict]:
    filtered = news

    if query:
        q = query.lower()
        filtered = [
            item for item in filtered
            if q in item.get("title", "").lower()
            or q in item.get("summary", "").lower()
            or q in item.get("source", "").lower()
            or q in item.get("tag", "").lower()
        ]

    if source:
        filtered = [
            item for item in filtered
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
