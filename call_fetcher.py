"""
call_fetcher.py — Horizon Europe Çağrı Çekici
EC API + Euresearch Scraper + UfukAvrupa + Yerel DB
"""
import requests
import time
import re
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from io import BytesIO

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


# ═══════════════════════════════════════════════════════════
# CACHE
# ═══════════════════════════════════════════════════════════
class CallCache:
    def __init__(self, ttl_minutes: int = 30):
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


# ═══════════════════════════════════════════════════════════
# HTML TEMİZLEYİCİ
# ═══════════════════════════════════════════════════════════
def clean_html(text: str) -> str:
    """HTML etiketlerini ve entity'leri temizle."""
    if not text:
        return ""
    if HAS_BS4:
        try:
            soup = BeautifulSoup(text, "html.parser")
            return soup.get_text(separator=" ", strip=True)
        except Exception:
            pass
    # Fallback: regex
    text = re.sub(r'<br\s*/?>', ' ', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#39;', "'", text)
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'&\w+;', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ═══════════════════════════════════════════════════════════
# EC FUNDING & TENDERS API
# ═══════════════════════════════════════════════════════════
EC_SEARCH_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"

def _extract_ec_field(metadata: dict, field_name: str) -> str:
    """EC API metadata'dan alan çıkar."""
    for key, values in metadata.items():
        if field_name.lower() in key.lower():
            if isinstance(values, list) and values:
                v = values[0]
                if isinstance(v, dict):
                    return str(v.get("value", ""))
                return str(v)
            elif isinstance(values, str):
                return values
    return ""


def _extract_ec_list(metadata: dict, field_name: str) -> List[str]:
    """EC API metadata'dan liste çıkar."""
    for key, values in metadata.items():
        if field_name.lower() in key.lower():
            if isinstance(values, list):
                result = []
                for v in values:
                    if isinstance(v, dict):
                        result.append(str(v.get("value", "")))
                    else:
                        result.append(str(v))
                return result
    return []


def fetch_horizon_calls(
    search_text: str = "",
    status: str = "",
    max_results: int = 100,
) -> List[Dict]:
    """EC Funding & Tenders API'den Horizon Europe çağrılarını çek."""
    calls = []
    try:
        query_parts = [
            "programmePeriod/code='2021-2027'",
            "frameworkProgramme/code='43108390'",
        ]
        if status:
            status_map = {
                "open": "31094501",
                "forthcoming": "31094502",
                "closed": "31094503",
            }
            sc = status_map.get(status.lower(), "")
            if sc:
                query_parts.append(f"status/code='{sc}'")

        query = " AND ".join(query_parts)

        page_size = min(max_results, 100)
        pages_needed = (max_results + page_size - 1) // page_size

        for page_num in range(1, pages_needed + 1):
            params = {
                "apiKey": "SEDIA",
                "text": search_text if search_text else "*",
                "pageSize": str(page_size),
                "pageNumber": str(page_num),
                "sortBy": "deadlineDate:desc",
                "query": query,
            }

            resp = requests.get(EC_SEARCH_URL, params=params, timeout=20)
            if resp.status_code != 200:
                break

            data = resp.json()
            results = data.get("results", [])
            if not results:
                break

            for r in results:
                meta = r.get("metadata", {})

                call_id = clean_html(_extract_ec_field(meta, "identifier"))
                title = clean_html(_extract_ec_field(meta, "title"))
                status_val = clean_html(_extract_ec_field(meta, "status"))
                deadline = clean_html(_extract_ec_field(meta, "deadlineDate"))
                start_date = clean_html(_extract_ec_field(meta, "startDate"))
                budget = clean_html(_extract_ec_field(meta, "budget"))
                desc = clean_html(_extract_ec_field(meta, "description"))
                types = _extract_ec_list(meta, "typesOfAction")
                types = [clean_html(t) for t in types]

                if not call_id and not title:
                    continue

                # Status mapping
                status_display = status_val
                if "open" in status_val.lower() or "31094501" in status_val:
                    status_display = "Open"
                elif "forthcoming" in status_val.lower() or "31094502" in status_val:
                    status_display = "Forthcoming"
                elif "closed" in status_val.lower() or "31094503" in status_val:
                    status_display = "Closed"

                link = ""
                if call_id:
                    link = (
                        f"https://ec.europa.eu/info/funding-tenders/"
                        f"opportunities/portal/screen/opportunities/"
                        f"topic-details/{call_id}"
                    )

                calls.append({
                    "call_id": call_id or "N/A",
                    "title": title or call_id or "N/A",
                    "status": status_display,
                    "deadline": deadline[:10] if deadline else "N/A",
                    "start_date": start_date[:10] if start_date else "",
                    "budget_total": budget,
                    "budget_per_project": "",
                    "action_types": types if types else ["RIA"],
                    "description": desc[:500] if desc else "",
                    "keywords": [],
                    "destination": "",
                    "scope": desc[:1000] if desc else "",
                    "expected_outcomes": "",
                    "link": link,
                    "source": "EC API",
                    "topics": [{"topic_id": call_id}] if call_id else [],
                })

            if len(results) < page_size:
                break
            if len(calls) >= max_results:
                break

    except Exception as e:
        calls.append({
            "call_id": "EC_API_ERROR",
            "title": f"EC API Hatası: {str(e)[:100]}",
            "status": "Error",
            "deadline": "N/A",
            "action_types": ["N/A"],
            "source": "EC API",
            "link": "",
            "keywords": [],
            "destination": "",
            "scope": "",
            "expected_outcomes": "",
            "topics": [],
            "budget_total": "",
            "budget_per_project": "",
            "description": str(e),
            "start_date": "",
        })

    return calls[:max_results]


def fetch_topic_details(topic_id: str) -> Optional[Dict]:
    """Tek bir topic'in detaylarını çek."""
    try:
        params = {
            "apiKey": "SEDIA",
            "text": f'"{topic_id}"',
            "pageSize": "1",
            "pageNumber": "1",
            "query": f"identifier/code='{topic_id}'",
        }
        resp = requests.get(EC_SEARCH_URL, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            if results:
                meta = results[0].get("metadata", {})
                return {
                    "topic_id": topic_id,
                    "title": clean_html(_extract_ec_field(meta, "title")),
                    "description": clean_html(_extract_ec_field(meta, "description")),
                    "budget": clean_html(_extract_ec_field(meta, "budget")),
                    "deadline": clean_html(_extract_ec_field(meta, "deadlineDate")),
                    "conditions": clean_html(_extract_ec_field(meta, "conditions")),
                }
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════
# EURESEARCH SCRAPER — DÜZELTİLMİŞ
# ═══════════════════════════════════════════════════════════
EURESEARCH_URL = "https://www.euresearch.ch/en/our-services/inform/open-calls-137.html"


def fetch_euresearch_calls(max_results: int = 50) -> List[Dict]:
    """Euresearch.ch'den açık çağrıları scrape et — HTML temizlenmiş."""
    if not HAS_BS4:
        return []

    calls = []
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        resp = requests.get(EURESEARCH_URL, headers=headers, timeout=20)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # Euresearch yapısını tara — çeşitli CSS seçiciler dene
        call_containers = (
            soup.select(".call-item")
            or soup.select(".view-content .views-row")
            or soup.select("article.node")
            or soup.select(".field-content")
            or soup.select("table tbody tr")
            or soup.select(".item-list li")
        )

        # Eğer yapısal seçici bulamazsak, tüm linkleri tara
        if not call_containers:
            call_containers = _euresearch_fallback_parse(soup)

        for item in call_containers[:max_results]:
            call = _parse_euresearch_item(item)
            if call and call.get("title") and call["title"] != "N/A":
                calls.append(call)

        # Son çare: sayfadaki tüm h3/h4'leri tara
        if not calls:
            calls = _euresearch_heading_parse(soup, max_results)

    except Exception as e:
        calls.append({
            "call_id": "EUR_SCRAPE_ERROR",
            "title": f"Euresearch Scrape Hatası: {str(e)[:100]}",
            "status": "Error",
            "deadline": "N/A",
            "action_types": ["N/A"],
            "source": "Euresearch",
            "link": EURESEARCH_URL,
            "keywords": [],
            "destination": "",
            "scope": "",
            "expected_outcomes": "",
            "topics": [],
            "budget_total": "",
            "budget_per_project": "",
            "description": str(e),
            "start_date": "",
        })

    return calls


def _parse_euresearch_item(item) -> Optional[Dict]:
    """Bir Euresearch çağrı öğesini parse et."""
    try:
        # Başlık bul
        title_el = (
            item.select_one("h2 a, h3 a, h4 a, .title a, .field-title a")
            or item.select_one("h2, h3, h4, .title, .field-title")
            or item.select_one("a[href*='call'], a[href*='topic']")
        )
        if not title_el:
            # Tüm metni al
            text = item.get_text(separator=" ", strip=True)
            if len(text) < 10:
                return None
            title = text[:200]
            link = ""
        else:
            title = title_el.get_text(strip=True)
            link = title_el.get("href", "") if title_el.name == "a" else ""
            if not link:
                a = title_el.find("a")
                if a:
                    link = a.get("href", "")

        title = clean_html(title)
        if not title or len(title) < 3:
            return None

        # Link düzelt
        if link and not link.startswith("http"):
            link = f"https://www.euresearch.ch{link}"

        # Status bul
        status = "Open"
        status_el = item.select_one(
            ".status, .badge, .label, .tag, "
            "[class*='status'], [class*='badge']"
        )
        if status_el:
            st_text = status_el.get_text(strip=True).lower()
            if "forthcoming" in st_text or "upcoming" in st_text:
                status = "Forthcoming"
            elif "closed" in st_text:
                status = "Closed"

        # Sayfadaki tüm metinde status ara
        full_text = item.get_text(separator=" ", strip=True).lower()
        if "forthcoming" in full_text:
            status = "Forthcoming"
        elif "closed" in full_text:
            status = "Closed"

        # Tarih bul
        deadline = "N/A"
        date_pattern = re.compile(r'(\d{4}-\d{2}-\d{2})')
        date_match = date_pattern.search(item.get_text())
        if date_match:
            deadline = date_match.group(1)
        else:
            # Diğer tarih formatları
            date_pattern2 = re.compile(
                r'(\d{1,2})\s+(January|February|March|April|May|June|'
                r'July|August|September|October|November|December)\s+(\d{4})',
                re.IGNORECASE,
            )
            dm2 = date_pattern2.search(item.get_text())
            if dm2:
                try:
                    deadline = datetime.strptime(
                        dm2.group(0), "%d %B %Y"
                    ).strftime("%Y-%m-%d")
                except Exception:
                    deadline = dm2.group(0)

        # Bütçe bul
        budget = ""
        budget_pattern = re.compile(r'€[\d.,]+[MmKkBb]?')
        budget_match = budget_pattern.search(item.get_text())
        if budget_match:
            budget = budget_match.group(0)

        # Aksiyon türü bul
        action_types = []
        at_patterns = {
            "RIA": r'\bRIA\b',
            "IA": r'\bIA\b',
            "CSA": r'\bCSA\b',
            "ERC-StG": r'ERC.{0,5}(Starting|StG)',
            "ERC-CoG": r'ERC.{0,5}(Consolidator|CoG)',
            "ERC-AdG": r'ERC.{0,5}(Advanced|AdG)',
            "ERC-PoC": r'ERC.{0,5}(Proof|PoC)',
            "MSCA-DN": r'MSCA.{0,5}(Doctoral|DN)',
            "MSCA-PF": r'MSCA.{0,5}(Postdoctoral|PF)',
            "EIC-Pathfinder": r'EIC.{0,5}Pathfinder',
            "EIC-Accelerator": r'EIC.{0,5}Accelerator',
        }
        for at_name, pat in at_patterns.items():
            if re.search(pat, full_text, re.IGNORECASE):
                action_types.append(at_name)
        if not action_types:
            action_types = ["RIA"]

        # Kategori/destination bul
        dest = ""
        dest_el = item.select_one(
            ".category, .programme, .cluster, "
            "[class*='category'], [class*='programme']"
        )
        if dest_el:
            dest = clean_html(dest_el.get_text(strip=True))

        # Açıklama
        desc_el = item.select_one(
            ".description, .summary, .teaser, .body, "
            "p, [class*='desc'], [class*='summary']"
        )
        desc = ""
        if desc_el:
            desc = clean_html(desc_el.get_text(strip=True))

        # Call ID çıkar
        call_id = ""
        id_pattern = re.compile(
            r'(HORIZON-[A-Z0-9-]+(?:-\d{4})?|'
            r'ERC-\d{4}-[A-Za-z]+|'
            r'EIC-\d{4}-[A-Za-z]+|'
            r'MSCA-\d{4}-[A-Za-z]+)',
        )
        id_match = id_pattern.search(title + " " + full_text)
        if id_match:
            call_id = id_match.group(1)
        else:
            call_id = f"EUR-{hashlib.md5(title.encode()).hexdigest()[:8]}"

        return {
            "call_id": call_id,
            "title": title,
            "status": status,
            "deadline": deadline,
            "start_date": "",
            "budget_total": budget,
            "budget_per_project": budget,
            "action_types": action_types,
            "description": desc[:500],
            "keywords": [],
            "destination": dest,
            "scope": desc[:1000],
            "expected_outcomes": "",
            "link": link or EURESEARCH_URL,
            "source": "Euresearch",
            "topics": [],
        }

    except Exception:
        return None


def _euresearch_fallback_parse(soup) -> list:
    """Yapısal seçici bulunamazsa link bazlı parse."""
    items = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if len(text) < 15:
            continue
        # Horizon/ERC/EIC/MSCA ile ilgili linkleri bul
        combined = (text + " " + href).lower()
        if any(kw in combined for kw in [
            "horizon", "erc", "eic", "msca", "call", "topic",
            "cluster", "pillar", "pathfinder", "accelerator",
        ]):
            if text not in seen:
                seen.add(text)
                # Wrapper div oluştur
                wrapper = a.parent if a.parent else a
                items.append(wrapper)
    return items


def _euresearch_heading_parse(soup, max_results: int) -> List[Dict]:
    """h3/h4 etiketlerinden çağrı bilgisi çıkar."""
    calls = []
    for heading in soup.find_all(["h2", "h3", "h4"])[:max_results * 2]:
        title = clean_html(heading.get_text(strip=True))
        if len(title) < 10:
            continue

        # İlgili mi kontrol et
        combined = title.lower()
        if not any(kw in combined for kw in [
            "horizon", "erc", "eic", "msca", "call", "grant",
            "pathfinder", "accelerator", "doctoral", "consolidator",
            "starting", "advanced", "cluster", "pillar",
        ]):
            continue

        link = ""
        a = heading.find("a")
        if a:
            link = a.get("href", "")
            if link and not link.startswith("http"):
                link = f"https://www.euresearch.ch{link}"

        # Heading sonrasındaki paragrafı al
        desc = ""
        next_el = heading.find_next_sibling()
        if next_el:
            desc = clean_html(next_el.get_text(strip=True))

        call_id = f"EUR-{hashlib.md5(title.encode()).hexdigest()[:8]}"

        calls.append({
            "call_id": call_id,
            "title": title,
            "status": "Open",
            "deadline": "N/A",
            "start_date": "",
            "budget_total": "",
            "budget_per_project": "",
            "action_types": ["RIA"],
            "description": desc[:500],
            "keywords": [],
            "destination": "",
            "scope": desc[:1000],
            "expected_outcomes": "",
            "link": link or EURESEARCH_URL,
            "source": "Euresearch",
            "topics": [],
        })

    return calls[:max_results]


# ═══════════════════════════════════════════════════════════
# UFUK AVRUPA SCRAPER — YENİ
# ═══════════════════════════════════════════════════════════
UFUKAVRUPA_URL = "https://ufukavrupa.org.tr/tr"
UFUKAVRUPA_NEWS_URL = "https://ufukavrupa.org.tr/tr/haberler"
UFUKAVRUPA_CALLS_URL = "https://ufukavrupa.org.tr/tr/cagrilar"


def fetch_ufukavrupa_calls(max_results: int = 30) -> List[Dict]:
    """ufukavrupa.org.tr'den çağrı bilgisi çek."""
    if not HAS_BS4:
        return []

    calls = []
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        # Çağrılar sayfası
        for url in [UFUKAVRUPA_CALLS_URL, UFUKAVRUPA_URL]:
            try:
                resp = requests.get(url, headers=headers, timeout=20)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                # Çeşitli container seçiciler
                containers = (
                    soup.select(".view-content .views-row")
                    or soup.select("article")
                    or soup.select(".node")
                    or soup.select(".card")
                    or soup.select("table tbody tr")
                    or soup.select(".item-list li")
                )

                for item in containers[:max_results]:
                    call = _parse_ufukavrupa_item(item)
                    if call and call.get("title") and len(call["title"]) > 10:
                        calls.append(call)

                # Heading bazlı fallback
                if not calls:
                    for heading in soup.find_all(["h2", "h3", "h4"])[:max_results]:
                        title = clean_html(heading.get_text(strip=True))
                        if len(title) < 15:
                            continue
                        lower = title.lower()
                        if any(kw in lower for kw in [
                            "çağrı", "horizon", "erc", "eic", "msca",
                            "hibe", "başvuru", "program",
                        ]):
                            link = ""
                            a = heading.find("a")
                            if a:
                                link = a.get("href", "")
                                if link and not link.startswith("http"):
                                    link = f"https://ufukavrupa.org.tr{link}"

                            calls.append({
                                "call_id": f"UA-{hashlib.md5(title.encode()).hexdigest()[:8]}",
                                "title": title,
                                "status": "Open",
                                "deadline": "N/A",
                                "start_date": "",
                                "budget_total": "",
                                "budget_per_project": "",
                                "action_types": ["RIA"],
                                "description": "",
                                "keywords": [],
                                "destination": "",
                                "scope": "",
                                "expected_outcomes": "",
                                "link": link or UFUKAVRUPA_CALLS_URL,
                                "source": "UfukAvrupa",
                                "topics": [],
                            })

                if calls:
                    break

            except Exception:
                continue

    except Exception as e:
        calls.append({
            "call_id": "UA_ERROR",
            "title": f"UfukAvrupa Hatası: {str(e)[:100]}",
            "status": "Error",
            "deadline": "N/A",
            "action_types": ["N/A"],
            "source": "UfukAvrupa",
            "link": UFUKAVRUPA_URL,
            "keywords": [],
            "destination": "",
            "scope": "",
            "expected_outcomes": "",
            "topics": [],
            "budget_total": "",
            "budget_per_project": "",
            "description": str(e),
            "start_date": "",
        })

    return calls


def _parse_ufukavrupa_item(item) -> Optional[Dict]:
    """UfukAvrupa çağrı öğesini parse et."""
    try:
        title_el = (
            item.select_one("h2 a, h3 a, h4 a, .title a, a")
            or item.select_one("h2, h3, h4, .title")
        )
        if not title_el:
            return None

        title = clean_html(title_el.get_text(strip=True))
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
            link = f"https://ufukavrupa.org.tr{link}"

        # Tarih
        deadline = "N/A"
        text = item.get_text(separator=" ", strip=True)
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
        if date_match:
            deadline = date_match.group(1)
        else:
            date_match2 = re.search(
                r'(\d{1,2})[./](\d{1,2})[./](\d{4})', text
            )
            if date_match2:
                try:
                    d, m, y = date_match2.groups()
                    deadline = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
                except Exception:
                    pass

        desc_el = item.select_one("p, .body, .summary, .description")
        desc = clean_html(desc_el.get_text(strip=True)) if desc_el else ""

        call_id = f"UA-{hashlib.md5(title.encode()).hexdigest()[:8]}"

        return {
            "call_id": call_id,
            "title": title,
            "status": "Open",
            "deadline": deadline,
            "start_date": "",
            "budget_total": "",
            "budget_per_project": "",
            "action_types": ["RIA"],
            "description": desc[:500],
            "keywords": [],
            "destination": "",
            "scope": desc[:1000],
            "expected_outcomes": "",
            "link": link or UFUKAVRUPA_CALLS_URL,
            "source": "UfukAvrupa",
            "topics": [],
        }
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# DETECT ACTION TYPE
# ═══════════════════════════════════════════════════════════
def detect_action_type_from_call(call_data: dict) -> str:
    types = call_data.get("action_types", [])
    title = call_data.get("title", "").lower()
    call_id = call_data.get("call_id", "").lower()
    combined = " ".join(types).lower() + " " + title + " " + call_id

    mapping = [
        (["eic-pathfinder", "eic pathfinder", "pathfinder open"], "EIC-Pathfinder-Open"),
        (["eic-accelerator", "eic accelerator"], "EIC-Accelerator"),
        (["erc-stg", "erc starting", "starting grant"], "ERC-StG"),
        (["erc-cog", "erc consolidator", "consolidator grant"], "ERC-CoG"),
        (["erc-adg", "erc advanced", "advanced grant"], "ERC-AdG"),
        (["msca-dn", "msca doctoral", "doctoral network"], "MSCA-DN"),
        (["msca-pf", "msca postdoctoral", "postdoctoral"], "MSCA-PF"),
        (["csa", "coordination and support"], "CSA"),
        (["ia", "innovation action"], "IA"),
        (["ria", "research and innovation"], "RIA"),
    ]

    for keywords, action_type in mapping:
        if any(kw in combined for kw in keywords):
            return action_type

    if types:
        return types[0]
    return "RIA"


def build_call_specific_criteria(call_data: dict, topic_details: dict = None) -> dict:
    at = detect_action_type_from_call(call_data)
    ctx_parts = [
        f"Call: {call_data.get('call_id', 'N/A')}",
        f"Title: {call_data.get('title', 'N/A')}",
        f"Action Type: {at}",
        f"Deadline: {call_data.get('deadline', 'N/A')}",
    ]
    if call_data.get("scope"):
        ctx_parts.append(f"Scope: {call_data['scope'][:800]}")
    if call_data.get("expected_outcomes"):
        ctx_parts.append(f"Expected Outcomes: {call_data['expected_outcomes'][:500]}")
    if topic_details and topic_details.get("description"):
        ctx_parts.append(f"Topic Description: {topic_details['description'][:1000]}")

    return {
        "action_type": at,
        "evaluation_context": "\n".join(ctx_parts),
        "call_data": call_data,
        "topic_details": topic_details,
    }


# ═══════════════════════════════════════════════════════════
# FETCH ALL — BİRLEŞTİRİLMİŞ
# ═══════════════════════════════════════════════════════════
def fetch_all_calls(
    search_text: str = "",
    status_filter: str = "",
    use_ec_api: bool = True,
    use_euresearch: bool = True,
    use_ufukavrupa: bool = True,
    max_api_results: int = 100,
) -> Tuple[List[Dict], Dict]:
    """Tüm kaynaklardan çağrı çek ve birleştir."""
    all_calls = []
    src_stats = {"ec_api": 0, "euresearch": 0, "ufukavrupa": 0, "local_db": 0, "total": 0}

    # 1. EC API
    if use_ec_api:
        try:
            ec_calls = fetch_horizon_calls(search_text, status_filter, max_api_results)
            ec_calls = [c for c in ec_calls if c.get("status") != "Error"]
            src_stats["ec_api"] = len(ec_calls)
            all_calls.extend(ec_calls)
        except Exception:
            pass

    # 2. Euresearch
    if use_euresearch:
        try:
            eur_calls = fetch_euresearch_calls(50)
            eur_calls = [c for c in eur_calls if c.get("status") != "Error"]
            src_stats["euresearch"] = len(eur_calls)
            all_calls.extend(eur_calls)
        except Exception:
            pass

    # 3. UfukAvrupa
    if use_ufukavrupa:
        try:
            ua_calls = fetch_ufukavrupa_calls(30)
            ua_calls = [c for c in ua_calls if c.get("status") != "Error"]
            src_stats["ufukavrupa"] = len(ua_calls)
            all_calls.extend(ua_calls)
        except Exception:
            pass

    # 4. Yerel DB (call_db'den)
    try:
        from call_db import HORIZON_CALLS_DB
        src_stats["local_db"] = len(HORIZON_CALLS_DB)
        # Duplicate kontrolü
        existing_ids = set(c.get("call_id", "") for c in all_calls)
        for db_call in HORIZON_CALLS_DB:
            if db_call.get("call_id") not in existing_ids:
                db_call_copy = dict(db_call)
                db_call_copy["source"] = db_call_copy.get("source", "Local DB")
                all_calls.append(db_call_copy)
    except Exception:
        pass

    # Deduplicate
    seen = set()
    unique = []
    for c in all_calls:
        key = c.get("call_id", "")
        if not key or key in ("N/A", ""):
            key = c.get("title", "")[:60]
        if key and key not in seen:
            seen.add(key)
            unique.append(c)

    src_stats["total"] = len(unique)
    return unique, src_stats


# ═══════════════════════════════════════════════════════════
# EXCEL EXPORT
# ═══════════════════════════════════════════════════════════
def calls_to_excel_bytes(calls: List[Dict]) -> bytes:
    """Çağrıları Excel dosyasına dönüştür."""
    if not HAS_OPENPYXL:
        # CSV fallback
        import csv
        from io import StringIO
        output = StringIO()
        writer = csv.writer(output)
        headers = [
            "Call ID", "Title", "Status", "Deadline",
            "Action Types", "Budget", "Source", "Link",
        ]
        writer.writerow(headers)
        for c in calls:
            writer.writerow([
                c.get("call_id", ""),
                clean_html(c.get("title", "")),
                c.get("status", ""),
                c.get("deadline", ""),
                ", ".join(c.get("action_types", [])),
                c.get("budget_per_project", c.get("budget_total", "")),
                c.get("source", ""),
                c.get("link", ""),
            ])
        return output.getvalue().encode("utf-8-sig")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Horizon Calls"

    headers = [
        "Call ID", "Title", "Status", "Deadline", "Action Types",
        "Budget", "Destination", "Source", "Link", "Description",
    ]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = openpyxl.styles.Font(bold=True)

    for row, c in enumerate(calls, 2):
        ws.cell(row=row, column=1, value=c.get("call_id", ""))
        ws.cell(row=row, column=2, value=clean_html(c.get("title", ""))[:200])
        ws.cell(row=row, column=3, value=c.get("status", ""))
        ws.cell(row=row, column=4, value=c.get("deadline", ""))
        ws.cell(row=row, column=5, value=", ".join(c.get("action_types", [])))
        ws.cell(
            row=row, column=6,
            value=c.get("budget_per_project", c.get("budget_total", "")),
        )
        ws.cell(row=row, column=7, value=clean_html(c.get("destination", ""))[:100])
        ws.cell(row=row, column=8, value=c.get("source", ""))
        ws.cell(row=row, column=9, value=c.get("link", ""))
        ws.cell(
            row=row, column=10,
            value=clean_html(c.get("description", ""))[:300],
        )

    # Sütun genişlikleri
    widths = [25, 60, 12, 12, 20, 15, 30, 15, 50, 50]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
