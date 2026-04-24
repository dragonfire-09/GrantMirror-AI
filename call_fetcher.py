"""
GrantMirror-AI: Live call data fetcher from EC Funding & Tenders API.
Fetches open/forthcoming Horizon Europe calls with metadata,
deadlines, topics, and evaluation criteria.
"""
import requests
import json
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum


# ═══════════════════════════════════════════════════════════
# EC API ENDPOINTS
# ═══════════════════════════════════════════════════════════
EC_SEARCH_API = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
CORDIS_API = "https://cordis.europa.eu/api/search"
FTOP_BASE = "https://ec.europa.eu/info/funding-tenders/opportunities"

# Funding & Tenders API query params
FT_API_PARAMS = {
    "apiKey": "SEDIA",
    "text": "*",
    "type": "1",  # 1 = calls for proposals
    "sort": "sortStatus asc,deadlineDate desc",
    "pageSize": "50",
    "pageNumber": "1",
}


class CallStatus(str, Enum):
    OPEN = "Open"
    FORTHCOMING = "Forthcoming"
    CLOSED = "Closed"


@dataclass
class TopicInfo:
    topic_id: str
    title: str
    description: str
    expected_outcomes: List[str]
    scope: str
    destination: str
    budget_range: str
    trl_expected: str
    action_type: str
    keywords: List[str]
    conditions: Dict[str, str]


@dataclass
class CallInfo:
    call_id: str
    call_title: str
    programme: str
    status: str
    opening_date: str
    deadline: str
    budget_total: str
    topics: List[TopicInfo]
    action_types: List[str]
    two_stage: bool
    lump_sum: bool
    blind_evaluation: bool
    page_limit: Optional[int]
    min_consortium: int
    min_countries: int
    specific_conditions: List[str]
    evaluation_criteria: List[Dict]
    url: str
    raw_data: Dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
# API FETCHING
# ═══════════════════════════════════════════════════════════
def fetch_horizon_calls(
    programme: str = "HORIZON",
    status: str = "",
    page_size: int = 50,
    page: int = 1,
    search_text: str = "",
) -> Tuple[List[Dict], int]:
    """
    Fetch calls from EC Funding & Tenders Search API.
    Returns (list of raw call dicts, total count).
    """
    params = {
        "apiKey": "SEDIA",
        "type": "1",
        "sort": "sortStatus asc,deadlineDate desc",
        "pageSize": str(page_size),
        "pageNumber": str(page),
    }

    # Build query
    query_parts = []
    if programme:
        query_parts.append(f'programmePeriod="{programme}" OR frameworkProgramme="{programme}"')
    if status:
        status_map = {"Open": "31094501", "Forthcoming": "31094502", "Closed": "31094503"}
        if status in status_map:
            query_parts.append(f'status/code="{status_map[status]}"')
    if search_text:
        query_parts.append(search_text)

    params["query"] = " AND ".join(query_parts) if query_parts else "*"

    try:
        resp = requests.get(
            EC_SEARCH_API,
            params=params,
            headers={"Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        total = data.get("totalResults", 0)

        calls = []
        for item in results:
            metadata = item.get("metadata", {})
            calls.append(_parse_call_metadata(metadata, item))

        return calls, total

    except requests.RequestException as e:
        return [], 0
    except (json.JSONDecodeError, KeyError) as e:
        return [], 0


def _parse_call_metadata(metadata: Dict, raw_item: Dict) -> Dict:
    """Parse raw API metadata into structured call dict."""

    def _get_field(key, default=""):
        val = metadata.get(key, default)
        if isinstance(val, list):
            return val[0] if val else default
        return val or default

    def _get_list(key):
        val = metadata.get(key, [])
        if isinstance(val, str):
            return [val]
        return val if isinstance(val, list) else []

    call_id = _get_field("identifier")
    title = _get_field("title")
    status = _get_field("status")
    programme = " / ".join(_get_list("programmePeriod"))

    # Dates
    opening = _get_field("startDate")
    deadline = _get_field("deadlineDate")

    # Budget
    budget = _get_field("budget", "N/A")

    # Action types from topics
    action_types = _get_list("actionType")
    if not action_types:
        action_types = _get_list("typesOfAction")

    # Keywords
    keywords = _get_list("keywords")

    # Topics
    topic_ids = _get_list("topicIdentifier")
    topic_titles = _get_list("topicTitle")

    topics = []
    for i, tid in enumerate(topic_ids):
        t_title = topic_titles[i] if i < len(topic_titles) else tid
        topics.append({
            "topic_id": tid,
            "title": t_title,
        })

    # URL
    url = f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{topic_ids[0]}" if topic_ids else ""

    return {
        "call_id": call_id,
        "title": title,
        "status": status,
        "programme": programme,
        "opening_date": opening,
        "deadline": deadline,
        "budget": budget,
        "action_types": action_types,
        "topics": topics,
        "keywords": keywords,
        "url": url,
        "raw": raw_item,
    }


def fetch_topic_details(topic_id: str) -> Optional[Dict]:
    """
    Fetch detailed topic information including scope, expected outcomes.
    """
    url = f"https://api.tech.ec.europa.eu/search-api/prod/rest/search"
    params = {
        "apiKey": "SEDIA",
        "query": f'identifier="{topic_id}"',
        "type": "1",
        "pageSize": "1",
    }

    try:
        resp = requests.get(url, params=params, headers={"Accept": "application/json"}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if results:
            meta = results[0].get("metadata", {})
            return {
                "topic_id": topic_id,
                "title": meta.get("title", ""),
                "description": meta.get("description", ""),
                "conditions": meta.get("conditions", ""),
                "budget": meta.get("budget", ""),
                "action_type": meta.get("actionType", []),
                "keywords": meta.get("keywords", []),
                "deadline": meta.get("deadlineDate", ""),
            }
        return None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# CRITERIA BUILDER (per action type + call specifics)
# ═══════════════════════════════════════════════════════════
def detect_action_type_from_call(call_data: Dict) -> str:
    """Detect the primary action type from call metadata."""
    action_types = call_data.get("action_types", [])

    if not action_types:
        title = call_data.get("title", "").upper()
        if "MSCA" in title or "MARIE" in title:
            return "MSCA-DN"
        elif "ERC" in title:
            return "ERC-StG"
        elif "EIC" in title and "PATHFINDER" in title:
            return "EIC-Pathfinder-Open"
        elif "EIC" in title and "ACCELERATOR" in title:
            return "EIC-Accelerator"
        elif "CSA" in title:
            return "CSA"
        elif "IA" in title:
            return "IA"
        return "RIA"

    at = action_types[0].upper() if action_types else ""

    if "RIA" in at:
        return "RIA"
    elif "IA" in at and "RIA" not in at:
        return "IA"
    elif "CSA" in at:
        return "CSA"
    elif "MSCA" in at or "TMA" in at:
        return "MSCA-DN"
    elif "ERC" in at:
        return "ERC-StG"
    elif "PATHFINDER" in at:
        return "EIC-Pathfinder-Open"
    elif "ACCELERATOR" in at:
        return "EIC-Accelerator"
    return "RIA"


def build_call_specific_criteria(call_data: Dict, topic_details: Optional[Dict] = None) -> Dict:
    """
    Build call-specific evaluation context by combining:
    1. Action type standard criteria (from config)
    2. Topic-specific expected outcomes and scope
    3. Call-specific conditions
    """
    action_type = detect_action_type_from_call(call_data)

    context = {
        "action_type": action_type,
        "call_id": call_data.get("call_id", ""),
        "call_title": call_data.get("title", ""),
        "deadline": call_data.get("deadline", ""),
        "budget": call_data.get("budget", ""),
    }

    # Topic-specific enrichment
    if topic_details:
        desc = topic_details.get("description", "")
        context["topic_scope"] = desc[:3000] if desc else ""
        context["topic_keywords"] = topic_details.get("keywords", [])
        context["topic_conditions"] = topic_details.get("conditions", "")

        # Extract expected outcomes from description
        outcomes = _extract_expected_outcomes(desc)
        context["expected_outcomes"] = outcomes
    else:
        context["topic_scope"] = ""
        context["expected_outcomes"] = []
        context["topic_keywords"] = call_data.get("keywords", [])

    # Build evaluation context text for LLM
    context["evaluation_context"] = _build_evaluation_context_text(context)

    return context


def _extract_expected_outcomes(description: str) -> List[str]:
    """Extract expected outcomes from topic description text."""
    outcomes = []
    lines = description.split("\n")
    in_outcomes = False

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        if "expected outcome" in lower or "expected impact" in lower:
            in_outcomes = True
            continue

        if in_outcomes:
            if stripped.startswith(("-", "•", "–", "*")) or (len(stripped) > 10 and stripped[0].isupper()):
                outcomes.append(stripped.lstrip("-•–* "))
            elif stripped == "" and outcomes:
                in_outcomes = False

    return outcomes[:10]


def _build_evaluation_context_text(context: Dict) -> str:
    """Build a text block for LLM evaluation context."""
    parts = []

    parts.append(f"CALL: {context.get('call_title', 'N/A')}")
    parts.append(f"ACTION TYPE: {context.get('action_type', 'N/A')}")
    parts.append(f"DEADLINE: {context.get('deadline', 'N/A')}")
    parts.append(f"BUDGET: {context.get('budget', 'N/A')}")

    if context.get("topic_scope"):
        parts.append(f"\nTOPIC SCOPE:\n{context['topic_scope'][:2000]}")

    outcomes = context.get("expected_outcomes", [])
    if outcomes:
        parts.append("\nEXPECTED OUTCOMES:")
        for i, o in enumerate(outcomes, 1):
            parts.append(f"  {i}. {o}")

    keywords = context.get("topic_keywords", [])
    if keywords:
        parts.append(f"\nKEYWORDS: {', '.join(keywords[:15])}")

    conditions = context.get("topic_conditions", "")
    if conditions:
        parts.append(f"\nSPECIAL CONDITIONS:\n{conditions[:500]}")

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════
# CALL CACHE (simple in-memory)
# ═══════════════════════════════════════════════════════════
class CallCache:
    """Simple cache to avoid re-fetching."""

    def __init__(self, ttl_minutes: int = 30):
        self._cache: Dict[str, Tuple[any, float]] = {}
        self._ttl = ttl_minutes * 60

    def get(self, key: str):
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                return value
            del self._cache[key]
        return None

    def set(self, key: str, value):
        self._cache[key] = (value, time.time())

    def clear(self):
        self._cache.clear()
