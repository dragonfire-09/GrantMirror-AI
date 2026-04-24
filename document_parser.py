import re
import io
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


class SectionType(str, Enum):
    EXCELLENCE = "excellence"
    IMPACT = "impact"
    IMPLEMENTATION = "implementation"
    OPEN_SCIENCE = "open_science"
    GENDER_DIMENSION = "gender_dimension"
    DISSEMINATION = "dissemination"
    EXPLOITATION = "exploitation"
    WORK_PACKAGES = "work_packages"
    RISK_TABLE = "risk_table"
    DELIVERABLES = "deliverables"
    MILESTONES = "milestones"
    ETHICS = "ethics"
    CONSORTIUM = "consortium"
    ABSTRACT = "abstract"
    REFERENCES = "references"
    UNKNOWN = "unknown"


@dataclass
class ExtractedSection:
    section_type: SectionType
    title: str
    content: str
    page_start: int
    page_end: int
    word_count: int


@dataclass
class ParsedProposal:
    full_text: str
    sections: Dict[SectionType, ExtractedSection]
    total_pages: int
    total_words: int
    metadata: Dict[str, str]
    warnings: List[str]
    partner_names: List[str]
    person_names: List[str]
    trl_mentions: List[Dict]
    kpi_mentions: List[str]
    budget_figures: List[Dict]
    acronym: Optional[str]


SECTION_PATTERNS = {
    SectionType.EXCELLENCE: [r"(?i)^[\d\.]*\s*(?:section\s*)?1[\.\s]+excellence", r"(?i)^1\.\s+excellence", r"(?i)^[\d\.]*\s*excellence"],
    SectionType.IMPACT: [r"(?i)^[\d\.]*\s*(?:section\s*)?2[\.\s]+impact", r"(?i)^2\.\s+impact", r"(?i)^[\d\.]*\s*impact"],
    SectionType.IMPLEMENTATION: [r"(?i)^[\d\.]*\s*(?:section\s*)?3[\.\s]+(?:quality|implementation)", r"(?i)^3\.\s+(?:quality|implementation)"],
    SectionType.OPEN_SCIENCE: [r"(?i)open\s+science\s+practices"],
    SectionType.GENDER_DIMENSION: [r"(?i)gender\s+dimension"],
    SectionType.DISSEMINATION: [r"(?i)dissemination\s+(?:and|&)\s+(?:exploitation|communication)"],
    SectionType.EXPLOITATION: [r"(?i)exploitation\s+(?:plan|strategy)"],
    SectionType.WORK_PACKAGES: [r"(?i)work\s+plan", r"(?i)work\s+packages?\s+(?:description|list)"],
    SectionType.RISK_TABLE: [r"(?i)risk\s+(?:management|assessment|table)", r"(?i)critical\s+risks"],
    SectionType.DELIVERABLES: [r"(?i)(?:list\s+of\s+)?deliverables"],
    SectionType.MILESTONES: [r"(?i)(?:list\s+of\s+)?milestones"],
    SectionType.ETHICS: [r"(?i)^ethics"],
    SectionType.CONSORTIUM: [r"(?i)consortium", r"(?i)participants?\s+(?:description|list)"],
    SectionType.ABSTRACT: [r"(?i)^abstract", r"(?i)^summary"],
    SectionType.REFERENCES: [r"(?i)^references", r"(?i)^bibliography"],
}


def _pdf_text(fb: bytes):
    import fitz
    doc = fitz.open(stream=fb, filetype="pdf")
    full = ""
    pts = []
    for i in range(len(doc)):
        t = doc[i].get_text("text")
        pts.append((i + 1, t))
        full += f"\n--- PAGE {i+1} ---\n{t}"
    doc.close()
    return full, len(doc), pts


def _docx_text(fb: bytes):
    from docx import Document
    doc = Document(io.BytesIO(fb))
    parts = [p.text for p in doc.paragraphs]
    for tbl in doc.tables:
        for row in tbl.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    full = "\n".join(parts)
    pages = max(1, len(full.split()) // 350)
    return full, pages, [(1, full)]


def _detect(full_text):
    secs = {}
    lines = full_text.split("\n")
    cur_type = SectionType.UNKNOWN
    cur_title = ""
    cur_lines = []
    cur_page = 1

    for line in lines:
        s = line.strip()
        if not s:
            cur_lines.append("")
            continue
        pm = re.match(r"--- PAGE (\d+) ---", s)
        if pm:
            cur_page = int(pm.group(1))
            continue
        found = False
        for st, pats in SECTION_PATTERNS.items():
            for p in pats:
                if re.match(p, s):
                    if cur_lines and cur_type != SectionType.UNKNOWN:
                        txt = "\n".join(cur_lines)
                        secs[cur_type] = ExtractedSection(cur_type, cur_title, txt, 1, cur_page, len(txt.split()))
                    cur_type = st
                    cur_title = s
                    cur_lines = []
                    found = True
                    break
            if found:
                break
        if not found:
            cur_lines.append(s)

    if cur_lines and cur_type != SectionType.UNKNOWN:
        txt = "\n".join(cur_lines)
        secs[cur_type] = ExtractedSection(cur_type, cur_title, txt, 1, cur_page, len(txt.split()))
    return secs


def parse_proposal(file_bytes: bytes, filename: str) -> ParsedProposal:
    warnings = []
    low = filename.lower()
    if low.endswith(".pdf"):
        full, pages, pts = _pdf_text(file_bytes)
    elif low.endswith((".docx", ".doc")):
        full, pages, pts = _docx_text(file_bytes)
    else:
        raise ValueError(f"Desteklenmeyen format: {filename}")

    words = len(full.split())
    secs = _detect(full)

    for exp in [SectionType.EXCELLENCE, SectionType.IMPACT, SectionType.IMPLEMENTATION]:
        if exp not in secs:
            warnings.append(f"'{exp.value}' bolumu tespit edilemedi.")

    trl = []
    for m in re.finditer(r"(?i)TRL\s*[\-:]?\s*(\d)\s*(?:to|->|–|-)\s*(?:TRL\s*)?(\d)", full):
        trl.append({"type": "range", "start_trl": int(m.group(1)), "end_trl": int(m.group(2))})
    if not trl:
        for m in re.finditer(r"(?i)TRL\s*[\-:]?\s*(\d)", full):
            trl.append({"type": "single", "trl": int(m.group(1))})

    kpi = [m.group(0).strip() for m in re.finditer(r"(?i)(?:KPI|key\s+performance\s+indicator)s?\s*[:]\s*([^\n]+)", full)]
    budget = [{"raw": m.group(0)} for m in re.finditer(r"(?i)(?:€|EUR)\s*([\d,\.]+)", full)]
    partners = list(set(m.group(0).strip() for m in re.finditer(
        r"(?:University|Institut[eo]?|Centre|Center|Foundation|GmbH|Ltd|AG)\s+\w+", full)))[:50]
    persons = list(set(m.group(1) for m in re.finditer(
        r"(?:Prof\.|Dr\.|Mr\.|Ms\.)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)", full)))
    acr_m = re.search(r"(?i)(?:acronym|project\s+title)\s*[:]\s*([A-Z][A-Za-z0-9\-]+)", full)

    return ParsedProposal(
        full_text=full, sections=secs, total_pages=pages, total_words=words,
        metadata={"filename": filename}, warnings=warnings,
        partner_names=partners, person_names=persons,
        trl_mentions=trl, kpi_mentions=kpi, budget_figures=budget,
        acronym=acr_m.group(1) if acr_m else None,
    )
