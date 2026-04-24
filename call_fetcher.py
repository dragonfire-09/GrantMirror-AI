"""
GrantMirror-AI call fetcher
Sources:
- EC Funding & Tenders SEDIA API
- Euresearch Open Calls
- RSS backup signals
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

try:
    import feedparser
    HAS_FEEDPARSER = True
except Exception:
    HAS_FEEDPARSER = False


EC_API_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
EURESEARCH_URL = "https://www.euresearch.ch/en/our-services/inform/open-calls-137.html"

RSS_FEEDS = [
    "https://ec.europa.eu/info/funding-tenders/opportunities/data/feeds/rss.xml",
    "https://ec.europa.eu/info/funding-tenders/opportunities/data/feeds/atom.xml",
]


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

    for pattern in [
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
    ]:
        match = re.search(pattern, text)
        if match:
            raw = match.group(1)
            for fmt in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
                try:
                    return datetime.strptime(raw, fmt).date()
                except Exception:
                    pass
    return None


def _normalize_status(value):
    text = str(value).lower()

    if "31094501" in text or "open" in text:
        return "Open"
    if "31094502" in text or "forthcoming" in text or "planned" in text or "upcoming" in text:
        return "Forthcoming"
    if "31094503" in text or "closed" in text:
        return "Closed"

    return str(value) if value else "Unknown"


def _detect_action_types_from_text(text):
    t = str(text).upper()
    found = []

    if re.search(r"\bRIA\b|RESEARCH AND INNOVATION ACTION", t):
        found.append("RIA")
    if re.search(r"\bIA\b|INNOVATION ACTION", t) and "RIA" not in found:
        found.append("IA")
    if re.search(r"\bCSA\b|COORDINATION AND SUPPORT ACTION", t):
        found.append("CSA")
    if "MSCA" in t:
        found.append("MSCA-DN")
    if "EIC" in t and "ACCELERATOR" in t:
        found.append("EIC-Accelerator")
    elif "EIC" in t and "PATHFINDER" in t:
        found.append("EIC-Pathfinder-Open")
    if "ERC" in t:
        found.append("ERC-StG")

    return found or ["RIA"]


def _is_current_horizon(call):
    text = " ".join([
        str(call.get("call_id", "")),
        str(call.get("title", "")),
        str(call.get("programme", "")),
        str(call.get("status", "")),
    ]).upper()

    if "H2020" in text or "HORIZON 2020" in text:
        return False

    if any(y in text for y in ["2014", "2015", "2016", "2017", "2018", "2019", "2020"]):
        return False

    if call.get("status") == "Closed":
        return False

    deadline = _parse_date_safe(call.get("deadline"))
    if deadline and deadline < date.today():
        return False

    return True


def _deduplicate_calls(calls):
    seen = set()
    unique = []

    for c in calls:
        key = (
            str(c.get("call_id", "")).lower().strip(),
            str(c.get("title", ""))[:100].lower().strip(),
            str(c.get("deadline", "")),
        )
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique


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
        return [v.strip() for v in value.split(",") if v.strip()] if "," in value else [value]
    return [str(value)]


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

    selected_status = status_filter or status
    max_results = int(page_size or max_api_results or 100)
    max_results = min(max_results, 500)

    all_calls = []

    src_stats = {
        "success": True,
        "ec_api": 0,
        "euresearch": 0,
        "rss": 0,
        "ec_backup": 0,
        "ufukavrupa": 0,
        "local_db": 0,
        "total_calls": 0,
        "ec_debug": {},
    }

    if use_ec_api:
        ec_calls, ec_debug = fetch_ec_calls(
            programme=programme,
            status=selected_status,
            search_text=search_text,
            max_results=max_results,
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

    rss_calls = fetch_rss_calls(
        search_text=search_text,
        status=selected_status,
        max_results=max_results,
    )
    all_calls.extend(rss_calls)
    src_stats["rss"] = len(rss_calls)

    if src_stats["euresearch"] == 0 and search_text:
        backup_calls = fetch_ec_backup_calls(
            search_text=search_text,
            status=selected_status,
            max_results=max_results,
        )
        all_calls.extend(backup_calls)
        src_stats["ec_backup"] = len(backup_calls)

    filtered = []

    for call in all_calls:
        if not _is_current_horizon(call):
            continue

        if selected_status and call.get("status") != selected_status:
            continue

        if search_text:
            kw = search_text.lower()
            haystack = " ".join([
                call.get("call_id", ""),
                call.get("title", ""),
                call.get("description", ""),
                call.get("scope", ""),
                call.get("destination", ""),
                " ".join(call.get("keywords", [])),
            ]).lower()

            if kw not in haystack:
                continue

        filtered.append(call)

    filtered = _deduplicate_calls(filtered)
    filtered.sort(key=lambda c: _parse_date_safe(c.get("deadline")) or date(2999, 12, 31))
    filtered = filtered[:max_results]

    src_stats["total_calls"] = len(filtered)

    return filtered, src_stats


def fetch_ec_calls(programme="HORIZON", status="", search_text="", max_results=100):
    max_results = min(int(max_results or 100), 500)
    statuses = [status] if status else ["Open", "Forthcoming"]

    all_calls = []

    debug = {
        "success": False,
        "total_api": 0,
        "pages_fetched": 0,
        "winning_strategy": "ec_paginated",
        "attempts": [],
    }

    for st in statuses:
        query_parts = []

        if programme:
            query_parts.append(f"frameworkProgramme/{programme}")

        code = {
            "Open": "31094501",
            "Forthcoming": "31094502",
            "Closed": "31094503",
        }.get(st, "")

        if code:
            query_parts.append(f"status/code/{code}")

        if search_text:
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

        max_pages = max(1, (max_results + 99) // 100)
        raw_results = []

        for page_num in range(1, max_pages + 1):
            params["pageNumber"] = str(page_num)

            try:
                r = requests.get(
                    EC_API_URL,
                    params=params,
                    timeout=30,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "GrantMirror-AI/1.0",
                    },
                )

                attempt = {
                    "strategy": f"EC {st} page {page_num}",
                    "status": r.status_code,
                    "url": r.url,
                    "count": 0,
                    "total_results": "?",
                    "page1_count": "?",
                }

                if r.status_code != 200:
                    debug["attempts"].append(attempt)
                    continue

                data = r.json()
                results = data.get("results", [])

                if page_num == 1:
                    total_api = data.get("totalResults", len(results))
                    attempt["total_results"] = total_api
                    debug["total_api"] += int(total_api) if str(total_api).isdigit() else 0

                attempt["page1_count"] = len(results)
                attempt["count"] = len(results)
                debug["attempts"].append(attempt)

                if not results:
                    break

                raw_results.extend(results)
                debug["pages_fetched"] += 1

                if len(raw_results) >= max_results:
                    break

            except Exception as e:
                debug["attempts"].append({
                    "strategy": f"EC {st} page {page_num}",
                    "status": "error",
                    "error": str(e),
                    "count": 0,
                })

        for item in raw_results:
            parsed = _parse_ec_result(item)
            if parsed and _is_current_horizon(parsed):
                all_calls.append(parsed)

    all_calls = _deduplicate_calls(all_calls)[:max_results]
    debug["success"] = len(all_calls) > 0

    return all_calls, debug


def _parse_ec_result(item):
    try:
        meta = item.get("metadata", {}) or item

        def get(*keys, default=""):
            for k in keys:
                if k in meta and meta.get(k) not in [None, "", []]:
                    return _as_string(meta.get(k), default)
            return default

        def get_list(*keys):
            for k in keys:
                if k in meta and meta.get(k) not in [None, "", []]:
                    return _as_list(meta.get(k))
            return []

        call_id = get("identifier", "callIdentifier", "ccm2Id", "topicIdentifier")
        title = get("title", "callTitle", "topicTitle")

        if not call_id and not title:
            return None

        deadline_raw = get("deadlineDate", "deadlineDates", "deadline", "endDate")
        deadline_date = _parse_date_safe(deadline_raw)

        deadline = deadline_date.isoformat() if deadline_date else str(deadline_raw or "N/A")[:20]

        topic_ids = get_list("topicIdentifier", "topicId", "identifier")
        topic_titles = get_list("topicTitle", "title")

        topics = []
        for i, topic_id in enumerate(topic_ids):
            topics.append({
                "topic_id": str(topic_id),
                "title": str(topic_titles[i] if i < len(topic_titles) else topic_id),
            })

        action_types = get_list("typesOfAction", "typeOfAction", "actionType", "fundingScheme")
        if not action_types:
            action_types = _detect_action_types_from_text(f"{call_id} {title}")

        url = get("url", "link")
        if not url:
            clean_id = str(topic_ids[0] if topic_ids else call_id).split(",")[0].strip()
            url = (
                "https://ec.europa.eu/info/funding-tenders/opportunities/"
                f"portal/screen/opportunities/topic-details/{clean_id}"
            )

        desc = clean_html(get("description", "shortDescription"))
        destination = clean_html(get("destination", "destinationTitle"))

        return {
            "call_id": call_id or "N/A",
            "title": clean_html(title) or "N/A",
            "status": _normalize_status(get("status", "callStatus", "sortStatus")),
            "programme": get("frameworkProgramme", "programme", "programmePeriod", default="HORIZON"),
            "opening_date": get("startDate", "openingDate"),
            "deadline": deadline,
            "budget": get("budget", "callBudget", "budgetOverall", default="N/A"),
            "budget_total": get("budget", "callBudget", "budgetOverall", default=""),
            "budget_per_project": "",
            "action_types": action_types,
            "topics": topics,
            "keywords": get_list("keywords", "tags"),
            "destination": destination,
            "description": desc,
            "scope": desc,
            "expected_outcomes": "",
            "url": url,
            "link": url,
            "raw": item,
            "source": "EC API",
        }

    except Exception:
        return None


def fetch_euresearch_calls(search_text="", status="", max_results=100):
    if not HAS_BS4:
        return []

    try:
        params = {}
        if search_text:
            params["filter_search"] = search_text
            params["filter_submit"] = "Filter"

        r = requests.get(
            EURESEARCH_URL,
            params=params,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0 GrantMirror-AI/1.0",
                "Accept": "text/html",
            },
        )

        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, "html.parser")

        calls = []
        current_destination = ""

        for el in soup.find_all(["h2", "h3", "h4", "tr", "li", "article", "div"]):
            text = clean_html(el.get_text(" ", strip=True))

            if not text:
                continue

            if el.name in ["h2", "h3", "h4"]:
                if text.lower() not in ["open calls", "filter options", "horizon europe"]:
                    current_destination = text[:150]
                continue

            if not re.search(r"HORIZON-|EIC-|ERC-|MSCA-", text):
                continue

            m = re.search(
                r"(HORIZON-[A-Z0-9\-]+|EIC-[A-Z0-9\-]+|ERC-[A-Z0-9\-]+|MSCA-[A-Z0-9\-]+)",
                text,
            )

            if not m:
                continue

            call_id = m.group(1)
            title = text.replace(call_id, "").strip(" -–|")

            deadline_date = _parse_date_safe(text)
            deadline = deadline_date.isoformat() if deadline_date else "N/A"

            link = EURESEARCH_URL
            a = el.find("a", href=True)
            if a:
                href = a.get("href")
                link = href if href.startswith("http") else "https://www.euresearch.ch" + href

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
                "action_types": _detect_action_types_from_text(text),
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

            if _is_current_horizon(call):
                calls.append(call)

        return _deduplicate_calls(calls)[:max_results]

    except Exception:
        return []


def fetch_rss_calls(search_text="", status="", max_results=100):
    if not HAS_FEEDPARSER:
        return []

    calls = []

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:max_results]:
                title = clean_html(entry.get("title", ""))
                summary = clean_html(entry.get("summary", ""))
                link = entry.get("link", feed_url)

                text = f"{title} {summary}"

                if not re.search(r"HORIZON-|EIC-|ERC-|MSCA-", text):
                    continue

                m = re.search(
                    r"(HORIZON-[A-Z0-9\-]+|EIC-[A-Z0-9\-]+|ERC-[A-Z0-9\-]+|MSCA-[A-Z0-9\-]+)",
                    text,
                )

                if not m:
                    continue

                call_id = m.group(1)

                call = {
                    "call_id": call_id,
                    "title": title or call_id,
                    "status": "Open",
                    "programme": "HORIZON",
                    "opening_date": "",
                    "deadline": "N/A",
                    "budget": "",
                    "budget_total": "",
                    "budget_per_project": "",
                    "action_types": _detect_action_types_from_text(text),
                    "topics": [{"topic_id": call_id, "title": title or call_id}],
                    "keywords": [],
                    "destination": "",
                    "description": summary,
                    "scope": summary,
                    "expected_outcomes": "",
                    "url": link,
                    "link": link,
                    "raw": {},
                    "source": "RSS",
                }

                if _is_current_horizon(call):
                    calls.append(call)

        except Exception:
            continue

    return _deduplicate_calls(calls)[:max_results]


def fetch_ec_backup_calls(search_text="", status="", max_results=100):
    query = f"Horizon Europe {search_text}".strip()

    params = {
        "apiKey": "SEDIA",
        "text": query,
        "type": "1",
        "pageSize": str(min(max_results, 100)),
        "pageNumber": "1",
        "sort": "deadlineDate asc",
    }

    try:
        r = requests.get(
            EC_API_URL,
            params=params,
            timeout=30,
            headers={
                "Accept": "application/json",
                "User-Agent": "GrantMirror-AI/1.0",
            },
        )

        if r.status_code != 200:
            return []

        data = r.json()
        results = data.get("results", [])

        calls = []

        for item in results:
            parsed = _parse_ec_result(item)
            if parsed and _is_current_horizon(parsed):
                parsed["source"] = "EC Backup Search"
                calls.append(parsed)

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
        r = requests.get(EC_API_URL, params=params, timeout=20)
        if r.status_code != 200:
            return None

        data = r.json()
        for result in data.get("results", []):
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
                "title": clean_html(title),
                "description": clean_html(desc),
                "keywords": meta.get("keywords", []),
                "deadline": meta.get("deadlineDate", ""),
                "action_type": meta.get("typesOfAction", []),
            }

    except Exception:
        return None

    return None


def detect_action_type_from_call(call_data: Dict) -> str:
    text = " ".join(
        call_data.get("action_types", [])
        + [call_data.get("title", ""), call_data.get("call_id", "")]
    ).upper()

    if "MSCA" in text:
        return "MSCA-DN"
    if "ERC" in text:
        return "ERC-StG"
    if "PATHFINDER" in text:
        return "EIC-Pathfinder-Open"
    if "ACCELERATOR" in text:
        return "EIC-Accelerator"
    if "CSA" in text:
        return "CSA"
    if "RIA" in text:
        return "RIA"
    if re.search(r"\bIA\b", text):
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

    if ctx.get("expected_outcomes"):
        parts.append("\nEXPECTED OUTCOMES:")
        for i, o in enumerate(ctx["expected_outcomes"], 1):
            parts.append(f"  {i}. {o}")

    if ctx.get("topic_keywords"):
        parts.append(f"\nKEYWORDS: {', '.join(str(k) for k in ctx['topic_keywords'][:15])}")

    return "\n".join(parts)


def calls_to_excel_bytes(calls: List[Dict]) -> bytes:
    import pandas as pd
    from io import BytesIO

    rows = []

    for c in calls:
        rows.append({
            "Call ID": c.get("call_id", ""),
            "Title": c.get("title", ""),
            "Status": c.get("status", ""),
            "Programme": c.get("programme", ""),
            "Opening Date": c.get("opening_date", ""),
            "Deadline": c.get("deadline", ""),
            "Budget": c.get("budget", ""),
            "Action Types": ", ".join(c.get("action_types", [])),
            "Topics": ", ".join(t.get("topic_id", "") for t in c.get("topics", [])),
            "Destination": c.get("destination", ""),
            "URL": c.get("url", ""),
            "Source": c.get("source", ""),
        })

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
            value, ts = self._cache[key]
            if time.time() - ts < self._ttl:
                return value
            del self._cache[key]
        return None

    def set(self, key, value):
        self._cache[key] = (value, time.time())

    def clear(self):
        self._cache.clear()
