"""
GrantMirror-AI: Live call data fetcher from EC Funding & Tenders Portal.
Uses the real EC SEDIA Search API.
"""
import requests
import json
import time
from typing import List, Dict, Optional, Tuple


# ═══════════════════════════════════════════════════════════
# WORKING EC API ENDPOINT
# ═══════════════════════════════════════════════════════════
EC_API_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"


def fetch_horizon_calls(
    programme: str = "HORIZON",
    status: str = "",
    page_size: int = 30,
    page: int = 1,
    search_text: str = "",
) -> Tuple[List[Dict], int]:
    """
    Fetch calls from EC Funding & Tenders Search API.
    """
    # Build query string
    query_parts = []

    if programme:
        query_parts.append(f"frameworkProgramme/{programme}")

    if status:
        status_code = {
            "Open": "31094501",
            "Forthcoming": "31094502",
            "Closed": "31094503",
        }.get(status, "")
        if status_code:
            query_parts.append(f"status/code/{status_code}")

    if search_text and search_text.strip():
        query_parts.append(search_text.strip())

    query = " AND ".join(query_parts) if query_parts else "frameworkProgramme/HORIZON"

    params = {
        "apiKey": "SEDIA",
        "text": query,
        "type": "1",
        "pageSize": str(page_size),
        "pageNumber": str(page),
        "sort": "sortStatus asc,deadlineDate desc",
    }

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.get(EC_API_URL, params=params, headers=headers, timeout=30)

        if resp.status_code != 200:
            # Try alternative query format
            return _fetch_fallback(programme, status, page_size, page, search_text)

        data = resp.json()
        results = data.get("results", [])
        total = data.get("totalResults", len(results))

        calls = []
        for item in results:
            parsed = _parse_result(item)
            if parsed:
                calls.append(parsed)

        return calls, total

    except Exception as e:
        # Try fallback
        return _fetch_fallback(programme, status, page_size, page, search_text)


def _fetch_fallback(programme, status, page_size, page, search_text):
    """Fallback: try different query format."""
    query = search_text if search_text else "Horizon Europe"

    params = {
        "apiKey": "SEDIA",
        "text": query,
        "type": "1",
        "pageSize": str(page_size),
        "pageNumber": str(page),
        "sort": "sortStatus asc",
    }

    try:
        resp = requests.get(EC_API_URL, params=params, timeout=30)
        if resp.status_code != 200:
            return _fetch_cordis_fallback(programme, status, page_size, search_text)

        data = resp.json()
        results = data.get("results", [])
        total = data.get("totalResults", len(results))

        calls = []
        for item in results:
            parsed = _parse_result(item)
            if parsed:
                # Filter by programme if needed
                if programme:
                    prog = parsed.get("programme", "").upper()
                    if programme.upper() not in prog and "HORIZON" not in prog:
                        continue
                # Filter by status if needed
                if status:
                    call_status = parsed.get("status", "").lower()
                    if status.lower() not in call_status:
                        continue
                calls.append(parsed)

        return calls, total

    except Exception:
        return _fetch_cordis_fallback(programme, status, page_size, search_text)


def _fetch_cordis_fallback(programme, status, page_size, search_text):
    """Second fallback: use CORDIS API."""
    try:
        query = search_text if search_text else "Horizon Europe"
        url = "https://cordis.europa.eu/api/search"
        params = {
            "q": query,
            "type": "project",
            "subtype": "HE",
            "page": "1",
            "num": str(min(page_size, 20)),
            "format": "json",
        }

        resp = requests.get(url, params=params, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("payload", {}).get("results", [])
            calls = []
            for r in results:
                calls.append({
                    "call_id": r.get("acronym", r.get("rcn", "?")),
                    "title": r.get("title", "N/A"),
                    "status": r.get("status", "?"),
                    "programme": "HORIZON",
                    "opening_date": r.get("startDate", ""),
                    "deadline": r.get("endDate", ""),
                    "budget": r.get("totalCost", "N/A"),
                    "action_types": [r.get("fundingScheme", "")],
                    "topics": [],
                    "keywords": [],
                    "url": f"https://cordis.europa.eu/project/id/{r.get('rcn', '')}",
                    "raw": r,
                    "source": "CORDIS",
                })
            return calls, len(calls)
    except Exception:
        pass

    # Final fallback: return curated sample data
    return _get_sample_calls(), 10


def _parse_result(item: Dict) -> Optional[Dict]:
    """Parse a single API result item."""
    try:
        meta = item.get("metadata", {})
        if not meta:
            # Try flat structure
            meta = item

        def _get(key, default=""):
            val = meta.get(key, default)
            if isinstance(val, list):
                return val[0] if val else default
            return str(val) if val else default

        def _get_list(key):
            val = meta.get(key, [])
            if isinstance(val, str):
                return [val]
            return list(val) if val else []

        call_id = _get("identifier", _get("callIdentifier", _get("ccm2Id", "")))
        title = _get("title", "")

        if not title and not call_id:
            return None

        status_raw = _get("status", "")
        if isinstance(meta.get("status"), dict):
            status_raw = meta["status"].get("abbr", meta["status"].get("description", ""))

        # Normalize status
        status = status_raw
        if "open" in status_raw.lower():
            status = "Open"
        elif "forthcoming" in status_raw.lower() or "planned" in status_raw.lower():
            status = "Forthcoming"
        elif "closed" in status_raw.lower():
            status = "Closed"

        deadline = _get("deadlineDate", _get("deadlineDates", ""))
        opening = _get("startDate", _get("openingDate", ""))
        budget = _get("budget", _get("callBudget", "N/A"))

        action_types = _get_list("typesOfAction")
        if not action_types:
            action_types = _get_list("actionType")
        if not action_types:
            action_types = _get_list("fundingScheme")

        topic_ids = _get_list("topicIdentifier")
        topic_titles = _get_list("topicTitle")
        topics = []
        for i, tid in enumerate(topic_ids):
            t_title = topic_titles[i] if i < len(topic_titles) else tid
            topics.append({"topic_id": tid, "title": t_title})

        keywords = _get_list("keywords")
        programme = " / ".join(_get_list("programmePeriod")) or _get("frameworkProgramme", "HORIZON")

        url_val = _get("url", "")
        if not url_val and topic_ids:
            url_val = f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{topic_ids[0]}"
        elif not url_val and call_id:
            url_val = f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/calls-for-proposals?callIdentifier={call_id}"

        return {
            "call_id": call_id or "N/A",
            "title": title or "N/A",
            "status": status,
            "programme": programme,
            "opening_date": opening,
            "deadline": deadline,
            "budget": str(budget),
            "action_types": action_types,
            "topics": topics,
            "keywords": keywords,
            "url": url_val,
            "raw": item,
            "source": "EC_API",
        }

    except Exception:
        return None


def fetch_topic_details(topic_id: str) -> Optional[Dict]:
    """Fetch detailed topic information."""
    params = {
        "apiKey": "SEDIA",
        "text": f'identifier/"{topic_id}"',
        "type": "1",
        "pageSize": "5",
    }

    try:
        resp = requests.get(EC_API_URL, params=params, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            for r in results:
                meta = r.get("metadata", {})
                ident = meta.get("identifier", "")
                if isinstance(ident, list):
                    ident = ident[0] if ident else ""
                if topic_id.lower() in str(ident).lower():
                    desc = meta.get("description", "")
                    if isinstance(desc, list):
                        desc = desc[0] if desc else ""
                    return {
                        "topic_id": topic_id,
                        "title": meta.get("title", [""])[0] if isinstance(meta.get("title"), list) else meta.get("title", ""),
                        "description": desc,
                        "keywords": meta.get("keywords", []),
                        "deadline": meta.get("deadlineDate", ""),
                        "action_type": meta.get("typesOfAction", []),
                    }
    except Exception:
        pass

    return None


def detect_action_type_from_call(call_data: Dict) -> str:
    """Detect primary action type from call metadata."""
    action_types = call_data.get("action_types", [])
    all_text = " ".join(action_types + [call_data.get("title", ""), call_data.get("call_id", "")]).upper()

    if "MSCA" in all_text or "MARIE" in all_text:
        return "MSCA-DN"
    if "ERC" in all_text:
        return "ERC-StG"
    if "PATHFINDER" in all_text:
        return "EIC-Pathfinder-Open"
    if "ACCELERATOR" in all_text:
        return "EIC-Accelerator"
    if "EIC" in all_text:
        return "EIC-Pathfinder-Open"
    if "CSA" in all_text:
        return "CSA"
    if "IA" in all_text and "RIA" not in all_text:
        return "IA"
    return "RIA"


def build_call_specific_criteria(call_data: Dict, topic_details: Optional[Dict] = None) -> Dict:
    """Build call-specific evaluation context."""
    action_type = detect_action_type_from_call(call_data)

    context = {
        "action_type": action_type,
        "call_id": call_data.get("call_id", ""),
        "call_title": call_data.get("title", ""),
        "deadline": call_data.get("deadline", ""),
        "budget": call_data.get("budget", ""),
        "topic_scope": "",
        "expected_outcomes": [],
        "topic_keywords": call_data.get("keywords", []),
    }

    if topic_details:
        desc = topic_details.get("description", "")
        context["topic_scope"] = desc[:3000] if desc else ""
        context["topic_keywords"] = topic_details.get("keywords", context["topic_keywords"])
        context["expected_outcomes"] = _extract_outcomes(desc)

    context["evaluation_context"] = _build_context_text(context)
    return context


def _extract_outcomes(desc: str) -> List[str]:
    """Extract expected outcomes from topic description."""
    outcomes = []
    lines = desc.split("\n")
    capture = False
    for line in lines:
        s = line.strip()
        lo = s.lower()
        if "expected outcome" in lo or "expected impact" in lo:
            capture = True
            continue
        if capture:
            if s.startswith(("-", "•", "–", "*")) or (len(s) > 15 and s[0].isupper()):
                outcomes.append(s.lstrip("-•–* "))
            elif s == "" and outcomes:
                capture = False
    return outcomes[:10]


def _build_context_text(ctx: Dict) -> str:
    """Build evaluation context text for LLM."""
    parts = [
        f"CALL: {ctx.get('call_title', 'N/A')}",
        f"ACTION TYPE: {ctx.get('action_type', 'N/A')}",
        f"DEADLINE: {ctx.get('deadline', 'N/A')}",
        f"BUDGET: {ctx.get('budget', 'N/A')}",
    ]
    if ctx.get("topic_scope"):
        parts.append(f"\nTOPIC SCOPE:\n{ctx['topic_scope'][:2000]}")
    oc = ctx.get("expected_outcomes", [])
    if oc:
        parts.append("\nEXPECTED OUTCOMES:")
        for i, o in enumerate(oc, 1):
            parts.append(f"  {i}. {o}")
    kw = ctx.get("topic_keywords", [])
    if kw:
        parts.append(f"\nKEYWORDS: {', '.join(str(k) for k in kw[:15])}")
    return "\n".join(parts)


def _get_sample_calls() -> List[Dict]:
    """Return sample calls when API is unavailable."""
    return [
        {
            "call_id": "HORIZON-CL4-2025-HUMAN-01",
            "title": "A human-centred and ethical development of digital and industrial technologies 2025",
            "status": "Open",
            "programme": "HORIZON",
            "opening_date": "2024-10-22",
            "deadline": "2025-02-19",
            "budget": "EUR 78,000,000",
            "action_types": ["RIA", "IA"],
            "topics": [{"topic_id": "HORIZON-CL4-2025-HUMAN-01-01", "title": "Next Generation AI"}],
            "keywords": ["AI", "digital", "human-centric"],
            "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal",
            "raw": {},
            "source": "sample",
        },
        {
            "call_id": "HORIZON-CL6-2025-BIODIV-01",
            "title": "Biodiversity and ecosystem services 2025",
            "status": "Open",
            "programme": "HORIZON",
            "opening_date": "2024-10-22",
            "deadline": "2025-02-19",
            "budget": "EUR 120,000,000",
            "action_types": ["RIA", "IA", "CSA"],
            "topics": [{"topic_id": "HORIZON-CL6-2025-BIODIV-01-01", "title": "Biodiversity monitoring"}],
            "keywords": ["biodiversity", "ecosystem", "nature-based solutions"],
            "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal",
            "raw": {},
            "source": "sample",
        },
        {
            "call_id": "HORIZON-MSCA-2025-DN-01",
            "title": "MSCA Doctoral Networks 2025",
            "status": "Forthcoming",
            "programme": "HORIZON",
            "opening_date": "2025-05-15",
            "deadline": "2025-11-27",
            "budget": "EUR 451,000,000",
            "action_types": ["MSCA-DN"],
            "topics": [{"topic_id": "HORIZON-MSCA-2025-DN-01", "title": "Doctoral Networks"}],
            "keywords": ["MSCA", "doctoral", "training", "mobility"],
            "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal",
            "raw": {},
            "source": "sample",
        },
        {
            "call_id": "EIC-PATHFINDER-2025-OPEN",
            "title": "EIC Pathfinder Open 2025",
            "status": "Open",
            "programme": "HORIZON",
            "opening_date": "2025-01-08",
            "deadline": "2025-04-16",
            "budget": "EUR 136,000,000",
            "action_types": ["EIC-Pathfinder"],
            "topics": [{"topic_id": "EIC-PATHFINDER-2025", "title": "Pathfinder Open"}],
            "keywords": ["breakthrough", "high-risk", "deep-tech"],
            "url": "https://eic.ec.europa.eu/eic-funding-opportunities_en",
            "raw": {},
            "source": "sample",
        },
        {
            "call_id": "HORIZON-CL5-2025-D3-01",
            "title": "Sustainable, secure and competitive energy supply 2025",
            "status": "Open",
            "programme": "HORIZON",
            "opening_date": "2024-10-22",
            "deadline": "2025-03-05",
            "budget": "EUR 200,000,000",
            "action_types": ["RIA", "IA"],
            "topics": [{"topic_id": "HORIZON-CL5-2025-D3-01-01", "title": "Clean energy technologies"}],
            "keywords": ["energy", "clean", "renewable", "hydrogen"],
            "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal",
            "raw": {},
            "source": "sample",
        },
        {
            "call_id": "HORIZON-HLTH-2025-DISEASE-03",
            "title": "Tackling diseases 2025",
            "status": "Open",
            "programme": "HORIZON",
            "opening_date": "2024-10-22",
            "deadline": "2025-04-16",
            "budget": "EUR 95,000,000",
            "action_types": ["RIA"],
            "topics": [{"topic_id": "HORIZON-HLTH-2025-DISEASE-03-01", "title": "Novel therapeutics"}],
            "keywords": ["health", "disease", "therapeutics", "clinical"],
            "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal",
            "raw": {},
            "source": "sample",
        },
        {
            "call_id": "HORIZON-CL2-2025-HERITAGE-01",
            "title": "Research and innovation on cultural heritage 2025",
            "status": "Forthcoming",
            "programme": "HORIZON",
            "opening_date": "2025-04-10",
            "deadline": "2025-09-18",
            "budget": "EUR 45,000,000",
            "action_types": ["RIA", "CSA"],
            "topics": [{"topic_id": "HORIZON-CL2-2025-HERITAGE-01-01", "title": "Cultural heritage preservation"}],
            "keywords": ["culture", "heritage", "digital", "preservation"],
            "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal",
            "raw": {},
            "source": "sample",
        },
        {
            "call_id": "EIC-ACCELERATOR-2025-01",
            "title": "EIC Accelerator 2025",
            "status": "Open",
            "programme": "HORIZON",
            "opening_date": "2025-01-08",
            "deadline": "2025-03-05",
            "budget": "EUR 675,000,000",
            "action_types": ["EIC-Accelerator"],
            "topics": [{"topic_id": "EIC-ACCELERATOR-2025", "title": "EIC Accelerator Open"}],
            "keywords": ["SME", "scale-up", "deep-tech", "innovation"],
            "url": "https://eic.ec.europa.eu/eic-funding-opportunities_en",
            "raw": {},
            "source": "sample",
        },
    ]


class CallCache:
    """Simple TTL cache."""
    def __init__(self, ttl_minutes=30):
        self._cache = {}
        self._ttl = ttl_minutes * 60

    def get(self, key):
        if key in self._cache:
            val, ts = self._cache[key]
            if time.time() - ts < self._ttl:
                return val
            del self._cache[key]
        return None

    def set(self, key, value):
        self._cache[key] = (value, time.time())

    def clear(self):
        self._cache.clear()
