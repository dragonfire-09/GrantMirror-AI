"""
call_fetcher.py — Horizon Europe Çağrı Çekici
EC Funding & Tenders API + Euresearch + UfukAvrupa + Yerel DB
"""
import requests
import time
import re
import hashlib
import json
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
def clean_html(text) -> str:
    """HTML etiketlerini ve entity'leri temizle."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
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
    text = re.sub(r'&#39;', "'", text)
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'&\w+;', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ═══════════════════════════════════════════════════════════
# EC FUNDING & TENDERS API — DÜZELTİLMİŞ
# ═══════════════════════════════════════════════════════════
EC_SEARCH_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"


def _safe_str(val) -> str:
    """Herhangi bir değeri güvenli string'e çevir."""
    if val is None:
        return ""
    if isinstance(val, list):
        parts = []
        for v in val:
            if isinstance(v, dict):
                parts.append(str(v.get("value", v.get("code", ""))))
            else:
                parts.append(str(v))
        return ", ".join(parts)
    if isinstance(val, dict):
        return str(val.get("value", val.get("code", "")))
    return str(val)


def _extract_ec_field(metadata: dict, *field_names) -> str:
    """EC API metadata'dan alan çıkar — birden fazla olası isim dener."""
    for target in field_names:
        target_lower = target.lower()
        for key, values in metadata.items():
            if target_lower in key.lower():
                return clean_html(_safe_str(values))
    return ""


def _extract_ec_list(metadata: dict, *field_names) -> List[str]:
    """EC API metadata'dan liste çıkar."""
    for target in field_names:
        target_lower = target.lower()
        for key, values in metadata.items():
            if target_lower in key.lower():
                if isinstance(values, list):
                    return [clean_html(_safe_str(v)) for v in values if v]
                return [clean_html(_safe_str(values))]
    return []


def fetch_horizon_calls(
    search_text: str = "",
    status: str = "",
    max_results: int = 100,
) -> Tuple[List[Dict], dict]:
    """
    EC Funding & Tenders API'den Horizon Europe çağrılarını çek.
    Birden fazla sorgu stratejisi dener.
    """
    calls = []
    debug_info = {"attempts": [], "success": False, "total_api": 0}

    # Strateji 1: Yeni API formatı
    strategies = [
        {
            "name": "strategy_1_framework",
            "params": {
                "apiKey": "SEDIA",
                "text": search_text if search_text else "horizon europe",
                "pageSize": str(min(max_results, 100)),
                "pageNumber": "1",
                "type": "1",
                "sortBy": "sortStatus:asc,deadlineDate:desc",
            },
        },
        {
            "name": "strategy_2_query",
            "params": {
                "apiKey": "SEDIA",
                "text": search_text if search_text else "*",
                "pageSize": str(min(max_results, 100)),
                "pageNumber": "1",
                "sortBy": "deadlineDate:desc",
                "query": (
                    "frameworkProgramme/code='43108390'"
                ),
            },
        },
        {
            "name": "strategy_3_programme_period",
            "params": {
                "apiKey": "SEDIA",
                "text": search_text if search_text else "*",
                "pageSize": str(min(max_results, 100)),
                "pageNumber": "1",
                "sortBy": "deadlineDate:desc",
                "query": (
                    "programmePeriod/code='2021-2027' AND "
                    "frameworkProgramme/code='43108390'"
                ),
            },
        },
        {
            "name": "strategy_4_simple",
            "params": {
                "apiKey": "SEDIA",
                "text": "HORIZON" if not search_text else f"HORIZON {search_text}",
                "pageSize": str(min(max_results, 100)),
                "pageNumber": "1",
                "sortBy": "deadlineDate:desc",
            },
        },
    ]

    for strategy in strategies:
        try:
            params = strategy["params"].copy()

            # Status filtresi
            if status:
                status_map = {
                    "open": "31094501",
                    "forthcoming": "31094502",
                    "closed": "31094503",
                }
                sc = status_map.get(status.lower(), "")
                if sc:
                    q = params.get("query", "")
                    status_q = f"status/code='{sc}'"
                    params["query"] = f"{q} AND {status_q}" if q else status_q

            resp = requests.get(EC_SEARCH_URL, params=params, timeout=25)
            debug_info["attempts"].append({
                "strategy": strategy["name"],
                "status_code": resp.status_code,
                "url": resp.url[:200],
            })

            if resp.status_code != 200:
                continue

            data = resp.json()
            results = data.get("results", [])
            total_results = data.get("totalResults", 0)

            debug_info["attempts"][-1]["total_results"] = total_results
            debug_info["attempts"][-1]["returned"] = len(results)

            if not results:
                continue

            # Sonuçları parse et
            for r in results:
                meta = r.get("metadata", {})
                call = _parse_ec_result(meta)
                if call:
                    calls.append(call)

            # Sayfalama — daha fazla sonuç varsa
            if total_results > len(results) and len(calls) < max_results:
                pages_needed = min(
                    (max_results - len(calls) + 99) // 100,
                    (total_results + 99) // 100,
                    5,  # Maks 5 sayfa
                )
                for page in range(2, pages_needed + 1):
                    try:
                        params["pageNumber"] = str(page)
                        resp2 = requests.get(
                            EC_SEARCH_URL, params=params, timeout=25,
                        )
                        if resp2.status_code == 200:
                            data2 = resp2.json()
                            for r2 in data2.get("results", []):
                                call2 = _parse_ec_result(r2.get("metadata", {}))
                                if call2:
                                    calls.append(call2)
                        if len(calls) >= max_results:
                            break
                    except Exception:
                        break

            if calls:
                debug_info["success"] = True
                debug_info["total_api"] = len(calls)
                break  # İlk başarılı strateji yeterli

        except Exception as e:
            debug_info["attempts"][-1]["error"] = str(e)[:200]
            continue

    # Hiçbir strateji çalışmadıysa
    if not calls:
        debug_info["fallback"] = "no_results"

    return calls[:max_results], debug_info


def _parse_ec_result(meta: dict) -> Optional[Dict]:
    """Tek bir EC API sonucunu parse et."""
    try:
        call_id = _extract_ec_field(meta, "identifier", "callIdentifier", "topicIdentifier")
        title = _extract_ec_field(meta, "title")

        if not call_id and not title:
            return None

        status_raw = _extract_ec_field(meta, "status")
        deadline = _extract_ec_field(meta, "deadlineDate", "deadlineDates")
        start_date = _extract_ec_field(meta, "startDate", "openingDate")
        budget = _extract_ec_field(meta, "budget", "budgetOverviewReference")
        desc = _extract_ec_field(meta, "description", "smedescription")
        programme = _extract_ec_field(meta, "programmeDivision", "destination")
        types_list = _extract_ec_list(meta, "typesOfAction", "typeOfAction")
        keywords_list = _extract_ec_list(meta, "keywords", "tags")

        # Status normalleştir
        status_display = _normalize_status(status_raw)

        # Deadline normalleştir (sadece ilk tarih)
        if deadline:
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', deadline)
            if date_match:
                deadline = date_match.group(1)
            else:
                # Diğer formatlar
                date_match2 = re.search(r'(\d{2})/(\d{2})/(\d{4})', deadline)
                if date_match2:
                    m, d, y = date_match2.groups()
                    deadline = f"{y}-{m}-{d}"
                else:
                    deadline = deadline[:10] if len(deadline) >= 10 else "N/A"

        # Action types
        if not types_list:
            types_list = _detect_action_types_from_text(call_id, title)

        # Link
        link = ""
        if call_id:
            # Temiz call_id (virgül varsa ilkini al)
            clean_id = call_id.split(",")[0].strip()
            link = (
                f"https://ec.europa.eu/info/funding-tenders/"
                f"opportunities/portal/screen/opportunities/"
                f"topic-details/{clean_id}"
            )

        return {
            "call_id": call_id or "N/A",
            "title": title or call_id or "N/A",
            "status": status_display,
            "deadline": deadline if deadline else "N/A",
            "start_date": start_date[:10] if start_date else "",
            "budget_total": budget,
            "budget_per_project": "",
            "action_types": types_list if types_list else ["RIA"],
            "description": desc[:500] if desc else "",
            "keywords": keywords_list,
            "destination": programme,
            "scope": desc[:1000] if desc else "",
            "expected_outcomes": "",
            "link": link,
            "source": "EC API",
            "topics": [{"topic_id": call_id.split(",")[0].strip()}] if call_id else [],
        }
    except Exception:
        return None


def _normalize_status(raw: str) -> str:
    """Status string'i normalleştir."""
    if not raw:
        return "Open"
    low = raw.lower()
    if any(x in low for x in ["open", "31094501", "açık"]):
        return "Open"
    if any(x in low for x in ["forthcoming", "31094502", "upcoming", "yaklaşan"]):
        return "Forthcoming"
    if any(x in low for x in ["closed", "31094503", "kapan"]):
        return "Closed"
    return raw


def _detect_action_types_from_text(call_id: str, title: str) -> List[str]:
    """Call ID ve başlıktan aksiyon türü tespit et."""
    combined = (call_id + " " + title).upper()
    types = []
    patterns = [
        ("ERC-StG", r'ERC.{0,10}(STG|STARTING)'),
        ("ERC-CoG", r'ERC.{0,10}(COG|CONSOLIDATOR)'),
        ("ERC-AdG", r'ERC.{0,10}(ADG|ADVANCED)'),
        ("ERC-PoC", r'ERC.{0,10}(POC|PROOF)'),
        ("MSCA-DN", r'MSCA.{0,10}(DN|DOCTORAL)'),
        ("MSCA-PF", r'MSCA.{0,10}(PF|POSTDOC)'),
        ("EIC-Pathfinder", r'EIC.{0,10}PATHFINDER'),
        ("EIC-Accelerator", r'EIC.{0,10}ACCELERATOR'),
        ("CSA", r'\bCSA\b'),
        ("IA", r'\bIA\b'),
        ("RIA", r'\bRIA\b'),
    ]
    for name, pattern in patterns:
        if re.search(pattern, combined):
            types.append(name)
    return types if types else ["RIA"]


def fetch_topic_details(topic_id: str) -> Optional[Dict]:
    """Tek bir topic'in detaylarını çek."""
    if not topic_id or topic_id == "N/A":
        return None
    try:
        # Strateji 1: identifier ile
        params = {
            "apiKey": "SEDIA",
            "text": f'"{topic_id}"',
            "pageSize": "5",
            "pageNumber": "1",
        }
        resp = requests.get(EC_SEARCH_URL, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            for r in results:
                meta = r.get("metadata", {})
                found_id = _extract_ec_field(meta, "identifier")
                if topic_id.lower() in found_id.lower():
                    return {
                        "topic_id": topic_id,
                        "title": _extract_ec_field(meta, "title"),
                        "description": _extract_ec_field(meta, "description"),
                        "budget": _extract_ec_field(meta, "budget"),
                        "deadline": _extract_ec_field(meta, "deadlineDate"),
                        "conditions": _extract_ec_field(meta, "conditions"),
                    }
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════
# EURESEARCH SCRAPER
# ═══════════════════════════════════════════════════════════
EURESEARCH_URL = "https://www.euresearch.ch/en/our-services/inform/open-calls-137.html"


def fetch_euresearch_calls(max_results: int = 50) -> List[Dict]:
    """Euresearch.ch'den açık çağrıları scrape et."""
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
            "Accept-Language": "en-US,en;q=0.5",
        }
        resp = requests.get(EURESEARCH_URL, headers=headers, timeout=20)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # Tüm div'leri tara — Euresearch yapısı
        # Her çağrı kartı genellikle bir div container içinde
        all_text_blocks = soup.find_all(
            ["div", "article", "li", "tr"],
            recursive=True,
        )

        seen_titles = set()
        for block in all_text_blocks:
            text = block.get_text(separator=" ", strip=True)
            if len(text) < 30:
                continue

            # HORIZON, ERC, EIC, MSCA pattern var mı?
            if not re.search(
                r'(HORIZON|ERC|EIC|MSCA|Pathfinder|Accelerator|'
                r'Starting|Consolidator|Advanced|Doctoral|'
                r'Postdoctoral|Twinning|Teaming|Cluster)',
                text,
                re.IGNORECASE,
            ):
                continue

            # Başlık çıkar — ilk anlamlı h element veya kalın metin
            title = ""
            for h in block.find_all(["h2", "h3", "h4", "strong", "b"]):
                t = clean_html(h.get_text(strip=True))
                if len(t) >= 10:
                    title = t
                    break

            if not title:
                # İlk satırı başlık olarak al
                lines = [
                    l.strip() for l in text.split("\n")
                    if len(l.strip()) >= 10
                ]
                if lines:
                    title = clean_html(lines[0])[:200]

            if not title or len(title) < 10:
                continue

            # Duplicate kontrolü
            title_key = title.lower()[:50]
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

            # Link bul
            link = ""
            for a in block.find_all("a", href=True):
                href = a.get("href", "")
                if any(x in href.lower() for x in [
                    "topic", "call", "horizon", "erc", "eic", "msca",
                    "ec.europa.eu",
                ]):
                    link = href
                    break
            if not link:
                first_a = block.find("a", href=True)
                if first_a:
                    link = first_a.get("href", "")
            if link and not link.startswith("http"):
                link = f"https://www.euresearch.ch{link}"

            # Status
            status = "Open"
            text_lower = text.lower()
            if "forthcoming" in text_lower or "upcoming" in text_lower:
                status = "Forthcoming"
            elif "closed" in text_lower:
                status = "Closed"

            # Tarih bul
            deadline = "N/A"
            date_patterns = [
                (r'(\d{4}-\d{2}-\d{2})', None),
                (
                    r'(\d{1,2})\s+(January|February|March|April|May|June|'
                    r'July|August|September|October|November|December)\s+(\d{4})',
                    "%d %B %Y",
                ),
                (r'(\d{2})\.(\d{2})\.(\d{4})', "dmy_dot"),
            ]
            for pat, fmt in date_patterns:
                dm = re.search(pat, text, re.IGNORECASE)
                if dm:
                    if fmt is None:
                        deadline = dm.group(1)
                    elif fmt == "dmy_dot":
                        d, m, y = dm.groups()
                        deadline = f"{y}-{m}-{d}"
                    else:
                        try:
                            deadline = datetime.strptime(
                                dm.group(0), fmt,
                            ).strftime("%Y-%m-%d")
                        except Exception:
                            pass
                    break

            # Bütçe bul
            budget = ""
            budget_match = re.search(r'€\s*[\d.,]+\s*[MmKkBb]?', text)
            if budget_match:
                budget = budget_match.group(0).strip()

            # Action type tespit
            action_types = _detect_action_types_from_text(title, text)

            # Call ID
            call_id = ""
            id_match = re.search(
                r'(HORIZON-[A-Z0-9]+-\d{4}-[A-Z0-9-]+|'
                r'ERC-\d{4}-[A-Za-z]+|'
                r'EIC-\d{4}-[A-Za-z]+|'
                r'MSCA-\d{4}-[A-Za-z-]+)',
                text,
            )
            if id_match:
                call_id = id_match.group(1)
            else:
                call_id = f"EUR-{hashlib.md5(title.encode()).hexdigest()[:8]}"

            # Açıklama — title dışındaki metin
            desc = clean_html(text)
            if desc.startswith(title):
                desc = desc[len(title):].strip()
            desc = desc[:500]

            # Destination
            dest = ""
            dest_patterns = [
                r'(European Research Council)',
                r'(EIC\s+\w+)',
                r'(MSCA\s+\w+)',
                r'(Cluster\s+\d)',
                r'(Pillar\s+\w+)',
                r'(Widening)',
            ]
            for dp in dest_patterns:
                dm = re.search(dp, text, re.IGNORECASE)
                if dm:
                    dest = dm.group(1)
                    break

            calls.append({
                "call_id": call_id,
                "title": title,
                "status": status,
                "deadline": deadline,
                "start_date": "",
                "budget_total": budget,
                "budget_per_project": budget,
                "action_types": action_types,
                "description": desc,
                "keywords": [],
                "destination": dest,
                "scope": desc,
                "expected_outcomes": "",
                "link": link or EURESEARCH_URL,
                "source": "Euresearch",
                "topics": [],
            })

            if len(calls) >= max_results:
                break

    except Exception:
        pass

    return calls


# ═══════════════════════════════════════════════════════════
# UFUK AVRUPA SCRAPER
# ═══════════════════════════════════════════════════════════
UFUKAVRUPA_BASE = "https://ufukavrupa.org.tr"


def fetch_ufukavrupa_calls(max_results: int = 30) -> List[Dict]:
    """ufukavrupa.org.tr'den çağrı bilgisi çek."""
    if not HAS_BS4:
        return []

    calls = []
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "tr-TR,tr;q=0.9",
        }

        urls = [
            f"{UFUKAVRUPA_BASE}/tr/cagrilar",
            f"{UFUKAVRUPA_BASE}/tr",
            f"{UFUKAVRUPA_BASE}/tr/haberler",
        ]

        for url in urls:
            try:
                resp = requests.get(url, headers=headers, timeout=20)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                seen = set()

                # Tüm anlamlı blokları tara
                for el in soup.find_all(["article", "div", "li"]):
                    text = el.get_text(separator=" ", strip=True)
                    if len(text) < 30:
                        continue

                    # Horizon/çağrı ile ilgili mi?
                    if not any(
                        kw in text.lower()
                        for kw in [
                            "çağrı", "horizon", "erc", "eic", "msca",
                            "hibe", "başvuru", "program", "proje",
                            "cluster", "call",
                        ]
                    ):
                        continue

                    title_el = el.find(["h2", "h3", "h4", "a"])
                    if not title_el:
                        continue

                    title = clean_html(title_el.get_text(strip=True))
                    if not title or len(title) < 10:
                        continue

                    tk = title.lower()[:50]
                    if tk in seen:
                        continue
                    seen.add(tk)

                    link = ""
                    a = title_el if title_el.name == "a" else title_el.find("a")
                    if a:
                        link = a.get("href", "")
                    if link and not link.startswith("http"):
                        link = f"{UFUKAVRUPA_BASE}{link}"

                    # Tarih
                    deadline = "N/A"
                    dm = re.search(r'(\d{4}-\d{2}-\d{2})', text)
                    if dm:
                        deadline = dm.group(1)
                    else:
                        dm2 = re.search(r'(\d{1,2})[./](\d{1,2})[./](\d{4})', text)
                        if dm2:
                            d, m, y = dm2.groups()
                            deadline = f"{y}-{m.zfill(2)}-{d.zfill(2)}"

                    calls.append({
                        "call_id": f"UA-{hashlib.md5(title.encode()).hexdigest()[:8]}",
                        "title": title,
                        "status": "Open",
                        "deadline": deadline,
                        "start_date": "",
                        "budget_total": "",
                        "budget_per_project": "",
                        "action_types": _detect_action_types_from_text("", title),
                        "description": clean_html(text)[:500],
                        "keywords": [],
                        "destination": "",
                        "scope": clean_html(text)[:1000],
                        "expected_outcomes": "",
                        "link": link or url,
                        "source": "UfukAvrupa",
                        "topics": [],
                    })

                    if len(calls) >= max_results:
                        break

                if calls:
                    break

            except Exception:
                continue

    except Exception:
        pass

    return calls


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

    if types and types[0] != "RIA":
        return types[0]
    return "RIA"


def build_call_specific_criteria(call_data: dict, topic_details: dict = None) -> dict:
    at = detect_action_type_from_call(call_data)
    ctx_parts = [
        f"Call: {clean_html(call_data.get('call_id', 'N/A'))}",
        f"Title: {clean_html(call_data.get('title', 'N/A'))}",
        f"Action Type: {at}",
        f"Deadline: {call_data.get('deadline', 'N/A')}",
    ]
    scope = clean_html(call_data.get("scope", ""))
    if scope:
        ctx_parts.append(f"Scope: {scope[:800]}")
    outcomes = clean_html(call_data.get("expected_outcomes", ""))
    if outcomes:
        ctx_parts.append(f"Expected Outcomes: {outcomes[:500]}")
    if topic_details and topic_details.get("description"):
        ctx_parts.append(
            f"Topic Description: {clean_html(topic_details['description'][:1000])}"
        )

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
    src_stats = {
        "ec_api": 0, "euresearch": 0, "ufukavrupa": 0,
        "local_db": 0, "total": 0, "ec_debug": {},
    }

    # 1. EC API
    if use_ec_api:
        try:
            ec_calls, ec_debug = fetch_horizon_calls(
                search_text, status_filter, max_api_results,
            )
            src_stats["ec_api"] = len(ec_calls)
            src_stats["ec_debug"] = ec_debug
            all_calls.extend(ec_calls)
        except Exception as e:
            src_stats["ec_debug"] = {"error": str(e)[:200]}

    # 2. Euresearch
    if use_euresearch:
        try:
            eur_calls = fetch_euresearch_calls(50)
            src_stats["euresearch"] = len(eur_calls)
            all_calls.extend(eur_calls)
        except Exception:
            pass

    # 3. UfukAvrupa
    if use_ufukavrupa:
        try:
            ua_calls = fetch_ufukavrupa_calls(30)
            src_stats["ufukavrupa"] = len(ua_calls)
            all_calls.extend(ua_calls)
        except Exception:
            pass

    # 4. Yerel DB
    try:
        from call_db import HORIZON_CALLS_DB
        existing_ids = set(c.get("call_id", "") for c in all_calls)
        db_added = 0
        for db_call in HORIZON_CALLS_DB:
            if db_call.get("call_id") not in existing_ids:
                db_call_copy = dict(db_call)
                db_call_copy["source"] = db_call_copy.get("source", "Local DB")
                all_calls.append(db_call_copy)
                db_added += 1
        src_stats["local_db"] = db_added
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
            # Tüm string alanları temizle
            c["title"] = clean_html(c.get("title", ""))
            c["description"] = clean_html(c.get("description", ""))
            c["destination"] = clean_html(c.get("destination", ""))
            unique.append(c)

    src_stats["total"] = len(unique)
    return unique, src_stats


# ═══════════════════════════════════════════════════════════
# EXCEL EXPORT
# ═══════════════════════════════════════════════════════════
def calls_to_excel_bytes(calls: List[Dict]) -> bytes:
    """Çağrıları Excel dosyasına dönüştür."""
    if not HAS_OPENPYXL:
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
        ws.cell(row=row, column=10, value=clean_html(c.get("description", ""))[:300])

    widths = [25, 60, 12, 12, 20, 15, 30, 15, 50, 50]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
