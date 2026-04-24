"""
Deterministic eligibility and admissibility checker.
Runs BEFORE LLM — fast, rule-based, no hallucination risk.
"""
import re
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

from config import ActionType, ActionTypeConfig, ACTION_TYPE_CONFIGS
from document_parser import ParsedProposal, SectionType


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    INFO = "info"
    UNABLE = "unable"


@dataclass
class CheckResult:
    check_name: str
    status: CheckStatus
    message: str
    details: Optional[str] = None


@dataclass
class EligibilityReport:
    action_type: ActionType
    results: List[CheckResult]
    is_admissible: bool
    is_eligible: bool
    critical_failures: List[str]
    warnings: List[str]


def _check_page_limit(proposal: ParsedProposal, config: ActionTypeConfig, stage: str = "full") -> CheckResult:
    limit = config.page_limit_full if stage == "full" else config.page_limit_stage1
    if limit is None:
        return CheckResult("Page Limit", CheckStatus.INFO,
                           f"No specific page limit for {config.action_type.value} {stage}")

    pages = proposal.total_pages
    if pages > limit:
        return CheckResult("Page Limit", CheckStatus.FAIL,
                           f"Teklif {pages} sayfa; limit {limit}. Fazla sayfalar değerlendirmede dikkate alınmaz.",
                           f"Tespit: {pages}, Limit: {limit}")
    elif pages > limit * 0.95:
        return CheckResult("Page Limit", CheckStatus.WARNING,
                           f"Teklif {pages} sayfa — {limit} sayfa limitine çok yakın.")
    else:
        return CheckResult("Page Limit", CheckStatus.PASS,
                           f"Teklif {pages} sayfa (limit: {limit}).")


def _check_required_sections(proposal: ParsedProposal, config: ActionTypeConfig) -> List[CheckResult]:
    results: List[CheckResult] = []
    required = [
        (SectionType.EXCELLENCE, "Excellence"),
        (SectionType.IMPACT, "Impact"),
        (SectionType.IMPLEMENTATION, "Quality and Efficiency of Implementation"),
    ]

    for sec_type, label in required:
        if sec_type in proposal.sections:
            wc = proposal.sections[sec_type].word_count
            if wc < 100:
                results.append(CheckResult(f"Section: {label}", CheckStatus.WARNING,
                                           f"'{label}' bölümü tespit edildi ama çok kısa ({wc} kelime)."))
            else:
                results.append(CheckResult(f"Section: {label}", CheckStatus.PASS,
                                           f"'{label}' bölümü bulundu ({wc} kelime)."))
        else:
            results.append(CheckResult(f"Section: {label}", CheckStatus.FAIL,
                                       f"'{label}' bölümü TESPİT EDİLEMEDİ. Bu bölüm zorunludur."))

    # Cross-cutting
    for keyword, label in [("open science", "Open Science"), ("gender dimension", "Gender Dimension"),
                           ("dissemination", "Dissemination & Exploitation"), ("risk", "Risk Management")]:
        found = keyword.lower() in proposal.full_text.lower()
        if found:
            results.append(CheckResult(f"Cross-cutting: {label}", CheckStatus.PASS,
                                       f"'{label}' içeriği metinde tespit edildi."))
        else:
            results.append(CheckResult(f"Cross-cutting: {label}", CheckStatus.WARNING,
                                       f"'{label}' içeriği metinde net tespit edilemedi."))

    return results


def _check_consortium(proposal: ParsedProposal, config: ActionTypeConfig) -> CheckResult:
    count = len(proposal.partner_names)
    if count == 0:
        return CheckResult("Consortium Size", CheckStatus.UNABLE,
                           f"Partner adları otomatik tespit edilemedi. Minimum: {config.min_consortium_size} kuruluş.")
    if count < config.min_consortium_size:
        return CheckResult("Consortium Size", CheckStatus.WARNING,
                           f"{count} potansiyel partner tespit edildi; minimum {config.min_consortium_size}.")
    return CheckResult("Consortium Size", CheckStatus.PASS,
                       f"{count} potansiyel partner tespit edildi (min: {config.min_consortium_size}).")


def _check_blind_eval(proposal: ParsedProposal, config: ActionTypeConfig) -> CheckResult:
    if not config.blind_evaluation:
        return CheckResult("Blind Evaluation", CheckStatus.INFO,
                           "Bu aksiyon türü için kör değerlendirme gerekli değil.")

    signals: List[str] = []
    if proposal.partner_names:
        signals.append(f"Kurum adları tespit edildi: {', '.join(proposal.partner_names[:3])}")
    if proposal.person_names:
        signals.append(f"Kişi adları tespit edildi: {', '.join(proposal.person_names[:3])}")

    self_ref_patterns = [
        r"(?i)(?:our|we)\s+(?:have|previously|already)\s+(?:developed|shown|demonstrated|published)",
        r"(?i)in\s+our\s+(?:previous|earlier)\s+(?:work|project|study)",
        r"(?i)as\s+(?:PI|coordinator|partner)\s+(?:of|in)",
    ]
    for pattern in self_ref_patterns:
        matches = re.findall(pattern, proposal.full_text[:5000])
        if matches:
            signals.append(f"Öz-referans dili tespit edildi: '{matches[0]}'")

    if signals:
        return CheckResult("Blind Evaluation", CheckStatus.WARNING,
                           "Kör değerlendirmede kimlik ifşa edebilecek bilgiler tespit edildi.",
                           "\n".join(f"• {s}" for s in signals))

    return CheckResult("Blind Evaluation", CheckStatus.PASS,
                       "Belirgin kimlik ifşa eden bilgi tespit edilmedi.")


def _check_trl(proposal: ParsedProposal) -> CheckResult:
    if not proposal.trl_mentions:
        return CheckResult("TRL Consistency", CheckStatus.WARNING,
                           "TRL referansı tespit edilemedi. Geçerliyse TRL giriş/çıkış belirtilmeli.")
    ranges = [m for m in proposal.trl_mentions if m.get("type") == "range"]
    if ranges:
        starts = set(m["start_trl"] for m in ranges)
        ends = set(m["end_trl"] for m in ranges)
        if len(starts) > 1 or len(ends) > 1:
            return CheckResult("TRL Consistency", CheckStatus.WARNING,
                               f"Birden fazla farklı TRL aralığı bulundu: başlangıç={starts}, bitiş={ends}.")
        return CheckResult("TRL Consistency", CheckStatus.PASS,
                           f"TRL aralığı: {list(starts)[0]} → {list(ends)[0]}")
    return CheckResult("TRL Consistency", CheckStatus.INFO,
                       f"{len(proposal.trl_mentions)} TRL referansı bulundu ama net aralık yok.")


def _check_kpi(proposal: ParsedProposal) -> CheckResult:
    if not proposal.kpi_mentions:
        return CheckResult("KPI Presence", CheckStatus.WARNING,
                           "Net KPI/gösterge referansı tespit edilemedi. Ölçülebilir hedefler hem Excellence hem Impact puanını güçlendirir.")
    return CheckResult("KPI Presence", CheckStatus.PASS,
                       f"{len(proposal.kpi_mentions)} KPI/gösterge referansı bulundu.")


def run_eligibility_checks(
    proposal: ParsedProposal,
    action_type: ActionType,
    stage: str = "full",
) -> EligibilityReport:
    """Run all deterministic eligibility and admissibility checks."""
    config = ACTION_TYPE_CONFIGS[action_type]
    results: List[CheckResult] = []
    critical_failures: List[str] = []
    warnings: List[str] = []

    # 1 Page limit
    pc = _check_page_limit(proposal, config, stage)
    results.append(pc)
    if pc.status == CheckStatus.FAIL:
        critical_failures.append(pc.message)

    # 2 Sections
    for sc in _check_required_sections(proposal, config):
        results.append(sc)
        if sc.status == CheckStatus.FAIL:
            critical_failures.append(sc.message)
        elif sc.status == CheckStatus.WARNING:
            warnings.append(sc.message)

    # 3 Consortium
    results.append(_check_consortium(proposal, config))

    # 4 Blind eval
    bc = _check_blind_eval(proposal, config)
    results.append(bc)
    if bc.status == CheckStatus.WARNING:
        warnings.append(bc.message)

    # 5 TRL
    results.append(_check_trl(proposal))

    # 6 KPI
    results.append(_check_kpi(proposal))

    is_admissible = not any(r.status == CheckStatus.FAIL and r.check_name == "Page Limit" for r in results)
    is_eligible = not any(r.status == CheckStatus.FAIL for r in results)

    return EligibilityReport(
        action_type=action_type,
        results=results,
        is_admissible=is_admissible,
        is_eligible=is_eligible,
        critical_failures=critical_failures,
        warnings=warnings,
    )
