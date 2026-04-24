"""
GrantMirror-AI call fetcher.

Sources:
- EC Funding & Tenders SEDIA Search API
- Euresearch Open Calls page

No fake/sample fallback.
"""

import re
import time
import requests
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except Exception:
    HAS_BS4 = False


EC_API_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
EURESEARCH_URL = "https://www.euresearch.ch/en/our-services/inform/open-calls-137.html"


def clean_html(text):
    if not text:
        return ""

    text = re.sub(r"<[^>]+>", " ", str(text))
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def _parse_date_safe(value):
    if not value:
        return None

    text = str(value)

    patterns = [
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue

        raw = match.group(1)

        for fmt in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except Exception:
                pass

    return None


def _normalize_status(status_raw):
    text = str(status_raw).lower()

    if "31094501" in text:
        return "Open"

    if "31094502" in text:
        return "Forthcoming"

    if "31094503" in text:
        return "Closed"

    if "open" in text:
        return "Open"

    if "forthcoming" in text or "planned" in text or "upcoming" in text:
        return "Forthcoming"

    if "closed" in text:
        return "Closed"

    return str(status_raw) if status_raw else "Unknown"


def _detect_action_types_from_text(text):
    text_u = str(text).upper()
    found = []

    if re.search(r"\bRIA\b|RESEARCH AND INNOVATION ACTION", text_u):
        found.append("RIA")

    if re.search(r"\bIA\b|INNOVATION ACTION", text_u) and "RIA" not in found:
        found.append("IA")

    if re.search(r"\bCSA\b|COORDINATION AND SUPPORT ACTION", text_u):
        found.append("CSA")

    if "MSCA" in text_u:
        found.append("MSCA-DN")

    if "EIC" in text_u and "ACCELERATOR" in text_u:
        found.append("EIC-Accelerator")

    elif "EIC" in text_u and "PATHFINDER" in text_u:
        found.append("EIC-Pathfinder-Open")

    return found or ["RIA"]


def _keep_only_current_horizon(call):
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

    if any(
        year in text
        for year in ["2014", "2015", "2016", "2017", "2018", "2019", "2020"]
    ):
        return False

    status = str(call.get("status", "")).lower()

    if "closed" in status:
        return False

    deadline = _parse_date_safe(call.get("deadline"))

    if deadline and deadline < date.today():
        return False

    return True


def _deduplicate_calls(calls):
    seen = set()
    unique = []

    for call in calls:
        key = (
            str(call.get("call_id", "")).strip().lower(),
            str(call.get("title", ""))[:100].strip().lower(),
            str(call.get("deadline", "")),
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(call)

    return unique


def fetch_horizon_calls(
    search_text: str = "",
    status: str = "",
    status_filter: str = "",
    programme: str = "HORIZON",
    page_size: int = 100,
    page: int = 1,
    use_ec_api: bool = True,
    use_euresearch: bool = True,
    use_ufukavrupa: bool = False,
    max_api_results: int = 100,
) -> Tuple[List[Dict], Dict]:
    """
    Compatible with current app.py.

    Returns:
    - calls: List[Dict]
    - src_stats: Dict
    """

    selected_status = status_filter or status
    max_results = int(page_size or max_api_results or 100)
    
    if max_results > 500:
        max_results = 500

    all_calls = []

    src_stats = {
        "success": True,
        "ec_api": 0,
        "euresearch": 0,
        "ufukavrupa": 0,
        "local_db": 0,
        "total_calls": 0,
        "ec_debug": {},
    }

    if use_ec_api:
        ec_calls, ec_debug = _fetch_ec_calls(
            programme=programme,
            status=selected_status,
            page_size=max_results,
            page=page,
            search_text=search_text,
        )
        all_calls.extend(ec_calls)
        src_stats["ec_api"] = len(ec_calls)
        src_stats["ec_debug"] = ec_debug

    if use_euresearch:
        euresearch_calls = fetch_euresearch_calls(
            search_text=search_text,
            status=selected_status,
            max_results=max_results,
        )
        all_calls.extend(euresearch_calls)
        src_stats["euresearch"] = len(euresearch_calls)

    filtered = []

    for call in all_calls:
        if not _keep_only_current_horizon(call):
            continue

        if selected_status and call.get("status") != selected_status:
            continue

        if search_text:
            keyword = search_text.lower()
            haystack = " ".join(
                [
                    call.get("call_id", ""),
                    call.get("title", ""),
                    call.get("description", ""),
                    call.get("scope", ""),
                    call.get("destination", ""),
                    " ".join(call.get("keywords", [])),
                ]
            ).lower()

            if keyword not in haystack:
                continue

        filtered.append(call)

    filtered = _deduplicate_calls(filtered)
    filtered.sort(
        key=lambda c: _parse_date_safe(c.get("deadline")) or date(2999, 12, 31)
    )
    filtered = filtered[:max_results]

    src_stats["total_calls"] = len(filtered)
    src_stats["success"] = True

    return filtered, src_stats


def _fetch_ec_calls(
    programme: str = "HORIZON",
    status: str = "",
    page_size: int = 100,
    page: int = 1,
    search_text: str = "",
) -> Tuple[List[Dict], Dict]:
    """
    Fetch EC calls with pagination.
    EC usually returns max 100 results per page.
    """

    max_results = min(int(page_size or 100), 500)
    statuses = [status] if status else ["Open", "Forthcoming"]

    all_calls = []

    debug = {
        "success": False,
        "total_api": 0,
        "pages_fetched": 0,
        "winning_strategy": "ec_get_query_paginated",
        "attempts": [],
    }

    for selected_status in statuses:
        query_parts = []

        if programme:
            query_parts.append(f"frameworkProgramme/{programme}")

        status_code = {
            "Open": "31094501",
            "Forthcoming": "31094502",
            "Closed": "31094503",
        }.get(selected_status, "")

        if status_code:
            query_parts.append(f"status/code/{status_code}")

        if search_text and search_text.strip():
            query_parts.append(search_text.strip())

        query = " AND ".join(query_parts) if query_parts else "frameworkProgramme/HORIZON"

        params = {
            "apiKey": "SEDIA",
            "text": query,
            "type": "1",
            "pageSize": "100",
            "pageNumber": "1",
            "sort": "sortStatus asc,deadlineDate asc",
        }

        all_results = []
        total_results = 0
        max_pages = max(1, (max_results + 99) // 100)

        for page_num in range(1, max_pages + 1):
            params["pageNumber"] = str(page_num)

            try:
                response = requests.get(
                    EC_API_URL,
                    params=params,
                    timeout=30,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "GrantMirror-AI/1.0",
                    },
                )

                attempt = {
                    "strategy": f"ec_get_{selected_status}_page_{page_num}",
                    "status": response.status_code,
                    "url": response.url,
                    "count": 0,
                    "total_results": "?",
                    "page1_count": "?",
                }

                if response.status_code != 200:
                    debug["attempts"].append(attempt)
                    continue

                data = response.json()
                results = data.get("results", [])

                if page_num == 1:
                    total_results = data.get("totalResults", len(results))

                attempt["total_results"] = total_results
                attempt["page1_count"] = len(results)

                if not results:
                    debug["attempts"].append(attempt)
                    break

                all_results.extend(results)

                attempt["count"] = len(results)
                debug["attempts"].append(attempt)
                debug["pages_fetched"] += 1

                if len(all_results) >= max_results:
                    break

            except Exception as e:
                debug["attempts"].append(
                    {
                        "strategy": f"ec_get_{selected_status}_page_{page_num}",
                        "status": "error",
                        "error": str(e),
                        "count": 0,
                    }
                )

        calls = []

        for item in all_results:
            parsed = _parse_ec_result(item)

            if parsed and _keep_only_current_horizon(parsed):
                calls.append(parsed)

        calls = calls[:max_results]

        debug["total_api"] += int(total_results) if str(total_results).isdigit() else 0
        all_calls.extend(calls)

    all_calls = _deduplicate_calls(all_calls)
    all_calls = all_calls[:max_results]
    debug["success"] = len(all_calls) > 0

    return all_calls, debug


def _as_string(value, default=""):
    if value is None:
        return default

    if isinstance(value, list):
        return _as_string(value[0], default) if value else default

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
        return [_as_string(value)]

    if isinstance(value, str):
        if "," in value:
            return [v.strip() for v in value.split(",") if v.strip()]

        return [value]

    return [str(value)]


def _parse_ec_result(item):
    try:
        meta = item.get("metadata", {}) or item

        def get(*keys, default=""):
            for key in keys:
                if key in meta:
                    value = meta.get(key)

                    if value not in [None, "", []]:
                        return _as_string(value, default)

            return default

        def get_list(*keys):
            for key in keys:
                if key in meta:
                    value = meta.get(key)

                    if value not in [None, "", []]:
                        return _as_list(value)

            return []

        call_id = get("identifier", "callIdentifier", "ccm2Id", "topicIdentifier")
        title = get("title", "callTitle", "topicTitle")

        if not title and not call_id:
            return None

        status = _normalize_status(get("status", "callStatus", "sortStatus"))

        deadline_raw = get("deadlineDate", "deadlineDates", "deadline", "endDate")
        deadline_date = _parse_date_safe(deadline_raw)
        deadline = (
            deadline_date.isoformat()
            if deadline_date
            else str(deadline_raw or "N/A")[:20]
        )

        opening = get("startDate", "openingDate")
        budget = get("budget", "callBudget", "budgetOverall", default="N/A")

        action_types = get_list(
            "typesOfAction",
            "typeOfAction",
            "actionType",
            "fundingScheme",
        )

        if not action_types:
            action_types = _detect_action_types_from_text(f"{call_id} {title}")

        topic_ids = get_list("topicIdentifier", "topicId", "identifier")
        topic_titles = get_list("topicTitle", "title")

        topics = []

        for index, topic_id in enumerate(topic_ids):
            topics.append(
                {
                    "topic_id": str(topic_id),
                    "title": str(
                        topic_titles[index]
                        if index < len(topic_titles)
                        else topic_id
                    ),
                }
            )

        keywords = get_list("keywords", "tags")

        programme_value = " / ".join(
            get_list("programmePeriod", "programme")
        ) or get(
            "frameworkProgramme",
            default="HORIZON",
        )

        description = get("description", "shortDescription")
        destination = get("destination", "destinationTitle")

        url = get("url", "link")

        if not url and topic_ids:
            clean_topic = str(topic_ids[0]).split(",")[0].strip()
            url = (
                "https://ec.europa.eu/info/funding-tenders/opportunities/"
                f"portal/screen/opportunities/topic-details/{clean_topic}"
            )

        elif not url and call_id:
            clean_call = str(call_id).split(",")[0].strip()
            url = (
                "https://ec.europa.eu/info/funding-tenders/opportunities/"
                f"portal/screen/opportunities/topic-details/{clean_call}"
            )

        return {
            "call_id": call_id or "N/A",
            "title": clean_html(title) or "N/A",
            "status": status,
            "programme": programme_value,
            "opening_date": opening,
            "deadline": deadline,
            "budget": str(budget),
            "budget_total": str(budget),
            "budget_per_project": "",
            "action_types": action_types,
            "topics": topics,
            "keywords": keywords,
            "destination": clean_html(destination),
            "description": clean_html(description),
            "scope": clean_html(description),
            "expected_outcomes": "",
            "url": url,
            "link": url,
            "raw": item,
            "source": "EC API",
        }

    except Exception:
        return None


def fetch_euresearch_calls(
    search_text: str = "",
    status: str = "",
    max_results: int = 100,
) -> List[Dict]:
    if not HAS_BS4:
        return []

    try:
        params = {}

        if search_text:
            params["filter_search"] = search_text
            params["filter_submit"] = "Filter"

        response = requests.get(
            EURESEARCH_URL,
            params=params,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0 GrantMirror-AI/1.0",
                "Accept": "text/html",
            },
        )

        if response.status_code != 200:
            return []

        soup = BeautifulSoup(response.text, "html.parser")

        calls = []
        current_destination = ""

        for element in soup.find_all(["h2", "h3", "h4", "tr", "li", "article", "div"]):
            tag_name = element.name
            text = clean_html(element.get_text(" ", strip=True))

            if not text:
                continue

            if tag_name in ["h2", "h3", "h4"]:
                if text.lower() not in ["open calls", "filter options", "horizon europe"]:
                    current_destination = text[:150]
                continue

            if not re.search(r"HORIZON-|EIC-|ERC-|MSCA-", text):
                continue

            call_id_match = re.search(
                r"(HORIZON-[A-Z0-9\-]+|EIC-[A-Z0-9\-]+|ERC-[A-Z0-9\-]+|MSCA-[A-Z0-9\-]+)",
                text,
            )

            if not call_id_match:
                continue

            call_id = call_id_match.group(1)
            title = text.replace(call_id, "").strip(" -–|")

            deadline_date = _parse_date_safe(text)
            deadline = deadline_date.isoformat() if deadline_date else "N/A"

            action_types = _detect_action_types_from_text(text)

            link = EURESEARCH_URL
            link_el = element.find("a", href=True)

            if link_el:
                href = link_el.get("href")

                if href.startswith("http"):
                    link = href

                else:
                    link = "https://www.euresearch.ch" + href

            call = {
                "call_id": call_id,
                "title": title or call_id,
                "status": "Open",
                "programme": "HORIZON",
                "opening_date": "",
                "deadline": deadline,
                "budget": "",
                "budget_total": "",
                "budget_per_project": "",
                "action_types": action_types,
                "topics": [{"topic_id": call_id, "title": title or call_id}],
                "keywords": [],
                "destination": current_destination,
                "description": "",
                "scope": "",
                "expected_outcomes": "",
                "url": link,
                "link": link,
                "raw": {},
                "source": "Euresearch",
            }

            if not _keep_only_current_horizon(call):
                continue

            if status and call.get("status") != status:
                continue

            calls.append(call)

        calls = _deduplicate_calls(calls)
        return calls[:max_results]

    except Exception:
        return []


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
                "title": clean_html(title),
                "description": clean_html(description),
                "keywords": meta.get("keywords", []),
                "deadline": meta.get("deadlineDate", ""),
                "action_type": meta.get("typesOfAction", []),
            }

    except Exception:
        return None

    return None


def detect_action_type_from_call(call_data: Dict) -> str:
    all_text = " ".join(
        call_data.get("action_types", [])
        + [
            call_data.get("title", ""),
            call_data.get("call_id", ""),
        ]
    ).upper()

    if "MSCA" in all_text:
        return "MSCA-DN"

    if "ERC" in all_text:
        return "ERC-StG"

    if "PATHFINDER" in all_text:
        return "EIC-Pathfinder-Open"

    if "ACCELERATOR" in all_text:
        return "EIC-Accelerator"

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
            f"\nKEYWORDS: {', '.join(str(keyword) for keyword in keywords[:15])}"
        )

    return "\n".join(parts)


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
                "Destination": call.get("destination", ""),
                "URL": call.get("url", ""),
                "Source": call.get("source", ""),
            }
        )

    output = BytesIO()

    pd.DataFrame(rows).to_excel(output, index=False, sheet_name="Horizon Calls")

    output.seek(0)

    return output.getvalue()


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
