"""
GrantMirror-AI: Horizon Europe Call Fetcher
Live EC Funding & Tenders API + Euresearch scraper + Excel export.
"""
import requests
import time
import re
import io
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime

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


@dataclass
class CallCache:
    """Simple in-memory cache with TTL."""
    ttl_minutes: int = 30
    _store: Dict = field(default_factory=dict)
    _timestamps: Dict = field(default_factory=dict)

    def get(self, key: str):
        if key in self._store:
            ts = self._timestamps.get(key, 0)
            if time.time() - ts < self.ttl_minutes * 60:
                return self._store[key]
            else:
                del self._store[key]
                del self._timestamps[key]
        return None

    def set(self, key: str, value):
        self._store[key] = value
        self._timestamps[key] = time.time()

    def clear(self):
        self._store.clear()
        self._timestamps.clear()


# ═══════════════════════════════════════════════════════════
# EC FUNDING & TENDERS API
# ═══════════════════════════════════════════════════════════
EC_API_BASE = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"


def fetch_horizon_calls(
    programme: str = "HORIZON",
    status: str = "",
    search_text: str = "",
    page_size: int = 100,
    page_num: int = 1,
    max_pages: int = 5,
    fetch_all: bool = True,
) -> Tuple[List[Dict], int]:
    all_calls = []
    total_count = 0

    for current_page in range(page_num, page_num + max_pages):
        params = {
            "apiKey": "SEDIA",
            "text": search_text or "*",
            "type": "1",
            "pageSize": str(min(page_size, 100)),
            "pageNumber": str(current_page),
        }
        query_parts = []
        if programme:
            query_parts.append(f'programmePeriod/abbreviation="{programme}"')
        if status:
            query_parts.append(f'status/abbreviation="{status}"')
        if query_parts:
            params["query"] = " AND ".join(query_parts)

        try:
            resp = requests.get(EC_API_BASE, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            break

        results = data.get("results", [])
        total_count = data.get("totalResults", len(results))
        if not results:
            break

        for item in results:
            meta = item.get("metadata", {})
            call_info = _parse_call_metadata(meta)
            if call_info:
                all_calls.append(call_info)

        if not fetch_all or len(all_calls) >= total_count:
            break
        time.sleep(0.3)

    seen = set()
    unique = []
    for c in all_calls:
        cid = c.get("call_id", "")
        if cid and cid not in seen:
            seen.add(cid)
            unique.append(c)
    return unique, total_count


def _parse_call_metadata(meta: Dict) -> Optional[Dict]:
    try:
        call_id = _extract_field(meta, "identifier") or _extract_field(meta, "ccm2Id")
        title = _extract_field(meta, "title")
        if not call_id and not title:
            return None

        status_raw = _extract_field(meta, "status")
        status = "Open"
        if status_raw:
            sl = status_raw.lower()
            if "closed" in sl:
                status = "Closed"
            elif "forthcoming" in sl or "upcoming" in sl:
                status = "Forthcoming"

        deadline = _extract_field(meta, "deadlineDate") or _extract_field(meta, "plannedClosingDate") or ""

        action_types = []
        at_raw = _extract_field(meta, "typesOfAction")
        if at_raw:
            action_types = [s.strip() for s in str(at_raw).split(",")] if not isinstance(at_raw, list) else at_raw
        if not action_types:
            action_types = _detect_action_types_from_text(call_id or "", title or "")

        topics = []
        topics_raw = meta.get("topics", [])
        if isinstance(topics_raw, list):
            for t in topics_raw:
                if isinstance(t, dict):
                    topics.append(t)
                elif isinstance(t, str):
                    topics.append({"topic_id": t})

        return {
            "call_id": call_id or "UNKNOWN",
            "title": title or "Untitled",
            "status": status,
            "deadline": deadline,
            "action_types": action_types if action_types else ["RIA"],
            "topics": topics,
            "budget_total": _extract_field(meta, "budget") or "",
            "description": _extract_field(meta, "description") or "",
            "source": "EC API",
        }
    except Exception:
        return None


def _extract_field(meta: Dict, key: str) -> Optional[str]:
    if key in meta:
        val = meta[key]
        if isinstance(val, list) and val:
            if isinstance(val[0], dict):
                return val[0].get("value", str(val[0]))
            return str(val[0])
        return str(val) if val else None
    return None


def _detect_action_types_from_text(call_id: str, title: str) -> List[str]:
    text = f"{call_id} {title}".upper()
    types = []
    if "MSCA" in text and "DN" in text:
        types.append("MSCA-DN")
    if "MSCA" in text and "PF" in text:
        types.append("MSCA-PF")
    if "ERC" in text:
        if "STG" in text:
            types.append("ERC-StG")
        elif "COG" in text:
            types.append("ERC-CoG")
        elif "ADG" in text:
            types.append("ERC-AdG")
        else:
            types.append("ERC")
    if "EIC" in text and "PATHFINDER" in text:
        types.append("EIC-Pathfinder")
    if "EIC" in text and "ACCELERATOR" in text:
        types.append("EIC-Accelerator")
    if "EIC" in text and "TRANSITION" in text:
        types.append("EIC-Transition")
    if "CSA" in text:
        types.append("CSA")
    if "IA" in text and "RIA" not in text:
        types.append("IA")
    if "RIA" in text:
        types.append("RIA")
    return types


# ═══════════════════════════════════════════════════════════
# EURESEARCH SCRAPER
# ═══════════════════════════════════════════════════════════
EURESEARCH_URL = "https://www.euresearch.ch/en/our-services/inform/open-calls-137.html"


def fetch_euresearch_calls(max_retries: int = 2) -> List[Dict]:
    """Scrape open calls from Euresearch website."""
    if not HAS_BS4:
        return []

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    for attempt in range(max_retries):
        try:
            resp = requests.get(EURESEARCH_URL, headers=headers, timeout=20)
            resp.raise_for_status()
            return _parse_euresearch_html(resp.text)
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(2)
    return []


def _parse_euresearch_html(html: str) -> List[Dict]:
    """Parse Euresearch HTML page for call data."""
    soup = BeautifulSoup(html, "html.parser")
    calls = []

    # Try multiple CSS selectors for robustness
    rows = (
        soup.select("table.views-table tbody tr")
        or soup.select("div.view-content div.views-row")
        or soup.select("table tbody tr")
        or soup.select("div.field-content")
    )

    if not rows:
        # Fallback: try to find any table
        tables = soup.find_all("table")
        for table in tables:
            trs = table.find_all("tr")
            for tr in trs[1:]:  # Skip header
                call = _parse_euresearch_row_from_cells(tr.find_all("td"))
                if call:
                    calls.append(call)
        if calls:
            return calls

        # Fallback 2: regex-based extraction from raw text
        return _parse_euresearch_from_text(soup.get_text())

    for row in rows:
        call = _parse_euresearch_row(row)
        if call:
            calls.append(call)

    return calls


def _parse_euresearch_row(row) -> Optional[Dict]:
    """Parse a single row/card from Euresearch."""
    cells = row.find_all("td")
    if cells:
        return _parse_euresearch_row_from_cells(cells)

    # Card-style layout
    title_el = row.find(["h3", "h4", "a", "strong"])
    title = title_el.get_text(strip=True) if title_el else ""
    if not title:
        return None

    full_text = row.get_text(" ", strip=True)

    # Extract deadline
    deadline = ""
    date_match = re.search(r'(\d{1,2}[./]\d{1,2}[./]\d{2,4})', full_text)
    if date_match:
        deadline = _normalize_date(date_match.group(1))
    else:
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', full_text)
        if date_match:
            deadline = date_match.group(1)

    # Extract call ID
    call_id = ""
    id_match = re.search(r'(HORIZON[-\w]+|ERC[-\w]+|EIC[-\w]+|MSCA[-\w]+)', full_text)
    if id_match:
        call_id = id_match.group(1)
    else:
        call_id = "EUR-" + re.sub(r'\W+', '-', title[:40]).strip('-').upper()

    # Extract link
    link = ""
    a_tag = row.find("a", href=True)
    if a_tag:
        href = a_tag["href"]
        if not href.startswith("http"):
            href = "https://www.euresearch.ch" + href
        link = href

    action_types = _detect_action_types_from_text(call_id, title)

    return {
        "call_id": call_id,
        "title": title,
        "status": "Open",
        "deadline": deadline,
        "action_types": action_types if action_types else ["RIA"],
        "topics": [],
        "budget_per_project": "",
        "description": full_text[:500],
        "source": "Euresearch",
        "link": link,
        "destination": "",
        "keywords": [],
        "expected_outcomes": "",
        "scope": "",
    }


def _parse_euresearch_row_from_cells(cells) -> Optional[Dict]:
    """Parse table cells into a call dict."""
    if len(cells) < 2:
        return None

    texts = [c.get_text(strip=True) for c in cells]
    title = texts[0] if texts else ""
    if not title or len(title) < 5:
        return None

    # Try to find deadline in cells
    deadline = ""
    call_id = ""
    for t in texts:
        date_m = re.search(r'(\d{1,2}[./]\d{1,2}[./]\d{2,4})', t)
        if date_m:
            deadline = _normalize_date(date_m.group(1))
        date_m2 = re.search(r'(\d{4}-\d{2}-\d{2})', t)
        if date_m2:
            deadline = date_m2.group(1)
        id_m = re.search(r'(HORIZON[-\w]+|ERC[-\w]+|EIC[-\w]+|MSCA[-\w]+)', t)
        if id_m:
            call_id = id_m.group(1)

    if not call_id:
        call_id = "EUR-" + re.sub(r'\W+', '-', title[:40]).strip('-').upper()

    link = ""
    for c in cells:
        a = c.find("a", href=True)
        if a:
            href = a["href"]
            if not href.startswith("http"):
                href = "https://www.euresearch.ch" + href
            link = href
            break

    action_types = _detect_action_types_from_text(call_id, title)

    return {
        "call_id": call_id,
        "title": title,
        "status": "Open",
        "deadline": deadline,
        "action_types": action_types if action_types else ["RIA"],
        "topics": [],
        "budget_per_project": texts[2] if len(texts) > 2 else "",
        "description": " | ".join(texts),
        "source": "Euresearch",
        "link": link,
        "destination": texts[1] if len(texts) > 1 else "",
        "keywords": [],
        "expected_outcomes": "",
        "scope": "",
    }


def _parse_euresearch_from_text(text: str) -> List[Dict]:
    """Fallback: extract calls from raw text using regex patterns."""
    calls = []
    lines = text.split("\n")
    current = {}

    for line in lines:
        line = line.strip()
        if not line:
            if current.get("title"):
                calls.append(current)
                current = {}
            continue

        # Look for call IDs
        id_match = re.search(r'(HORIZON[-\w]+|ERC[-\w]+|EIC[-\w]+|MSCA[-\w]+)', line)
        if id_match:
            if current.get("title"):
                calls.append(current)
            current = {
                "call_id": id_match.group(1),
                "title": line[:150],
                "status": "Open",
                "deadline": "",
                "action_types": _detect_action_types_from_text(id_match.group(1), line),
                "topics": [],
                "source": "Euresearch",
                "keywords": [],
                "expected_outcomes": "",
                "scope": "",
                "description": "",
                "budget_per_project": "",
                "link": "",
                "destination": "",
            }

        # Look for dates
        date_match = re.search(r'(\d{1,2}[./]\d{1,2}[./]\d{2,4})', line)
        if date_match and current:
            current["deadline"] = _normalize_date(date_match.group(1))
        date_match2 = re.search(r'(\d{4}-\d{2}-\d{2})', line)
        if date_match2 and current:
            current["deadline"] = date_match2.group(1)

    if current.get("title"):
        calls.append(current)

    return calls


def _normalize_date(date_str: str) -> str:
    """Normalize date string to YYYY-MM-DD."""
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d.%m.%y", "%d/%m/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str


# ═══════════════════════════════════════════════════════════
# COMBINED FETCH (EC API + Euresearch + Local DB)
# ═══════════════════════════════════════════════════════════
def fetch_all_calls(
    search_text: str = "",
    status_filter: str = "",
    use_ec_api: bool = True,
    use_euresearch: bool = True,
    max_api_results: int = 100,
) -> Tuple[List[Dict], Dict]:
    """
    Fetch calls from all sources and merge.
    Returns (calls_list, source_stats).
    """
    all_calls = []
    stats = {"ec_api": 0, "euresearch": 0, "local_db": 0, "total": 0}

    # 1. EC API
    if use_ec_api:
        try:
            api_calls, _ = fetch_horizon_calls(
                programme="HORIZON",
                status=status_filter,
                search_text=search_text,
                page_size=100,
                max_pages=max(1, max_api_results // 100),
                fetch_all=True,
            )
            all_calls.extend(api_calls)
            stats["ec_api"] = len(api_calls)
        except Exception:
            pass

    # 2. Euresearch
    if use_euresearch:
        try:
            eur_calls = fetch_euresearch_calls()
            all_calls.extend(eur_calls)
            stats["euresearch"] = len(eur_calls)
        except Exception:
            pass

    # 3. Local DB (fill gaps)
    from call_db import HORIZON_CALLS_DB
    existing_ids = set(c.get("call_id", "") for c in all_calls)
    local_added = 0
    for lc in HORIZON_CALLS_DB:
        if lc["call_id"] not in existing_ids:
            lc_copy = {**lc, "source": "Local DB"}
            all_calls.append(lc_copy)
            existing_ids.add(lc["call_id"])
            local_added += 1
    stats["local_db"] = local_added

    # Deduplicate
    seen = set()
    unique = []
    for c in all_calls:
        cid = c.get("call_id", "")
        if cid and cid not in seen:
            seen.add(cid)
            unique.append(c)

    stats["total"] = len(unique)
    return unique, stats


# ═══════════════════════════════════════════════════════════
# TOPIC DETAILS
# ═══════════════════════════════════════════════════════════
def fetch_topic_details(topic_id: str) -> Optional[Dict]:
    params = {
        "apiKey": "SEDIA",
        "text": f'"{topic_id}"',
        "type": "1",
        "pageSize": "5",
    }
    try:
        resp = requests.get(EC_API_BASE, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("results", []):
            meta = item.get("metadata", {})
            identifier = _extract_field(meta, "identifier") or ""
            if topic_id.lower() in identifier.lower():
                return {
                    "topic_id": topic_id,
                    "title": _extract_field(meta, "title") or "",
                    "description": _extract_field(meta, "description") or "",
                    "budget": _extract_field(meta, "budget") or "",
                    "conditions": _extract_field(meta, "conditions") or "",
                }
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════
def detect_action_type_from_call(call_data: Dict) -> str:
    action_types = call_data.get("action_types", [])
    if action_types:
        return action_types[0]
    text = f"{call_data.get('call_id', '')} {call_data.get('title', '')}".upper()
    if "MSCA" in text and "DN" in text:
        return "MSCA-DN"
    if "ERC" in text:
        return "ERC-StG"
    if "EIC" in text and "PATHFINDER" in text:
        return "EIC-Pathfinder"
    if "EIC" in text and "ACCELERATOR" in text:
        return "EIC-Accelerator"
    if "CSA" in text:
        return "CSA"
    if "IA" in text:
        return "IA"
    return "RIA"


def build_call_specific_criteria(call_data: Dict, topic_details: Optional[Dict] = None) -> Dict:
    parts = [
        f"Call: {call_data.get('call_id', 'N/A')}",
        f"Title: {call_data.get('title', 'N/A')}",
        f"Action Types: {', '.join(call_data.get('action_types', []))}",
        f"Deadline: {call_data.get('deadline', 'N/A')}",
        f"Source: {call_data.get('source', 'N/A')}",
    ]
    if call_data.get("description"):
        parts.append(f"\nCall Description:\n{call_data['description'][:2000]}")
    if topic_details:
        if topic_details.get("description"):
            parts.append(f"\nTopic Description:\n{topic_details['description'][:3000]}")
        if topic_details.get("conditions"):
            parts.append(f"\nConditions:\n{topic_details['conditions'][:1000]}")

    return {
        "action_type": detect_action_type_from_call(call_data),
        "evaluation_context": "\n".join(parts),
        "call_id": call_data.get("call_id", ""),
        "deadline": call_data.get("deadline", ""),
    }


def calls_to_excel_bytes(calls: List[Dict]) -> bytes:
    if HAS_OPENPYXL:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Horizon Calls"

        headers = ["Call ID", "Title", "Status", "Deadline", "Action Types",
                    "Destination", "Budget", "Source", "Link",
                    "Expected Outcomes", "Scope", "Keywords"]
        ws.append(headers)

        from openpyxl.styles import Font, PatternFill, Alignment
        hfont = Font(bold=True, color="FFFFFF", size=11)
        hfill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
        for cell in ws[1]:
            cell.font = hfont
            cell.fill = hfill
            cell.alignment = Alignment(horizontal="center")

        for call in calls:
            ws.append([
                call.get("call_id", ""),
                call.get("title", ""),
                call.get("status", ""),
                call.get("deadline", ""),
                ", ".join(call.get("action_types", [])),
                call.get("destination", ""),
                call.get("budget_per_project", call.get("budget_total", "")),
                call.get("source", ""),
                call.get("link", ""),
                call.get("expected_outcomes", ""),
                call.get("scope", ""),
                ", ".join(call.get("keywords", [])),
            ])

        for col in ws.columns:
            max_len = 0
            letter = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_len:
                        max_len = len(str(cell.value))
                except Exception:
                    pass
            ws.column_dimensions[letter].width = min(max_len + 2, 50)

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    else:
        import csv
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Call ID", "Title", "Status", "Deadline", "Action Types", "Source"])
        for call in calls:
            writer.writerow([
                call.get("call_id", ""), call.get("title", ""),
                call.get("status", ""), call.get("deadline", ""),
                ", ".join(call.get("action_types", [])),
                call.get("source", ""),
            ])
        return buf.getvalue().encode("utf-8")
