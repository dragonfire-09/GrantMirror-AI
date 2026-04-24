"""
GrantMirror-AI: Live call data fetcher from EC Funding & Tenders Portal.
Uses EC SEDIA Search API with current Horizon filtering, fallback, cache and Excel export.
"""

import re
import time
import requests
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple


EC_API_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"


# =========================================================
# DATE / FILTER HELPERS
# =========================================================

def _parse_date_safe(value):
    if not value:
        return None

    text = str(value)

    match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if match:
        text = match.group(1)
    else:
        text = text[:10]

    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except Exception:
        return None


def _normalize_status(status_raw: str) -> str:
    text = str(status_raw).lower()

    if "31094501" in text:
        return "Open"

    if "31094502" in text:
        return "Forthcoming"

    if "31094503" in text:
        return "Closed"

    if "open" in text:
        return "Open"

    if "forthcoming" in text or "planned" in text:
        return "Forthcoming"

    if "closed" in text:
        return "Closed"

    return str(status_raw) if status_raw else "Unknown"


def _keep_only_current_horizon(call: Dict) -> bool:
    """
    Keep only current Horizon Europe calls.
    Removes H2020 / 2014-2020 archive / closed old calls.
    """

    text = " ".join(
        [
            str(call.get("call_id", "")),
            str(call.get("title", "")),
            str(call.get("programme", "")),
            str(call.get("status", "")),
            " ".join(str(t.get("topic_id", "")) for t in call.get("topics", [])),
        ]
    ).upper()

    if "H2020" in text or "HORIZON 2020" in text:
        return False

    old_years = ["2014", "2015", "2016", "2017", "2018", "2019", "2020"]
    if any(year in text for year in old_years):
        return False

    status = str(call.get("status", "")).lower()

    if "closed" in status:
        return False

    deadline = _parse_date_safe(call.get("deadline"))

    if deadline and deadline < date.today():
        return False

    return True


def _deduplicate_calls(calls: List[Dict]) -> List[Dict]:
    seen = set()
    unique = []

    for call in calls:
        key = (
            call.get("call_id", ""),
            call.get("title", "")[:80],
            call.get("deadline", ""),
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(call)

    return unique


# =========================================================
# MAIN FETCHER
# =========================================================

def fetch_horizon_calls(
    programme: str = "HORIZON",
    status: str = "",
    page_size: int = 100,
    page: int = 1,
    search_text: str = "",
) -> Tuple[List[Dict], int]:
    """
    Fetch current Horizon Europe calls from EC Funding & Tenders Search API.

    status:
    - "" means Open + Forthcoming
    - "Open"
    - "Forthcoming"
    - "Closed" is intentionally discouraged for current dashboard
    """

    calls = []

    # If status empty, fetch Open + Forthcoming separately for cleaner results.
    statuses_to_fetch = [status] if status else ["Open", "Forthcoming"]

    for st in statuses_to_fetch:
        fetched = _fetch_single_status(
            programme=programme,
            status=st,
            page_size=page_size,
            page=page,
            search_text=search_text,
        )

        calls.extend(fetched)

    calls = _deduplicate_calls(calls)

    # Sort by deadline ascending, N/A last.
    calls.sort(
        key=lambda c: _parse_date_safe(c.get("deadline")) or date(2999, 12, 31)
    )

    return calls, len(calls)


def _fetch_single_status(
    programme: str = "HORIZON",
    status: str = "Open",
    page_size: int = 100,
    page: int = 1,
    search_text: str = "",
) -> List[Dict]:
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
        "sort": "sortStatus asc,deadlineDate asc",
    }

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "GrantMirror-AI/1.0",
    }

    try:
        response = requests.get(
            EC_API_URL,
            params=params,
            headers=headers,
            timeout=30,
        )

        if response.status_code != 200:
            return _fetch_fallback(
                programme=programme,
                status=status,
                page_size=page_size,
                page=page,
                search_text=search_text,
            )

        data = response.json()
        results = data.get("results", [])

        calls = []

        for item in results:
            parsed = _parse_result(item)

            if parsed and _keep_only_current_horizon(parsed):
                calls.append(parsed)

        return calls

    except Exception:
        return _fetch_fallback(
            programme=programme,
            status=status,
            page_size=page_size,
            page=page,
            search_text=search_text,
        )


# =========================================================
# FALLBACK
# =========================================================

def _fetch_fallback(
    programme: str,
    status: str,
    page_size: int,
    page: int,
    search_text: str,
) -> List[Dict]:
    query = search_text if search_text else "Horizon Europe"

    params = {
        "apiKey": "SEDIA",
        "text": query,
        "type": "1",
        "pageSize": str(page_size),
        "pageNumber": str(page),
        "sort": "sortStatus asc,deadlineDate asc",
    }

    try:
        response = requests.get(EC_API_URL, params=params, timeout=30)

        if response.status_code != 200:
            return _get_sample_calls()

        data = response.json()
        results = data.get("results", [])

        calls = []

        for item in results:
            parsed = _parse_result(item)

            if not parsed:
                continue

            if status:
                normalized = _normalize_status(parsed.get("status", ""))
                if normalized != status:
                    continue

            if _keep_only_current_horizon(parsed):
                calls.append(parsed)

        return calls

    except Exception:
        return _get_sample_calls()


# =========================================================
# PARSING
# =========================================================

def _as_string(value, default=""):
    if value is None:
        return default

    if isinstance(value, list):
        if not value:
            return default
        return _as_string(value[0], default)

    if isinstance(value, dict):
        return str(
            value.get("description")
            or value.get("abbr")
            or value.get("code")
            or value.get("label")
            or default
        )

    return str(value)


def _as_list(value):
    if value is None:
        return []

    if isinstance(value, list):
        return [str(v) for v in value if v is not None]

    if isinstance(value, dict):
        return [
            str(
                value.get("description")
                or value.get("abbr")
                or value.get("code")
                or value
            )
        ]

    if isinstance(value, str):
        if "," in value:
            return [v.strip() for v in value.split(",") if v.strip()]
        return [value]

    return [str(value)]


def _parse_result(item: Dict) -> Optional[Dict]:
    try:
        meta = item.get("metadata", {}) or item

        def get(*keys, default=""):
            for key in keys:
                if key in meta:
                    val = meta.get(key)
                    if val not in [None, "", []]:
                        return _as_string(val, default)
            return default

        def get_list(*keys):
            for key in keys:
                if key in meta:
                    val = meta.get(key)
                    if val not in [None, "", []]:
                        return _as_list(val)
            return []

        call_id = get("identifier", "callIdentifier", "ccm2Id", "topicIdentifier")
        title = get("title", "callTitle", "topicTitle")

        if not title and not call_id:
            return None

        status_raw = get("status", "callStatus", "sortStatus")
        status = _normalize_status(status_raw)

        deadline = get("deadlineDate", "deadlineDates", "deadline", "endDate")
        opening = get("startDate", "openingDate")
        budget = get("budget", "callBudget", "budgetOverall", default="N/A")

        action_types = get_list("typesOfAction", "typeOfAction", "actionType", "fundingScheme")

        topic_ids = get_list("topicIdentifier", "topicId", "identifier")
        topic_titles = get_list("topicTitle", "title")

        topics = []

        for i, topic_id in enumerate(topic_ids):
            topic_title = topic_titles[i] if i < len(topic_titles) else topic_id
            topics.append(
                {
                    "topic_id": str(topic_id),
                    "title": str(topic_title),
                }
            )

        keywords = get_list("keywords", "tags")
        programme = " / ".join(get_list("programmePeriod", "programme")) or get(
            "frameworkProgramme",
            default="HORIZON",
        )

        url_val = get("url", "link")

        if not url_val and topic_ids:
            clean_topic = str(topic_ids[0]).split(",")[0].strip()
            url_val = (
                "https://ec.europa.eu/info/funding-tenders/opportunities/"
                f"portal/screen/opportunities/topic-details/{clean_topic}"
            )

        elif not url_val and call_id:
            url_val = (
                "https://ec.europa.eu/info/funding-tenders/opportunities/"
                f"portal/screen/opportunities/calls-for-proposals?callIdentifier={call_id}"
            )

        deadline_date = _parse_date_safe(deadline)
        deadline_clean = deadline_date.isoformat() if deadline_date else str(deadline or "N/A")[:20]

        return {
            "call_id": call_id or "N/A",
            "title": title or "N/A",
            "status": status,
            "programme": programme,
            "opening_date": opening,
            "deadline": deadline_clean,
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


# =========================================================
# TOPIC DETAILS
# =========================================================

def fetch_topic_details(topic_id: str) -> Optional[Dict]:
    params = {
        "apiKey": "SEDIA",
        "text": f'identifier/"{topic_id}"',
        "type": "1",
        "pageSize": "5",
    }

    try:
        response = requests.get(EC_API_URL, params=params, timeout=20)

        if response.status_code != 200:
            return None

        data = response.json()
        results = data.get("results", [])

        for result in results:
            meta = result.get("metadata", {})

            identifier = meta.get("identifier", "")

            if isinstance(identifier, list):
                identifier = identifier[0] if identifier else ""

            if topic_id.lower() not in str(identifier).lower():
                continue

            description = meta.get("description", "")

            if isinstance(description, list):
                description = description[0] if description else ""

            title = meta.get("title", "")

            if isinstance(title, list):
                title = title[0] if title else ""

            return {
                "topic_id": topic_id,
                "title": title,
                "description": description,
                "keywords": meta.get("keywords", []),
                "deadline": meta.get("deadlineDate", ""),
                "action_type": meta.get("typesOfAction", []),
            }

    except Exception:
        return None

    return None


# =========================================================
# ACTION TYPE / CONTEXT
# =========================================================

def detect_action_type_from_call(call_data: Dict) -> str:
    action_types = call_data.get("action_types", [])

    all_text = " ".join(
        action_types
        + [
            call_data.get("title", ""),
            call_data.get("call_id", ""),
        ]
    ).upper()

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

    if "RIA" in all_text:
        return "RIA"

    if re.search(r"\bIA\b", all_text):
        return "IA"

    return "RIA"


def build_call_specific_criteria(
    call_data: Dict,
    topic_details: Optional[Dict] = None,
) -> Dict:
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
        description = topic_details.get("description", "")

        context["topic_scope"] = description[:3000] if description else ""
        context["topic_keywords"] = topic_details.get(
            "keywords",
            context["topic_keywords"],
        )
        context["expected_outcomes"] = _extract_outcomes(description)

    context["evaluation_context"] = _build_context_text(context)

    return context


def _extract_outcomes(description: str) -> List[str]:
    outcomes = []
    lines = description.split("\n")
    capture = False

    for line in lines:
        stripped = line.strip()
        lowered = stripped.lower()

        if "expected outcome" in lowered or "expected impact" in lowered:
            capture = True
            continue

        if capture:
            if stripped.startswith(("-", "•", "–", "*")) or (
                len(stripped) > 15 and stripped[0].isupper()
            ):
                outcomes.append(stripped.lstrip("-•–* "))

            elif stripped == "" and outcomes:
                capture = False

    return outcomes[:10]


def _build_context_text(ctx: Dict) -> str:
    parts = [
        f"CALL: {ctx.get('call_title', 'N/A')}",
        f"ACTION TYPE: {ctx.get('action_type', 'N/A')}",
        f"DEADLINE: {ctx.get('deadline', 'N/A')}",
        f"BUDGET: {ctx.get('budget', 'N/A')}",
    ]

    if ctx.get("topic_scope"):
        parts.append(f"\nTOPIC SCOPE:\n{ctx['topic_scope'][:2000]}")

    outcomes = ctx.get("expected_outcomes", [])

    if outcomes:
        parts.append("\nEXPECTED OUTCOMES:")

        for index, outcome in enumerate(outcomes, 1):
            parts.append(f"  {index}. {outcome}")

    keywords = ctx.get("topic_keywords", [])

    if keywords:
        parts.append(
            f"\nKEYWORDS: {', '.join(str(k) for k in keywords[:15])}"
        )

    return "\n".join(parts)


# =========================================================
# EXCEL EXPORT
# =========================================================

def calls_to_excel_bytes(calls: List[Dict]) -> bytes:
    import pandas as pd
    from io import BytesIO

    rows = []

    for call in calls:
        rows.append(
            {
                "Call ID": call.get("call_id", ""),
                "Title": call.get("title", ""),
                "Status": call.get("status", ""),
                "Programme": call.get("programme", ""),
                "Opening Date": call.get("opening_date", ""),
                "Deadline": call.get("deadline", ""),
                "Budget": call.get("budget", ""),
                "Action Types": ", ".join(call.get("action_types", [])),
                "Topics": ", ".join(
                    topic.get("topic_id", "") for topic in call.get("topics", [])
                ),
                "Keywords": ", ".join(str(k) for k in call.get("keywords", [])),
                "URL": call.get("url", ""),
                "Source": call.get("source", ""),
            }
        )

    df = pd.DataFrame(rows)

    output = BytesIO()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Horizon Calls")

        workbook = writer.book
        worksheet = writer.sheets["Horizon Calls"]

        header_format = workbook.add_format(
            {
                "bold": True,
                "bg_color": "#101828",
                "font_color": "white",
                "border": 1,
            }
        )

        for col_num, value in enumerate(df.columns):
            worksheet.write(0, col_num, value, header_format)
            worksheet.set_column(col_num, col_num, 26)

        worksheet.freeze_panes(1, 0)
        worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)

    output.seek(0)

    return output.getvalue()


# =========================================================
# SAMPLE FALLBACK
# =========================================================

def _get_sample_calls() -> List[Dict]:
    return [
        {
            "call_id": "HORIZON-CL6-2025-01",
            "title": "Sample Horizon Europe Cluster 6 2025 Call",
            "status": "Open",
            "programme": "HORIZON",
            "opening_date": "2025-01-01",
            "deadline": "2026-12-31",
            "budget": "N/A",
            "action_types": ["RIA"],
            "topics": [
                {
                    "topic_id": "HORIZON-CL6-2025-01-01",
                    "title": "Sample topic",
                }
            ],
            "keywords": ["Horizon Europe", "Cluster 6"],
            "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal",
            "raw": {},
            "source": "sample",
        }
    ]


# =========================================================
# SIMPLE TTL CACHE
# =========================================================

class CallCache:
    def __init__(self, ttl_minutes=30):
        self._cache = {}
        self._ttl = ttl_minutes * 60

    def get(self, key):
        if key in self._cache:
            value, timestamp = self._cache[key]

            if time.time() - timestamp < self._ttl:
                return value

            del self._cache[key]

        return None

    def set(self, key, value):
        self._cache[key] = (value, time.time())

    def clear(self):
        self._cache.clear()
