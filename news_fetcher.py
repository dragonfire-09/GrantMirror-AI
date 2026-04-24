"""
news_fetcher.py — Horizon Europe Canlı Haber Çekici
RSS + Web Scraper + EC API + UfukAvrupa + Euresearch
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
# RSS KAYNAKLARI
# ═══════════════════════════════════════════════════════════
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

    def get(self, key: str) -> Optional[list]:
        entry = self._store.get(key)
        if entry and (time.time() - entry["ts"]) < self.ttl:
            return entry["data"]
        return None

    def set(self, key: str, data: list):
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
# HTML TEMİZLEYİCİ
# ═══════════════════════════════════════════════════════════
def _clean_html(text: str) -> str:
    """HTML etiketlerini ve entity'leri temizle."""
    if not text:
        return ""
    if HAS_BS4:
        try:
            soup = BeautifulSoup(text, "html.parser")
            return soup.get_text(separator=" ", strip=True)
        except Exception:
            pass
    text = re.sub(r'<br\s*/?>', ' ', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'&\w+;', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ═══════════════════════════════════════════════════════════
# TARİH PARSER
# ═══════════════════════════════════════════════════════════
def _parse_date(entry) -> str:
    """RSS entry'den tarih çıkar."""
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
                try:
                    return raw[:10]
                except Exception:
                    pass
    return datetime.now().strftime("%Y-%m-%d")


# ═══════════════════════════════════════════════════════════
# KATEGORİ TESPİTİ
# ═══════════════════════════════════════════════════════════
def _is_horizon_related(title: str, summary: str) -> bool:
    """Haberin Horizon Europe ile ilgili olup olmadığını kontrol et."""
    combined = (title + " " + summary).lower()
    return any(kw in combined for kw in HORIZON_KEYWORDS)


def _detect_tag(title: str, summary: str, default_category: str) -> str:
    """Haberin kategorisini otomatik belirle."""
    combined = (title + " " + summary).lower()

    tag_rules = [
        (
            ["call for proposals", "new call", "calls open",
             "çağrı açıldı", "yeni çağrı", "open call"],
            "🆕 Yeni Çağrı",
        ),
        (["erc", "european research council"], "⭐ ERC"),
        (["eic", "pathfinder", "accelerator"], "💡 EIC"),
        (
            ["msca", "marie sklodowska", "marie curie", "doctoral network"],
            "🎓 MSCA",
        ),
        (
            ["mission", "cancer", "ocean", "climate adaptation",
             "soil health", "climate-neutral"],
            "🌍 Missions",
        ),
        (["widening", "twinning", "teaming", "era"], "🤝 Widening"),
        (
            ["work programme", "update", "amendment", "güncelleme"],
            "📋 Program Güncellemesi",
        ),
        (
            ["statistics", "success rate", "evaluation result", "istatistik"],
            "📊 İstatistik",
        ),
        (["guide", "guideline", "how to", "tip", "rehber"], "📝 Rehber"),
        (["cluster 4", "digital", "industry", "space"], "🔬 Cluster 4"),
        (["cluster 5", "climate", "energy", "mobility"], "🌿 Cluster 5"),
        (["cluster 1", "health"], "🏥 Cluster 1"),
        (["cluster 2", "culture", "creative", "society"], "🎭 Cluster 2"),
        (["cluster 3", "security", "civil"], "🛡️ Cluster 3"),
        (
            ["cluster 6", "food", "bioeconomy", "natural resources"],
            "🌾 Cluster 6",
        ),
        (["infrastructure", "research infrastructure"], "🏗️ Altyapı"),
    ]

    for keywords, tag in tag_rules:
        if any(kw in combined for kw in keywords):
            return tag

    return default_category


# ═══════════════════════════════════════════════════════════
# RSS ÇEKME
# ═══════════════════════════════════════════════════════════
def _fetch_rss_feed(url: str, timeout: int = 15):
    """RSS feed'i çek — feedparser + requests fallback."""
    if not HAS_FEEDPARSER:
        return None

    # Önce feedparser ile dene
    try:
        feed = feedparser.parse(
            url,
            agent="GrantMirror-AI/1.0",
        )
        if feed.entries:
            return feed
    except Exception:
        pass

    # requests + feedparser combo
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            feed = feedparser.parse(resp.content)
            if feed.entries:
                return feed
    except Exception:
        pass

    return None


def fetch_rss_news(
    source: dict,
    max_items: int = 20,
    horizon_only: bool = True,
) -> List[Dict]:
    """Tek bir RSS kaynağından haber çek."""
    cache_key = f"rss_{hashlib.md5(source['url'].encode()).hexdigest()}"
    cached = _news_cache.get(cache_key)
    if cached is not None:
        return cached

    items = []
    feed = _fetch_rss_feed(source["url"])

    if not feed or not feed.entries:
        _news_cache.set(cache_key, items)
        return items

    need_filter = source.get("horizon_filter", True) and horizon_only

    for entry in feed.entries[:max_items * 3]:
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
        tag = _detect_tag(
            title, summary, source.get("category", "📰 Haber")
        )

        item_id = hashlib.md5(
            (title + link).encode("utf-8")
        ).hexdigest()[:12]

        items.append({
            "id": item_id,
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


def fetch_all_rss_news(
    max_per_source: int = 15,
    horizon_only: bool = True,
) -> List[Dict]:
    """Tüm RSS kaynaklarından haber çek."""
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
            title_key = item["title"].lower()[:60]
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                all_items.append(item)

    # Az kaynak çalışıyorsa alternatifler
    if working_sources < 2:
        for source in ALT_RSS_SOURCES:
            items = fetch_rss_news(source, max_per_source, horizon_only)
            for item in items:
                title_key = item["title"].lower()[:60]
                if title_key not in seen_titles:
                    seen_titles.add(title_key)
                    all_items.append(item)

    all_items.sort(key=lambda x: x.get("date", ""), reverse=True)
    _news_cache.set(cache_key, all_items)
    return all_items


# ═══════════════════════════════════════════════════════════
# UFUK AVRUPA HABER SCRAPER
# ═══════════════════════════════════════════════════════════
UFUKAVRUPA_NEWS_URL = "https://ufukavrupa.org.tr/tr/haberler"
UFUKAVRUPA_BASE = "https://ufukavrupa.org.tr"


def fetch_ufukavrupa_news(max_items: int = 20) -> List[Dict]:
    """ufukavrupa.org.tr'den haber çek."""
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
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
        }

        urls_to_try = [
            UFUKAVRUPA_NEWS_URL,
            f"{UFUKAVRUPA_BASE}/tr",
            f"{UFUKAVRUPA_BASE}/tr/duyurular",
            f"{UFUKAVRUPA_BASE}/tr/etkinlikler",
        ]

        for url in urls_to_try:
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                containers = (
                    soup.select(".view-content .views-row")
                    or soup.select("article")
                    or soup.select(".node--type-article")
                    or soup.select(".card")
                    or soup.select(".news-item")
                    or soup.select(".list-item")
                )

                if not containers:
                    containers = []
                    for heading in soup.find_all(["h2", "h3", "h4"]):
                        parent = heading.parent
                        if parent:
                            containers.append(parent)

                for item_el in containers[:max_items * 2]:
                    news = _parse_ufukavrupa_news_item(item_el, url)
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


def _parse_ufukavrupa_news_item(item, source_url: str) -> Optional[Dict]:
    """UfukAvrupa haber öğesini parse et."""
    try:
        title_el = (
            item.select_one(
                "h2 a, h3 a, h4 a, .title a, .field--name-title a"
            )
            or item.select_one(
                "h2, h3, h4, .title, .field--name-title"
            )
        )
        if not title_el:
            return None

        title = _clean_html(title_el.get_text(strip=True))
        if not title or len(title) < 10:
            return None

        link = ""
        if title_el.name == "a":
            link = title_el.get("href", "")
        else:
            a = title_el.find("a")
            if a:
                link = a.get("href", "")
        if link and not link.startswith("http"):
            link = f"{UFUKAVRUPA_BASE}{link}"

        date_str = datetime.now().strftime("%Y-%m-%d")
        date_el = item.select_one(
            ".date, .field--name-created, time, "
            "[class*='date'], [class*='tarih']"
        )
        if date_el:
            raw_date = date_el.get_text(strip=True)
            date_match = re.search(
                r'(\d{1,2})[./](\d{1,2})[./](\d{4})', raw_date
            )
            if date_match:
                d, m, y = date_match.groups()
                date_str = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
            else:
                date_match2 = re.search(r'(\d{4}-\d{2}-\d{2})', raw_date)
                if date_match2:
                    date_str = date_match2.group(1)
                else:
                    dt_attr = date_el.get("datetime", "")
                    if dt_attr and len(dt_attr) >= 10:
                        date_str = dt_attr[:10]

        summary = ""
        summary_el = item.select_one(
            ".summary, .body, .teaser, .description, "
            ".field--name-body, p, .text, "
            "[class*='summary'], [class*='ozet']"
        )
        if summary_el:
            summary = _clean_html(summary_el.get_text(strip=True))
            if len(summary) > 400:
                summary = summary[:397] + "..."

        tag = _detect_tag(title, summary, "📋 Program Güncellemesi")

        item_id = hashlib.md5(
            (title + link).encode("utf-8")
        ).hexdigest()[:12]

        return {
            "id": item_id,
            "date": date_str,
            "tag": tag,
            "title": title,
            "summary": summary,
            "link": link or source_url,
            "source": "UfukAvrupa",
            "source_icon": "🇹🇷",
        }

    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# EC API — SON AÇILAN ÇAĞRILAR (HABER OLARAK)
# ═══════════════════════════════════════════════════════════
EC_SEARCH_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"


def _extract_meta_field(metadata: dict, field: str) -> str:
    """EC API metadata'dan alan çıkar."""
    for key, values in metadata.items():
        if field.lower() in key.lower():
            if isinstance(values, list) and values:
                v = values[0]
                if isinstance(v, dict):
                    return str(v.get("value", ""))
                return str(v)
            elif isinstance(values, str):
                return values
    return ""


def fetch_recent_calls_as_news(
    days: int = 30,
    max_items: int = 10,
) -> List[Dict]:
    """EC API'den son N günde açılan çağrıları haber olarak getir."""
    cache_key = f"recent_calls_news_{days}_{max_items}"
    cached = _news_cache.get(cache_key)
    if cached is not None:
        return cached

    items = []
    try:
        since = (
            datetime.now() - timedelta(days=days)
        ).strftime("%Y-%m-%d")
        params = {
            "apiKey": "SEDIA",
            "text": "*",
            "pageSize": str(min(max_items * 2, 50)),
            "pageNumber": "1",
            "sortBy": "startDate:desc",
            "query": (
                "(programmePeriod/code='2021-2027' AND "
                "frameworkProgramme/code='43108390')"
            ),
        }

        resp = requests.get(EC_SEARCH_URL, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])

            for r in results[:max_items]:
                meta = r.get("metadata", {})

                title = _clean_html(_extract_meta_field(meta, "title"))
                call_id = _clean_html(_extract_meta_field(meta, "identifier"))
                deadline = _clean_html(
                    _extract_meta_field(meta, "deadlineDate")
                )
                status = _clean_html(_extract_meta_field(meta, "status"))
                start_date = _clean_html(
                    _extract_meta_field(meta, "startDate")
                )

                if not title:
                    continue

                if start_date and len(start_date) >= 10:
                    if start_date[:10] < since:
                        continue

                link = ""
                if call_id:
                    link = (
                        f"https://ec.europa.eu/info/funding-tenders/"
                        f"opportunities/portal/screen/opportunities/"
                        f"topic-details/{call_id}"
                    )

                summary_parts = []
                if call_id:
                    summary_parts.append(f"Çağrı ID: {call_id}")
                if deadline:
                    summary_parts.append(f"Son tarih: {deadline[:10]}")
                if status:
                    summary_parts.append(f"Durum: {status}")
                summary = " | ".join(summary_parts)

                display_title = (
                    f"{call_id}: {title}" if call_id else title
                )

                items.append({
                    "id": hashlib.md5(
                        (call_id or title).encode()
                    ).hexdigest()[:12],
                    "date": (
                        start_date[:10]
                        if start_date and len(start_date) >= 10
                        else datetime.now().strftime("%Y-%m-%d")
                    ),
                    "tag": "🆕 Yeni Çağrı",
                    "title": display_title,
                    "summary": summary,
                    "link": link,
                    "source": "EC F&T Portal",
                    "source_icon": "🇪🇺",
                })

    except Exception:
        pass

    _news_cache.set(cache_key, items)
    return items


# ═══════════════════════════════════════════════════════════
# EURESEARCH HABER SCRAPER
# ═══════════════════════════════════════════════════════════
EURESEARCH_NEWS_URLS = [
    "https://www.euresearch.ch/en/news",
    "https://www.euresearch.ch/en/our-services/inform",
]


def fetch_euresearch_news(max_items: int = 15) -> List[Dict]:
    """Euresearch.ch'den haber çek."""
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
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
        }

        for url in EURESEARCH_NEWS_URLS:
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                containers = (
                    soup.select(".view-content .views-row")
                    or soup.select("article")
                    or soup.select(".news-item")
                    or soup.select(".card")
                    or soup.select(".teaser")
                )

                if not containers:
                    for a in soup.find_all("a", href=True):
                        text = a.get_text(strip=True)
                        href = a.get("href", "")
                        if len(text) >= 20 and any(
                            kw in (text + href).lower()
                            for kw in [
                                "news", "event", "call", "horizon",
                            ]
                        ):
                            parent = a.parent if a.parent else a
                            containers.append(parent)

                for container in containers[:max_items]:
                    news = _parse_euresearch_news_item(container)
                    if (
                        news
                        and news.get("title")
                        and len(news["title"]) > 10
                    ):
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
    """Euresearch haber öğesi parse."""
    try:
        title_el = (
            item.select_one("h2 a, h3 a, h4 a, .title a, a")
            or item.select_one("h2, h3, h4, .title")
        )
        if not title_el:
            return None

        title = _clean_html(title_el.get_text(strip=True))
        if not title or len(title) < 10:
            return None

        link = ""
        if title_el.name == "a":
            link = title_el.get("href", "")
        else:
            a = title_el.find("a")
            if a:
                link = a.get("href", "")
        if link and not link.startswith("http"):
            link = f"https://www.euresearch.ch{link}"

        date_str = datetime.now().strftime("%Y-%m-%d")
        date_el = item.select_one(".date, time, [class*='date']")
        if date_el:
            raw = date_el.get_text(strip=True)
            dm = re.search(r'(\d{4}-\d{2}-\d{2})', raw)
            if dm:
                date_str = dm.group(1)
            else:
                dt_attr = date_el.get("datetime", "")
                if dt_attr and len(dt_attr) >= 10:
                    date_str = dt_attr[:10]

        summary = ""
        sum_el = item.select_one(
            ".summary, .teaser, .body, p, .description"
        )
        if sum_el:
            summary = _clean_html(sum_el.get_text(strip=True))
            if len(summary) > 400:
                summary = summary[:397] + "..."

        tag = _detect_tag(title, summary, "📋 Program Güncellemesi")

        return {
            "id": hashlib.md5(title.encode()).hexdigest()[:12],
            "date": date_str,
            "tag": tag,
            "title": title,
            "summary": summary,
            "link": link or "https://www.euresearch.ch",
            "source": "Euresearch",
            "source_icon": "🇨🇭",
        }
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# FALLBACK — STATİK HABERLER
# ═══════════════════════════════════════════════════════════
FALLBACK_NEWS = [
    {
        "id": "fb1",
        "date": "2025-01-15",
        "tag": "🆕 Yeni Çağrı",
        "title": "Cluster 5 — Climate, Energy and Mobility 2025 çağrıları açıldı",
        "summary": (
            "Enerji dönüşümü, sürdürülebilir ulaşım ve iklim bilimi "
            "alanlarında toplam €2.3 milyar bütçeli çağrılar başvuruya açıldı."
        ),
        "link": (
            "https://ec.europa.eu/info/funding-tenders/opportunities/"
            "portal/screen/opportunities/topic-search"
        ),
        "source": "Statik",
        "source_icon": "📌",
    },
    {
        "id": "fb2",
        "date": "2025-01-10",
        "tag": "📋 Program Güncellemesi",
        "title": "Horizon Europe Work Programme 2025 güncellemeleri yayınlandı",
        "summary": (
            "2025 yılı iş programında yapılan değişiklikler açıklandı. "
            "Yeni topic'ler eklendi ve bazı deadline'lar güncellendi."
        ),
        "link": (
            "https://research-and-innovation.ec.europa.eu/funding/"
            "funding-opportunities/funding-programmes-and-open-calls/"
            "horizon-europe/horizon-europe-work-programmes_en"
        ),
        "source": "Statik",
        "source_icon": "📌",
    },
    {
        "id": "fb3",
        "date": "2025-01-08",
        "tag": "🎓 MSCA",
        "title": "MSCA Doctoral Networks 2025 — Başvuru rehberi güncellendi",
        "summary": (
            "Marie Skłodowska-Curie Doctoral Networks için 2025 çağrı "
            "rehberi yayınlandı. Yeni değerlendirme kriterleri açıklandı."
        ),
        "link": (
            "https://marie-sklodowska-curie-actions.ec.europa.eu/"
            "actions/doctoral-networks"
        ),
        "source": "Statik",
        "source_icon": "📌",
    },
    {
        "id": "fb4",
        "date": "2025-01-05",
        "tag": "💡 EIC",
        "title": "EIC Pathfinder Open 2025 — Başvurular başladı",
        "summary": (
            "Çığır açan teknolojiler için €3-4M bütçeli Pathfinder Open "
            "çağrısı açıldı. Son başvuru: 12 Mart 2025."
        ),
        "link": (
            "https://eic.ec.europa.eu/eic-funding-opportunities/"
            "eic-pathfinder_en"
        ),
        "source": "Statik",
        "source_icon": "📌",
    },
    {
        "id": "fb5",
        "date": "2024-12-20",
        "tag": "⭐ ERC",
        "title": "ERC Advanced Grants 2025 çağrısı açıldı",
        "summary": (
            "Kıdemli araştırmacılar için €2.5M'a kadar bütçeli Advanced "
            "Grants başvuruları başladı."
        ),
        "link": "https://erc.europa.eu/apply-grant/advanced-grant",
        "source": "Statik",
        "source_icon": "📌",
    },
    {
        "id": "fb6",
        "date": "2024-12-18",
        "tag": "🌍 Missions",
        "title": "EU Missions 2025 çağrıları — Kanser, Okyanus, İklim, Toprak, Şehir",
        "summary": (
            "5 EU Mission alanında yeni çağrılar yayınlandı. "
            "Toplam bütçe: €1.8 milyar."
        ),
        "link": (
            "https://research-and-innovation.ec.europa.eu/funding/"
            "funding-opportunities/funding-programmes-and-open-calls/"
            "horizon-europe/eu-missions-horizon-europe_en"
        ),
        "source": "Statik",
        "source_icon": "📌",
    },
    {
        "id": "fb7",
        "date": "2024-12-15",
        "tag": "📊 İstatistik",
        "title": "Horizon Europe 2024 değerlendirme istatistikleri açıklandı",
        "summary": (
            "2024 yılında toplam 48,000+ başvuru alındı. "
            "Ortalama başarı oranı %15.2."
        ),
        "link": (
            "https://ec.europa.eu/info/funding-tenders/opportunities/"
            "portal/screen/opportunities/horizon-dashboard"
        ),
        "source": "Statik",
        "source_icon": "📌",
    },
    {
        "id": "fb8",
        "date": "2024-12-10",
        "tag": "🤝 Widening",
        "title": "Widening Participation — Twinning ve Teaming 2025 çağrıları",
        "summary": (
            "Araştırma kapasitesi düşük ülkeler için kapasite geliştirme "
            "çağrıları açıldı."
        ),
        "link": (
            "https://research-and-innovation.ec.europa.eu/funding/"
            "funding-opportunities/funding-programmes-and-open-calls/"
            "horizon-europe/widening-participation-and-spreading-"
            "excellence_en"
        ),
        "source": "Statik",
        "source_icon": "📌",
    },
]


# ═══════════════════════════════════════════════════════════
# ANA FONKSİYON — TÜM KAYNAKLAR
# ═══════════════════════════════════════════════════════════
def get_news_with_fallback(
    max_per_source: int = 15,
    horizon_only: bool = True,
    include_recent_calls: bool = True,
    include_ufukavrupa: bool = True,
    include_euresearch: bool = True,
) -> List[Dict]:
    """RSS + Scraper + EC API + Fallback ile haber getir."""
    cache_key = (
        f"all_news_{max_per_source}_{horizon_only}_"
        f"{include_recent_calls}_{include_ufukavrupa}_"
        f"{include_euresearch}"
    )
    cached = _news_cache.get(cache_key)
    if cached is not None:
        return cached

    all_news = []

    # 1. RSS haberleri
    try:
        rss_news = fetch_all_rss_news(max_per_source, horizon_only)
        all_news.extend(rss_news)
    except Exception:
        pass

    # 2. UfukAvrupa haberleri
    if include_ufukavrupa:
        try:
            ua_news = fetch_ufukavrupa_news(max_per_source)
            all_news.extend(ua_news)
        except Exception:
            pass

    # 3. Euresearch haberleri
    if include_euresearch:
        try:
            eur_news = fetch_euresearch_news(max_per_source)
            all_news.extend(eur_news)
        except Exception:
            pass

    # 4. Son açılan çağrılar (haber olarak)
    if include_recent_calls:
        try:
            call_news = fetch_recent_calls_as_news(days=30, max_items=10)
            all_news.extend(call_news)
        except Exception:
            pass

    # 5. Hiç haber yoksa fallback
    if not all_news:
        all_news = FALLBACK_NEWS.copy()

    # Deduplicate
    seen = set()
    unique = []
    for item in all_news:
        key = item.get("title", "")[:60].lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    # Tarihe göre sırala
    unique.sort(key=lambda x: x.get("date", ""), reverse=True)

    _news_cache.set(cache_key, unique)
    return unique


# ═══════════════════════════════════════════════════════════
# KAYNAK DURUMU
# ═══════════════════════════════════════════════════════════
def get_news_sources_status() -> List[Dict]:
    """Her haber kaynağının durumunu kontrol et."""
    statuses = []

    # RSS kaynakları
    for source in RSS_SOURCES:
        try:
            feed = _fetch_rss_feed(source["url"])
            ok = feed is not None and bool(getattr(feed, 'entries', []))
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

    # UfukAvrupa
    try:
        headers = {"User-Agent": "GrantMirror-AI/1.0", "Accept": "text/html"}
        resp = requests.get(
            UFUKAVRUPA_NEWS_URL, headers=headers, timeout=10,
        )
        statuses.append({
            "name": "UfukAvrupa",
            "icon": "🇹🇷",
            "url": UFUKAVRUPA_NEWS_URL,
            "status": "✅" if resp.status_code == 200 else "⚠️",
            "count": -1,
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

    # Euresearch
    try:
        headers = {"User-Agent": "GrantMirror-AI/1.0", "Accept": "text/html"}
        resp = requests.get(
            "https://www.euresearch.ch/en/news",
            headers=headers, timeout=10,
        )
        statuses.append({
            "name": "Euresearch",
            "icon": "🇨🇭",
            "url": "https://www.euresearch.ch/en/news",
            "status": "✅" if resp.status_code == 200 else "⚠️",
            "count": -1,
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

    # EC API
    try:
        params = {
            "apiKey": "SEDIA",
            "text": "*",
            "pageSize": "1",
            "pageNumber": "1",
            "query": (
                "programmePeriod/code='2021-2027' AND "
                "frameworkProgramme/code='43108390'"
            ),
        }
        resp = requests.get(EC_SEARCH_URL, params=params, timeout=10)
        total = 0
        if resp.status_code == 200:
            total = resp.json().get("totalResults", 0)
        statuses.append({
            "name": "EC F&T API",
            "icon": "🇪🇺",
            "url": EC_SEARCH_URL,
            "status": "✅" if resp.status_code == 200 else "⚠️",
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
