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
        if match:
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
    text = " ".join([
        str(call.get("call_id", "")),
        str(call.get("title", "")),
        str(call.get("programme", "")),
        str(call.get("status", "")),
        " ".join(str(t.get("topic_id", "")) for t in call.get("topics", [])),
    ]).upper()

    if "H2020" in text or "HORIZON 2020" in text:
        return False

    if any(y in text for y in ["2014", "2015", "2016", "2017", "2018", "2019", "2020"]):
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
    Compatible with app.py old and new signatures.
    Returns:
    - calls
    - src_stats dict
    """

    selected_status = status_filter or status
    max_results = int(max_api_results or page_size or 100)

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
        eur_calls = fetch_euresearch_calls(
            search_text=search_text,
            status=selected_status,
            max_results=max_results,
        )
        all_calls.extend(eur_calls)
        src_stats["euresearch"] = len(eur_calls)

    filtered = []
    for call in all_calls:
        if not _keep_only_current_horizon(call):
            continue

        if selected_status:
            if call.get("status") != selected_status:
                continue

        if search_text:
            kw = search_text.lower()
            haystack = " ".join([
                call.get("call_id", ""),
                call.get("title", ""),
                call.get("description", ""),
                call.get("scope", ""),
                " ".join(call.get("keywords", [])),
            ]).lower()
            if kw not in haystack:
                continue

        filtered.append(call)

    filtered = _deduplicate_calls(filtered)
    filtered.sort(key=lambda c: _parse_date_safe(c.get("deadline")) or date(2999, 12, 31))

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
    statuses = [status] if status else ["Open", "Forthcoming"]
    all_calls = []

    debug = {
        "success": False,
        "total_api": 0,
        "pages_fetched": 0,
        "winning_strategy": "ec_get_query",
        "attempts": [],
    }

    for st in statuses:
        query_parts = []

        if programme:
            query_parts.append(f"frameworkProgramme/{programme}")

        status_code = {
            "Open": "31094501",
            "Forthcoming": "31094502",
            "Closed": "31094503",
        }.get(st, "")

        if status_code:
            query_parts.append(f"status/code/{status_code}")

        if search_text:
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
                "strategy": f"ec_get_{st}",
                "status": response.status_code,
                "url": response.url,
                "count": 0,
                "total_results": "?",
                "page1_count": "?",
            }

            if response.status_code != 200:
                debug["attempts"].append(attempt)
                continue

            
            all_results = []
            total_results = 0

max_pages = max(1, int(page_size / 100))

for page_num in range(1, max_pages + 1):
    params["pageNumber"] = str(page_num)

    response = requests.get(
        EC_API_URL,
        params=params,
        timeout=30,
        headers={
            "Accept": "application/json",
            "User-Agent": "GrantMirror-AI/1.0",
        },
    )

    if response.status_code != 200:
        continue

    data = response.json()
    results = data.get("results", [])

    if page_num == 1:
        total_results = data.get("totalResults", len(results))

    if not results:
        break

    all_results.extend(results)

    if len(all_results) >= page_size:
        break

            attempt["total_results"] = total_results
            attempt["page1_count"] = len(results)

            calls = []
            for item in all_results:
                parsed = _parse_ec_result(item)
                if parsed and _keep_only_current_horizon(parsed):
                    calls.append(parsed)
                    
            calls = calls[:page_size]

            attempt["count"] = len(calls)
            debug["attempts"].append(attempt)
            debug["total_api"] += int(total_results) if str(total_results).isdigit() else 0
            debug["pages_fetched"] += 1

            all_calls.extend(calls)

        except Exception as e:
            debug["attempts"].append({
                "strategy": f"ec_get_{st}",
                "status": "error",
                "error": str(e),
                "count": 0,
            })

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

        status = _normalize_status(get("status", "callStatus", "sortStatus"))
        deadline_raw = get("deadlineDate", "deadlineDates", "deadline", "endDate")
        deadline_date = _parse_date_safe(deadline_raw)
        deadline = deadline_date.isoformat() if deadline_date else str(deadline_raw or "N/A")[:20]

        opening = get("startDate", "openingDate")
        budget = get("budget", "callBudget", "budgetOverall", default="N/A")

        action_types = get_list("typesOfAction", "typeOfAction", "actionType", "fundingScheme")
        if not action_types:
            action_types = _detect_action_types_from_text(f"{call_id} {title}")

        topic_ids = get_list("topicIdentifier", "topicId", "identifier")
        topic_titles = get_list("topicTitle", "title")

        topics = []
        for i, tid in enumerate(topic_ids):
            topics.append({
                "topic_id": str(tid),
                "title": str(topic_titles[i] if i < len(topic_titles) else tid),
            })

        keywords = get_list("keywords", "tags")
        programme_value = " / ".join(get_list("programmePeriod", "programme")) or get(
            "frameworkProgramme",
            default="HORIZON",
        )

        url = get("url", "link")
        if not url and topic_ids:
            clean_topic = str(topic_ids[0]).split(",")[0].strip()
            url = (
                "https://ec.europa.eu/info/funding-tenders/opportunities/"
                f"portal/screen/opportunities/topic-details/{clean_topic}"
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
            "destination": "",
            "description": "",
            "scope": "",
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

        # Başlıkları destination/category olarak yakala
        for element in soup.find_all(["h2", "h3", "h4", "tr"]):
            tag_name = element.name

            if tag_name in ["h2", "h3", "h4"]:
                heading = clean_html(element.get_text(" ", strip=True))
                if heading and heading.lower() not in [
                    "open calls",
                    "filter options",
                    "horizon europe",
                ]:
                    current_destination = heading
                continue

            if tag_name == "tr":
                cells = [
                    clean_html(td.get_text(" ", strip=True))
                    for td in element.find_all(["td", "th"])
                ]

                if len(cells) < 3:
                    continue

                first = cells[0]
                opening = cells[1]
                deadline = cells[2]

                if not re.search(r"HORIZON-|EIC-|ERC-|MSCA-", first):
                    continue

                call_id_match = re.search(
                    r"(HORIZON-[A-Z0-9\-]+|EIC-[A-Z0-9\-]+|ERC-[A-Z0-9\-]+|MSCA-[A-Z0-9\-]+)",
                    first,
                )

                if not call_id_match:
                    continue

                call_id = call_id_match.group(1)
                title = first.replace(call_id, "").strip(" -–|")

                deadline_date = _parse_date_safe(deadline)
                opening_date = _parse_date_safe(opening)

                deadline_clean = (
                    deadline_date.isoformat() if deadline_date else deadline
                )

                opening_clean = (
                    opening_date.isoformat() if opening_date else opening
                )

                action_types = _detect_action_types_from_text(first)

                link = EURESEARCH_URL
                a = element.find("a", href=True)
                if a:
                    href = a.get("href")
                    if href.startswith("http"):
                        link = href
                    else:
                        link = "https://www.euresearch.ch" + href

                call = {
                    "call_id": call_id,
                    "title": title or call_id,
                    "status": "Open",
                    "programme": "HORIZON",
                    "opening_date": opening_clean,
                    "deadline": deadline_clean,
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

        return _deduplicate_calls(calls)[:max_results]

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

            desc = meta.get("description", "")
            if isinstance(desc, list):
                desc = desc[0] if desc else ""

            title = meta.get("title", "")
            if isinstance(title, list):
                title = title[0] if title else ""

            return {
                "topic_id": topic_id,
                "title": title,
                "description": desc,
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


def build_call_specific_criteria(call_data: Dict, topic_details: Optional[Dict] = None) -> Dict:
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
        for i, outcome in enumerate(outcomes, 1):
            parts.append(f"  {i}. {outcome}")

    keywords = ctx.get("topic_keywords", [])
    if keywords:
        parts.append(f"\nKEYWORDS: {', '.join(str(k) for k in keywords[:15])}")

    return "\n".join(parts)


def calls_to_excel_bytes(calls: List[Dict]) -> bytes:
    import pandas as pd
    from io import BytesIO

    rows = []

    for call in calls:
        rows.append({
            "Call ID": call.get("call_id", ""),
            "Title": call.get("title", ""),
            "Status": call.get("status", ""),
            "Programme": call.get("programme", ""),
            "Opening Date": call.get("opening_date", ""),
            "Deadline": call.get("deadline", ""),
            "Budget": call.get("budget", ""),
            "Action Types": ", ".join(call.get("action_types", [])),
            "Topics": ", ".join(t.get("topic_id", "") for t in call.get("topics", [])),
            "Destination": call.get("destination", ""),
            "URL": call.get("url", ""),
            "Source": call.get("source", ""),
        })

    df = pd.DataFrame(rows)
    output = BytesIO()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Horizon Calls")
        workbook = writer.book
        worksheet = writer.sheets["Horizon Calls"]

        header_format = workbook.add_format({
            "bold": True,
            "bg_color": "#101828",
            "font_color": "white",
            "border": 1,
        })

        for col_num, value in enumerate(df.columns):
            worksheet.write(0, col_num, value, header_format)
            worksheet.set_column(col_num, col_num, 26)

        worksheet.freeze_panes(1, 0)
        worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)

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
