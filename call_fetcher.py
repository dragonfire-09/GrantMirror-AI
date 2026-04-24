"""
GrantMirror-AI: Horizon Europe Call Fetcher
Live EC Funding & Tenders API integration with pagination and Excel export.
"""
import requests
import time
import io
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime

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
    """
    Fetch calls from EC API with pagination support.
    If fetch_all=True, fetches multiple pages up to max_pages.
    """
    all_calls = []
    total_count = 0

    for current_page in range(page_num, page_num + max_pages):
        params = {
            "apiKey": "SEDIA",
            "text": search_text or "*",
            "type": "1",  # calls
            "pageSize": str(min(page_size, 100)),
            "pageNumber": str(current_page),
        }

        # Build query filters
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
        except Exception as e:
            print(f"EC API error (page {current_page}): {e}")
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

        # Stop if we have all results or not fetching all
        if not fetch_all or len(all_calls) >= total_count:
            break

        # Be nice to the API
        time.sleep(0.3)

    # Deduplicate by call_id
    seen = set()
    unique_calls = []
    for c in all_calls:
        cid = c.get("call_id", "")
        if cid and cid not in seen:
            seen.add(cid)
            unique_calls.append(c)

    return unique_calls, total_count


def _parse_call_metadata(meta: Dict) -> Optional[Dict]:
    """Parse EC API metadata into our call format."""
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

        deadline = _extract_field(meta, "deadlineDate") or ""
        if not deadline:
            deadline = _extract_field(meta, "plannedClosingDate") or ""

        # Parse action types
        action_types = []
        at_raw = _extract_field(meta, "typesOfAction")
        if at_raw:
            if isinstance(at_raw, list):
                action_types = at_raw
            else:
                action_types = [s.strip() for s in str(at_raw).split(",")]

        if not action_types:
            action_types = _detect_action_types_from_text(call_id or "", title or "")

        # Parse topics
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
        }
    except Exception:
        return None


def _extract_field(meta: Dict, key: str) -> Optional[str]:
    """Extract a field from EC API metadata (handles nested structures)."""
    if key in meta:
        val = meta[key]
        if isinstance(val, list) and val:
            if isinstance(val[0], dict):
                return val[0].get("value", str(val[0]))
            return str(val[0])
        return str(val) if val else None
    return None


def _detect_action_types_from_text(call_id: str, title: str) -> List[str]:
    """Detect action types from call ID or title."""
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


def fetch_topic_details(topic_id: str) -> Optional[Dict]:
    """Fetch detailed topic information from EC API."""
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
        results = data.get("results", [])

        for item in results:
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


def detect_action_type_from_call(call_data: Dict) -> str:
    """Detect action type from call data."""
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
    """Build evaluation context from call + topic data."""
    context_parts = [
        f"Call: {call_data.get('call_id', 'N/A')}",
        f"Title: {call_data.get('title', 'N/A')}",
        f"Action Types: {', '.join(call_data.get('action_types', []))}",
        f"Deadline: {call_data.get('deadline', 'N/A')}",
    ]

    if call_data.get("description"):
        context_parts.append(f"\nCall Description:\n{call_data['description'][:2000]}")

    if topic_details:
        if topic_details.get("description"):
            context_parts.append(f"\nTopic Description:\n{topic_details['description'][:3000]}")
        if topic_details.get("conditions"):
            context_parts.append(f"\nConditions:\n{topic_details['conditions'][:1000]}")

    action_type = detect_action_type_from_call(call_data)

    return {
        "action_type": action_type,
        "evaluation_context": "\n".join(context_parts),
        "call_id": call_data.get("call_id", ""),
        "deadline": call_data.get("deadline", ""),
    }


def calls_to_excel_bytes(calls: List[Dict]) -> bytes:
    """Convert calls list to Excel bytes for download."""
    if HAS_OPENPYXL:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Horizon Calls"

        # Header
        headers = [
            "Call ID", "Title", "Status", "Deadline",
            "Action Types", "Destination", "Budget",
            "Expected Outcomes", "Scope", "Keywords",
        ]
        ws.append(headers)

        # Style header
        from openpyxl.styles import Font, PatternFill, Alignment
        header_font = Font(bold=True, color="FFFFFF", size=11)
        header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
        for col_idx, cell in enumerate(ws[1], 1):
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        # Data rows
        for call in calls:
            ws.append([
                call.get("call_id", ""),
                call.get("title", ""),
                call.get("status", ""),
                call.get("deadline", ""),
                ", ".join(call.get("action_types", [])),
                call.get("destination", ""),
                call.get("budget_per_project", call.get("budget_total", "")),
                call.get("expected_outcomes", ""),
                call.get("scope", ""),
                ", ".join(call.get("keywords", [])),
            ])

        # Auto-width
        for col in ws.columns:
            max_length = 0
            col_letter = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except Exception:
                    pass
            ws.column_dimensions[col_letter].width = min(max_length + 2, 50)

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    else:
        # Fallback: CSV as bytes
        import csv
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Call ID", "Title", "Status", "Deadline", "Action Types"])
        for call in calls:
            writer.writerow([
                call.get("call_id", ""),
                call.get("title", ""),
                call.get("status", ""),
                call.get("deadline", ""),
                ", ".join(call.get("action_types", [])),
            ])
        return buf.getvalue().encode("utf-8")
