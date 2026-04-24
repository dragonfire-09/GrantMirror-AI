"""
De-identification module for blind evaluation compliance.
Scans proposal text for identity-revealing information.
"""
import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class IdentitySignal:
    signal_type: str  # "institution", "person", "self_reference", "logo_hint", "project_ref"
    text_found: str
    location: str  # approximate location description
    severity: str  # "high", "medium", "low"
    recommendation: str


def scan_for_identity_signals(
    text: str,
    partner_names: Optional[List[str]] = None,
    person_names: Optional[List[str]] = None,
) -> List[IdentitySignal]:
    """Scan text for identity-revealing information relevant to blind evaluation."""
    signals = []

    # 1. Self-referencing language
    self_ref_patterns = [
        (r"(?i)\b(?:our|we)\s+(?:have|had|previously|already|recently)\s+(?:developed|shown|demonstrated|proved|published|designed|built|created|implemented)",
         "Self-referencing past work"),
        (r"(?i)\b(?:in\s+our\s+(?:previous|earlier|recent|prior)\s+(?:work|project|study|research|publication))",
         "Reference to own prior work"),
        (r"(?i)\b(?:as\s+(?:PI|coordinator|partner|leader|WP\s*lead)\s+(?:of|in|for))",
         "Role self-identification"),
        (r"(?i)\b(?:our\s+(?:lab|laboratory|group|team|department|institute|centre|center)\s+(?:has|is|was|at))",
         "Lab/group identification"),
        (r"(?i)\b(?:we\s+(?:are|were)\s+(?:the\s+)?(?:first|only|leading|pioneering))",
         "Self-promotional claim"),
    ]

    for pattern, desc in self_ref_patterns:
        for m in re.finditer(pattern, text):
            context_start = max(0, m.start() - 30)
            context_end = min(len(text), m.end() + 50)
            signals.append(IdentitySignal(
                signal_type="self_reference",
                text_found=text[context_start:context_end].strip(),
                location=f"Character position ~{m.start()}",
                severity="medium",
                recommendation=f"Rephrase to remove self-identification: '{desc}'",
            ))

    # 2. Known partner/institution names
    if partner_names:
        for name in partner_names:
            if len(name) < 3:
                continue
            escaped = re.escape(name)
            for m in re.finditer(escaped, text, re.IGNORECASE):
                signals.append(IdentitySignal(
                    signal_type="institution",
                    text_found=name,
                    location=f"Character position ~{m.start()}",
                    severity="high",
                    recommendation=f"Remove or anonymize institution name '{name}' for blind evaluation.",
                ))

    # 3. Person names
    if person_names:
        for name in person_names:
            if len(name) < 4:
                continue
            escaped = re.escape(name)
            for m in re.finditer(escaped, text):
                signals.append(IdentitySignal(
                    signal_type="person",
                    text_found=name,
                    location=f"Character position ~{m.start()}",
                    severity="high",
                    recommendation=f"Remove person name '{name}' for blind evaluation.",
                ))

    # 4. Grant/project number references that could identify
    project_ref_patterns = [
        r"(?i)\b(?:grant\s+(?:agreement\s+)?(?:no\.?|number|#)\s*[\d]{5,})",
        r"(?i)\b(?:project\s+(?:no\.?|number|#|ID)\s*[\d]{5,})",
        r"(?i)\b(?:H2020|FP7|Horizon\s+2020|Horizon\s+Europe)[-\s]+\d{5,}",
        r"(?i)\b(?:GA\s*\d{6,})",
    ]
    for pattern in project_ref_patterns:
        for m in re.finditer(pattern, text):
            signals.append(IdentitySignal(
                signal_type="project_ref",
                text_found=m.group(0),
                location=f"Character position ~{m.start()}",
                severity="high",
                recommendation="Remove specific grant/project number references for blind evaluation.",
            ))

    # 5. URL/website that identifies institution
    url_patterns = [
        r"(?:https?://)?(?:www\.)?[\w\-]+\.(?:edu|ac\.[\w]{2}|uni[\w\-]*\.[\w]{2,})",
        r"(?:https?://)?[\w\-]+\.(?:org|eu|com)/[\w\-/]*",
    ]
    for pattern in url_patterns:
        for m in re.finditer(pattern, text):
            signals.append(IdentitySignal(
                signal_type="institution",
                text_found=m.group(0),
                location=f"Character position ~{m.start()}",
                severity="medium",
                recommendation="URLs may reveal institution identity. Consider removing for blind evaluation.",
            ))

    # Deduplicate by text_found
    seen = set()
    unique_signals = []
    for s in signals:
        key = (s.signal_type, s.text_found)
        if key not in seen:
            seen.add(key)
            unique_signals.append(s)

    return unique_signals


def generate_deidentification_report(signals: List[IdentitySignal]) -> str:
    """Generate a human-readable de-identification report."""
    if not signals:
        return "✅ No identity-revealing information detected."

    high = [s for s in signals if s.severity == "high"]
    medium = [s for s in signals if s.severity == "medium"]
    low = [s for s in signals if s.severity == "low"]

    lines = [f"🔍 **De-identification Scan Results**: {len(signals)} signal(s) found\n"]

    if high:
        lines.append(f"### 🔴 High Severity ({len(high)})")
        for s in high:
            lines.append(f"- **{s.signal_type}**: `{s.text_found}`")
            lines.append(f"  → {s.recommendation}")
        lines.append("")

    if medium:
        lines.append(f"### 🟡 Medium Severity ({len(medium)})")
        for s in medium:
            lines.append(f"- **{s.signal_type}**: `{s.text_found}`")
            lines.append(f"  → {s.recommendation}")
        lines.append("")

    if low:
        lines.append(f"### 🟢 Low Severity ({len(low)})")
        for s in low:
            lines.append(f"- **{s.signal_type}**: `{s.text_found}`")

    return "\n".join(lines)
