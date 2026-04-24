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


def run_eligibility_checks(proposal: ParsedProposal, action_type: ActionType, stage: str = "full") -> EligibilityReport:
    cfg = ACTION_TYPE_CONFIGS[action_type]
    results = []
    fails = []
    warns = []

    # Page limit
    limit = cfg.page_limit_full if stage == "full" else cfg.page_limit_stage1
    if limit:
        p = proposal.total_pages
        if p > limit:
            r = CheckResult("Page Limit", CheckStatus.FAIL, f"{p} sayfa; limit {limit}.")
            fails.append(r.message)
        elif p > limit * 0.95:
            r = CheckResult("Page Limit", CheckStatus.WARNING, f"{p} sayfa — limite cok yakin ({limit}).")
            warns.append(r.message)
        else:
            r = CheckResult("Page Limit", CheckStatus.PASS, f"{p} sayfa (limit: {limit}).")
        results.append(r)

    # Sections
    for st, label in [(SectionType.EXCELLENCE, "Excellence"), (SectionType.IMPACT, "Impact"), (SectionType.IMPLEMENTATION, "Implementation")]:
        if st in proposal.sections:
            wc = proposal.sections[st].word_count
            if wc < 100:
                r = CheckResult(f"Section: {label}", CheckStatus.WARNING, f"'{label}' cok kisa ({wc} kelime).")
                warns.append(r.message)
            else:
                r = CheckResult(f"Section: {label}", CheckStatus.PASS, f"'{label}' bulundu ({wc} kelime).")
        else:
            r = CheckResult(f"Section: {label}", CheckStatus.FAIL, f"'{label}' BULUNAMADI.")
            fails.append(r.message)
        results.append(r)

    # Cross-cutting
    for kw, label in [("open science", "Open Science"), ("gender dimension", "Gender Dimension"),
                       ("dissemination", "Dissemination"), ("risk", "Risk Management")]:
        found = kw in proposal.full_text.lower()
        results.append(CheckResult(f"Cross: {label}",
                                    CheckStatus.PASS if found else CheckStatus.WARNING,
                                    f"'{label}' {'bulundu' if found else 'tespit edilemedi'}."))

    # Consortium
    n = len(proposal.partner_names)
    if n == 0:
        results.append(CheckResult("Consortium", CheckStatus.UNABLE, f"Partner adi tespit edilemedi. Min: {cfg.min_consortium_size}."))
    elif n < cfg.min_consortium_size:
        results.append(CheckResult("Consortium", CheckStatus.WARNING, f"{n} partner; min {cfg.min_consortium_size}."))
    else:
        results.append(CheckResult("Consortium", CheckStatus.PASS, f"{n} partner (min: {cfg.min_consortium_size})."))

    # Blind eval
    if cfg.blind_evaluation:
        sigs = []
        if proposal.partner_names:
            sigs.append(f"Kurum adlari: {', '.join(proposal.partner_names[:3])}")
        if proposal.person_names:
            sigs.append(f"Kisi adlari: {', '.join(proposal.person_names[:3])}")
        for pat in [r"(?i)(?:our|we)\s+(?:have|previously)\s+(?:developed|shown|published)",
                     r"(?i)in\s+our\s+(?:previous|earlier)\s+(?:work|project)"]:
            if re.search(pat, proposal.full_text[:5000]):
                sigs.append("Oz-referans dili tespit edildi")
                break
        if sigs:
            r = CheckResult("Blind Eval", CheckStatus.WARNING, "Kimlik ifsa riski.", "\n".join(sigs))
            warns.append(r.message)
        else:
            r = CheckResult("Blind Eval", CheckStatus.PASS, "Kimlik bilgisi tespit edilmedi.")
        results.append(r)

    # TRL
    if proposal.trl_mentions:
        results.append(CheckResult("TRL", CheckStatus.PASS, f"{len(proposal.trl_mentions)} TRL referansi."))
    else:
        results.append(CheckResult("TRL", CheckStatus.WARNING, "TRL referansi bulunamadi."))

    # KPI
    if proposal.kpi_mentions:
        results.append(CheckResult("KPI", CheckStatus.PASS, f"{len(proposal.kpi_mentions)} KPI referansi."))
    else:
        results.append(CheckResult("KPI", CheckStatus.WARNING, "KPI/gosterge bulunamadi."))

    return EligibilityReport(
        action_type=action_type, results=results,
        is_admissible=not any(r.status == CheckStatus.FAIL and "Page" in r.check_name for r in results),
        is_eligible=len(fails) == 0,
        critical_failures=fails, warnings=warns,
    )
