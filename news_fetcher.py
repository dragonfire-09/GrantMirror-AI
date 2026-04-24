"""
news_fetcher.py — Horizon Europe RSS haber çekici
"""
import feedparser
import time
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import re
import requests


# ═══════════════════════════════════════════════════════════
# RSS KAYNAKLARI
# ═══════════════════════════════════════════════════════════
RSS_SOURCES = [
    {
        "name": "CORDIS News",
        "url": "https://cordis.europa.eu/news/rss",
        "icon": "🇪🇺",
        "category": "📋 Program Güncellemesi",
    },
    {
        "name": "CORDIS Results",
        "url": "https://cordis.europa.eu/article/rss",
        "icon": "🔬",
        "category": "🔬 Araştırma Sonuçları",
    },
    {
        "name": "EC R&I News",
        "url": "https://research-and-innovation.ec.europa.eu/news/rss.xml",
        "icon": "📡",
        "category": "📋 Program Güncellemesi",
    },
    {
        "name": "ERC News",
        "url": "https://erc.europa.eu/news/rss.xml",
        "icon": "⭐",
        "category": "⭐ ERC",
    },
    {
        "name": "EIC News",
        "url": "https://eic.ec.europa.eu/news/rss.xml",
        "icon": "💡",
        "category": "💡 EIC",
    },
    {
        "name": "MSCA News",
        "url": "https://marie-sklodowska-curie-actions.ec.europa.eu/news/rss.xml",
        "icon": "🎓",
        "category": "🎓 MSCA",
    },
]

# Horizon Europe ile ilgili anahtar kelimeler (filtreleme için)
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
    "trl", "technology readiness",
    "ria", "innovation action", "coordination and support",
    "lump sum", "proposal", "evaluation",
    "pillar", "destination", "topic",
]


# ═══════════════════════════════════════════════════════════
# CACHE
# ═══════════════════════════════════════════════════════════
class NewsCache:
    """Basit bellek içi cache."""

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


_news_cache = NewsCache(ttl_minutes=15)


# ═══════════════════════════════════════════════════════════
# RSS PARSER
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
            # Yaygın formatları dene
            for fmt in ("%a, %d %b %Y %H:%M:%S %z",
                        "%Y-%m-%dT%H:%M:%S%z",
                        "%Y-%m-%d %H:%M:%S",
                        "%d %b %Y"):
                try:
                    return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
                except Exception:
                    continue
            # En azından ilk 10 karakteri dene
            if len(raw) >= 10:
                return raw[:10]
    return datetime.now().strftime("%Y-%m-%d")


def _clean_html(text: str) -> str:
    """Basit HTML temizleyici."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#\d+;", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_horizon_related(title: str, summary: str) -> bool:
    """Haberin Horizon Europe ile ilgili olup olmadığını kontrol et."""
    combined = (title + " " + summary).lower()
    return any(kw in combined for kw in HORIZON_KEYWORDS)


def _detect_tag(title: str, summary: str, default_category: str) -> str:
    """Haberin kategorisini otomatik belirle."""
    combined = (title + " " + summary).lower()

    tag_rules = [
        (["call for proposals", "new call", "calls open", "çağrı"],
         "🆕 Yeni Çağrı"),
        (["erc", "european research council"],
         "⭐ ERC"),
        (["eic", "pathfinder", "accelerator"],
         "💡 EIC"),
        (["msca", "marie sklodowska", "marie curie", "doctoral network"],
         "🎓 MSCA"),
        (["mission", "cancer", "ocean", "climate", "soil", "cities"],
         "🌍 Missions"),
        (["widening", "twinning", "teaming"],
         "🤝 Widening"),
        (["work programme", "update", "amendment"],
         "📋 Program Güncellemesi"),
        (["statistics", "success rate", "evaluation result"],
         "📊 İstatistik"),
        (["guide", "guideline", "how to", "tip"],
         "📝 Rehber"),
        (["cluster 4", "digital", "industry", "space"],
         "🔬 Cluster 4"),
        (["cluster 5", "climate", "energy", "mobility"],
         "🌿 Cluster 5"),
        (["cluster 1", "health"],
         "🏥 Cluster 1"),
        (["cluster 6", "food", "bioeconomy", "natural resources"],
         "🌾 Cluster 6"),
    ]

    for keywords, tag in tag_rules:
        if any(kw in combined for kw in keywords):
            return tag

    return default_category


def fetch_rss_news(
    source: dict,
    max_items: int = 20,
    horizon_only: bool = True,
) -> List[Dict]:
    """Tek bir RSS kaynağından haber çek."""
    cache_key = f"rss_{source['url']}_{max_items}_{horizon_only}"
    cached = _news_cache.get(cache_key)
    if cached is not None:
        return cached

    items = []
    try:
        feed = feedparser.parse(
            source["url"],
            agent="GrantMirror-AI/1.0 (+https://grantmirror.ai)",
        )

        if feed.bozo and not feed.entries:
            # Feed parse hatası ve entry yok
            return items

        for entry in feed.entries[:max_items * 2]:  # Fazla çek, filtrele
            title = _clean_html(getattr(entry, "title", ""))
            summary = _clean_html(
                getattr(entry, "summary", "")
                or getattr(entry, "description", "")
            )
            link = getattr(entry, "link", "")

            if not title:
                continue

            # Horizon filtresi
            if horizon_only and not _is_horizon_related(title, summary):
                continue

            # Özeti kısalt
            if len(summary) > 300:
                summary = summary[:297] + "..."

            date_str = _parse_date(entry)
            tag = _detect_tag(title, summary, source.get("category", "📰 Haber"))

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

    except Exception as e:
        items.append({
            "id": "error",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "tag": "⚠️ Hata",
            "title": f"{source['name']} — RSS okunamadı",
            "summary": str(e)[:200],
            "link": "",
            "source": source["name"],
            "source_icon": "⚠️",
        })

    _news_cache.set(cache_key, items)
    return items


def fetch_all_news(
    max_per_source: int = 15,
    horizon_only: bool = True,
    sources: Optional[List[dict]] = None,
) -> List[Dict]:
    """Tüm RSS kaynaklarından haber çek ve birleştir."""
    if sources is None:
        sources = RSS_SOURCES

    cache_key = f"all_news_{max_per_source}_{horizon_only}_{len(sources)}"
    cached = _news_cache.get(cache_key)
    if cached is not None:
        return cached

    all_items = []
    seen_titles = set()

    for source in sources:
        items = fetch_rss_news(source, max_per_source, horizon_only)
        for item in items:
            # Duplicate kontrolü (benzer başlıkları filtrele)
            title_key = item["title"].lower()[:60]
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                all_items.append(item)

    # Tarihe göre sırala (en yeni önce)
    all_items.sort(key=lambda x: x.get("date", ""), reverse=True)

    _news_cache.set(cache_key, all_items)
    return all_items


# ═══════════════════════════════════════════════════════════
# EC FUNDING & TENDERS API — Yeni Çağrı Haberleri
# ═══════════════════════════════════════════════════════════
def fetch_recent_calls_as_news(days: int = 30, max_items: int = 10) -> List[Dict]:
    """EC API'den son N günde açılan çağrıları haber olarak getir."""
    cache_key = f"recent_calls_news_{days}_{max_items}"
    cached = _news_cache.get(cache_key)
    if cached is not None:
        return cached

    items = []
    try:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        url = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
        params = {
            "apiKey": "SEDIA",
            "text": "*",
            "pageSize": str(max_items),
            "pageNumber": "1",
            "sortBy": "startDate:desc",
            "query": f"(programmePeriod/code='2021-2027' AND frameworkProgramme/code='43108390') AND startDate>={since}",
        }
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            for r in results[:max_items]:
                meta = r.get("metadata", {})

                title = _extract_field(meta, "title")
                call_id = _extract_field(meta, "identifier")
                deadline = _extract_field(meta, "deadlineDate")
                status = _extract_field(meta, "status")
                start_date = _extract_field(meta, "startDate")

                if not title:
                    continue

                link = f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{call_id}" if call_id else ""

                summary = f"Çağrı ID: {call_id}"
                if deadline:
                    summary += f" | Son tarih: {deadline[:10]}"
                if status:
                    summary += f" | Durum: {status}"

                items.append({
                    "id": hashlib.md5(call_id.encode()).hexdigest()[:12] if call_id else "unknown",
                    "date": start_date[:10] if start_date else datetime.now().strftime("%Y-%m-%d"),
                    "tag": "🆕 Yeni Çağrı",
                    "title": f"{call_id}: {title}" if call_id else title,
                    "summary": summary,
                    "link": link,
                    "source": "EC F&T Portal",
                    "source_icon": "🇪🇺",
                })

    except Exception:
        pass

    _news_cache.set(cache_key, items)
    return items


def _extract_field(metadata: dict, field: str) -> str:
    """EC API metadata'dan alan çıkar."""
    for key, values in metadata.items():
        if field.lower() in key.lower():
            if isinstance(values, list) and values:
                v = values[0]
                if isinstance(v, dict):
                    return v.get("value", str(v))
                return str(v)
            return str(values)
    return ""


# ═══════════════════════════════════════════════════════════
# FALLBACK — Statik haberler (RSS çalışmazsa)
# ═══════════════════════════════════════════════════════════
FALLBACK_NEWS = [
    {
        "id": "fb1",
        "date": "2025-01-15",
        "tag": "🆕 Yeni Çağrı",
        "title": "Cluster 5 — Climate, Energy and Mobility 2025 çağrıları açıldı",
        "summary": "Enerji dönüşümü, sürdürülebilir ulaşım ve iklim bilimi "
                   "alanlarında toplam €2.3 milyar bütçeli çağrılar başvuruya açıldı.",
        "link": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/"
                "screen/opportunities/topic-search",
        "source": "Statik",
        "source_icon": "📌",
    },
    {
        "id": "fb2",
        "date": "2025-01-10",
        "tag": "📋 Program Güncellemesi",
        "title": "Horizon Europe Work Programme 2025 güncellemeleri yayınlandı",
        "summary": "2025 yılı iş programında yapılan değişiklikler açıklandı. "
                   "Yeni topic'ler eklendi ve bazı deadline'lar güncellendi.",
        "link": "https://research-and-innovation.ec.europa.eu/funding/"
                "funding-opportunities/funding-programmes-and-open-calls/"
                "horizon-europe/horizon-europe-work-programmes_en",
        "source": "Statik",
        "source_icon": "📌",
    },
    {
        "id": "fb3",
        "date": "2025-01-08",
        "tag": "🎓 MSCA",
        "title": "MSCA Doctoral Networks 2025 — Başvuru rehberi güncellendi",
        "summary": "Marie Skłodowska-Curie Doctoral Networks için 2025 çağrı "
                   "rehberi yayınlandı. Yeni değerlendirme kriterleri açıklandı.",
        "link": "https://marie-sklodowska-curie-actions.ec.europa.eu/"
                "actions/doctoral-networks",
        "source": "Statik",
        "source_icon": "📌",
    },
    {
        "id": "fb4",
        "date": "2025-01-05",
        "tag": "💡 EIC",
        "title": "EIC Pathfinder Open 2025 — Başvurular başladı",
        "summary": "Çığır açan teknolojiler için €3-4M bütçeli Pathfinder Open "
                   "çağrısı açıldı. Son başvuru: 12 Mart 2025.",
        "link": "https://eic.ec.europa.eu/eic-funding-opportunities/"
                "eic-pathfinder_en",
        "source": "Statik",
        "source_icon": "📌",
    },
    {
        "id": "fb5",
        "date": "2024-12-20",
        "tag": "⭐ ERC",
        "title": "ERC Advanced Grants 2025 çağrısı açıldı",
        "summary": "Kıdemli araştırmacılar için €2.5M'a kadar bütçeli Advanced "
                   "Grants başvuruları başladı.",
        "link": "https://erc.europa.eu/apply-grant/advanced-grant",
        "source": "Statik",
        "source_icon": "📌",
    },
]


def get_news_with_fallback(
    max_per_source: int = 15,
    horizon_only: bool = True,
    include_recent_calls: bool = True,
) -> List[Dict]:
    """RSS + EC API + fallback ile haber getir."""
    all_news = []

    # 1. RSS haberleri
    rss_news = fetch_all_news(max_per_source, horizon_only)
    all_news.extend(rss_news)

    # 2. Son açılan çağrılar (haber olarak)
    if include_recent_calls:
        call_news = fetch_recent_calls_as_news(days=30, max_items=10)
        all_news.extend(call_news)

    # 3. Hiç haber yoksa fallback
    if not all_news:
        all_news = FALLBACK_NEWS.copy()

    # Deduplicate
    seen = set()
    unique = []
    for item in all_news:
        key = item.get("title", "")[:60].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)

    # Tarihe göre sırala
    unique.sort(key=lambda x: x.get("date", ""), reverse=True)

    return unique


def get_news_sources_status() -> List[Dict]:
    """Her RSS kaynağının durumunu kontrol et."""
    statuses = []
    for source in RSS_SOURCES:
        try:
            feed = feedparser.parse(source["url"])
            ok = bool(feed.entries) and not feed.bozo
            statuses.append({
                "name": source["name"],
                "icon": source.get("icon", "📰"),
                "url": source["url"],
                "status": "✅" if ok else "⚠️",
                "count": len(feed.entries) if ok else 0,
            })
        except Exception as e:
            statuses.append({
                "name": source["name"],
                "icon": source.get("icon", "📰"),
                "url": source["url"],
                "status": "❌",
                "count": 0,
                "error": str(e)[:100],
            })
    return statuses
