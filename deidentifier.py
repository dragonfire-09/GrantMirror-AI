"""
De-identification scanner for blind evaluation compliance.
"""
import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class IdentitySignal:
    signal_type: str
    text_found: str
    severity: str
    recommendation: str


def scan_for_identity_signals(
    text: str,
    partner_names: Optional[List[str]] = None,
    person_names: Optional[List[str]] = None,
) -> List[IdentitySignal]:
    signals: List[IdentitySignal] = []

    # Self-referencing
    self_patterns = [
        (r"(?i)\b(?:our|we)\s+(?:have|had|previously|already|recently)\s+(?:developed|shown|demonstrated|published)", "Self-referencing past work"),
        (r"(?i)\bin\s+our\s+(?:previous|earlier|recent)\s+(?:work|project|study)", "Own prior work reference"),
        (r"(?i)\bas\s+(?:PI|coordinator|partner|WP\s*lead)\s+(?:of|in)", "Role self-identification"),
        (r"(?i)\bour\s+(?:lab|laboratory|group|team|department|institute)", "Lab/group identification"),
    ]
    for pattern, desc in self_patterns:
        for m in re.finditer(pattern, text[:10000]):
            signals.append(IdentitySignal("self_reference", m.group(0)[:80], "medium",
                                          f"Öz-referans ifadesi kaldırılmalı: {desc}"))

    # Partner names
    if partner_names:
        for name in partner_names:
            if len(name) >= 4 and name.lower() in text.lower():
                signals.append(IdentitySignal("institution", name, "high",
                                              f"Kurum adı '{name}' kör değerlendirmede kaldırılmalı."))

    # Person names
    if person_names:
        for name in person_names:
            if len(name) >= 4 and name in text:
                signals.append(IdentitySignal("person", name, "high",
                                              f"Kişi adı '{name}' kör değerlendirmede kaldırılmalı."))

    # Grant numbers
    for m in re.finditer(r"(?i)(?:grant|GA|project)\s*(?:no\.?|number|#|ID)\s*[\d]{5,}", text):
        signals.append(IdentitySignal("project_ref", m.group(0), "high",
                                      "Proje/hibe numarası kör değerlendirmede kaldırılmalı."))

    # Deduplicate
    seen = set()
    unique = []
    for s in signals:
        key = (s.signal_type, s.text_found)
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


def generate_deidentification_report(signals: List[IdentitySignal]) -> str:
    if not signals:
        return "✅ Kimlik ifşa eden bilgi tespit edilmedi."

    high = [s for s in signals if s.severity == "high"]
    medium = [s for s in signals if s.severity == "medium"]

    lines = [f"🔍 **Kimlik Tarama Sonuçları**: {len(signals)} sinyal bulundu\n"]
    if high:
        lines.append(f"### 🔴 Yüksek Önem ({len(high)})")
        for s in high:
            lines.append(f"- **{s.signal_type}**: `{s.text_found[:60]}`\n  → {s.recommendation}")
    if medium:
        lines.append(f"\n### 🟡 Orta Önem ({len(medium)})")
        for s in medium:
            lines.append(f"- **{s.signal_type}**: `{s.text_found[:60]}`\n  → {s.recommendation}")
    return "\n".join(lines)
