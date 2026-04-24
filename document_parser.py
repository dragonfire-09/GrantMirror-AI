"""
Document parser for Horizon Europe proposals.
Extracts text, detects sections, finds key entities.
"""
import re
import io
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


class SectionType(str, Enum):
    EXCELLENCE = "excellence"
    IMPACT = "impact"
    IMPLEMENTATION = "implementation"
    ETHICS = "ethics"
    BUDGET = "budget"
    CONSORTIUM = "consortium"
    WORK_PACKAGES = "work_packages"
    RISK_TABLE = "risk_table"
    GANTT = "gantt"
    DELIVERABLES = "deliverables"
    MILESTONES = "milestones"
    OPEN_SCIENCE = "open_science"
    GENDER_DIMENSION = "gender_dimension"
    DISSEMINATION = "dissemination"
    EXPLOITATION = "exploitation"
    REFERENCES = "references"
    ABSTRACT = "abstract"
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


# ── Section detection patterns ──────────────────────────
SECTION_PATTERNS: Dict[SectionType, List[str]] = {
    SectionType.EXCELLENCE: [
        r"(?i)^[\d\.]*\s*(?:section\s*)?1[\.\s]+excellence",
        r"(?i)^[\d\.]*\s*excellence",
        r"(?i)^1\.\s+excellence",
    ],
    SectionType.IMPACT: [
        r"(?i)^[\d\.]*\s*(?:section\s*)?2[\.\s]+impact",
        r"(?i)^[\d\.]*\s*impact",
        r"(?i)^2\.\s+impact",
    ],
    SectionType.IMPLEMENTATION: [
        r"(?i)^[\d\.]*\s*(?:section\s*)?3[\.\s]+(?:quality|implementation)",
        r"(?i)^[\d\.]*\s*quality\s+and\s+efficiency",
        r"(?i)^3\.\s+(?:quality|implementation)",
    ],
    SectionType.OPEN_SCIENCE: [
        r"(?i)open\s+science\s+practices",
    ],
    SectionType.GENDER_DIMENSION: [
        r"(?i)gender\s+dimension",
    ],
    SectionType.DISSEMINATION: [
        r"(?i)dissemination\s+(?:and|&)\s+(?:exploitation|communication)",
    ],
    SectionType.EXPLOITATION: [
        r"(?i)exploitation\s+(?:plan|strategy)",
    ],
    SectionType.WORK_PACKAGES: [
        r"(?i)work\s+plan",
        r"(?i)work\s+packages?\s+(?:description|list)",
    ],
    SectionType.RISK_TABLE: [
        r"(?i)risk\s+(?:management|assessment|table)",
        r"(?i)critical\s+risks",
    ],
    SectionType.DELIVERABLES: [
        r"(?i)(?:list\s+of\s+)?deliverables",
    ],
    SectionType.MILESTONES: [
        r"(?i)(?:list\s+of\s+)?milestones",
    ],
    SectionType.ETHICS: [
        r"(?i)ethics",
    ],
    SectionType.CONSORTIUM: [
        r"(?i)consortium",
        r"(?i)participants?\s+(?:description|list)",
    ],
    SectionType.ABSTRACT: [
        r"(?i)^abstract",
        r"(?i)^summary",
    ],
    SectionType.REFERENCES: [
        r"(?i)^references",
        r"(?i)^bibliography",
    ],
}


def _extract_text_from_pdf(file_bytes: bytes) -> Tuple[str, int, List[Tuple[int, str]]]:
    """Extract text from PDF with page tracking."""
    try:
        import fitz
    except ImportError:
        raise ImportError("PyMuPDF gerekli: pip install PyMuPDF")

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    full_text = ""
    page_texts: List[Tuple[int, str]] = []
    total_pages = len(doc)

    for page_num in range(total_pages):
        page = doc[page_num]
        text = page.get_text("text")
        page_texts.append((page_num + 1, text))
        full_text += f"\n--- PAGE {page_num + 1} ---\n{text}"

    doc.close()
    return full_text, total_pages, page_texts


def _extract_text_from_docx(file_bytes: bytes) -> Tuple[str, int, List[Tuple[int, str]]]:
    """Extract text from DOCX."""
    try:
        from docx import Document
    except ImportError:
        raise ImportError("python-docx gerekli: pip install python-docx")

    doc = Document(io.BytesIO(file_bytes))
    paragraphs: List[str] = []
    for para in doc.paragraphs:
        paragraphs.append(para.text)

    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells)
            paragraphs.append(row_text)

    full_text = "\n".join(paragraphs)
    words = len(full_text.split())
    approx_pages = max(1, words // 350)
    return full_text, approx_pages, [(1, full_text)]


def _detect_sections(full_text: str) -> Dict[SectionType, ExtractedSection]:
    """Detect proposal sections using pattern matching."""
    sections: Dict[SectionType, ExtractedSection] = {}
    lines = full_text.split("\n")

    current_section = SectionType.UNKNOWN
    current_title = ""
    current_content: List[str] = []
    current_page = 1

    for line in lines:
        stripped = line.strip()
        if not stripped:
            current_content.append("")
            continue

        # Page marker
        page_match = re.match(r"--- PAGE (\d+) ---", stripped)
        if page_match:
            current_page = int(page_match.group(1))
            continue

        # Check section headers
        detected = False
        for section_type, patterns in SECTION_PATTERNS.items():
            for pattern in patterns:
                if re.match(pattern, stripped):
                    # Save previous
                    if current_content and current_section != SectionType.UNKNOWN:
                        content_text = "\n".join(current_content)
                        sections[current_section] = ExtractedSection(
                            section_type=current_section,
                            title=current_title,
                            content=content_text,
                            page_start=1,
                            page_end=current_page,
                            word_count=len(content_text.split()),
                        )
                    current_section = section_type
                    current_title = stripped
                    current_content = []
                    detected = True
                    break
            if detected:
                break

        if not detected:
            current_content.append(stripped)

    # Save last section
    if current_content and current_section != SectionType.UNKNOWN:
        content_text = "\n".join(current_content)
        sections[current_section] = ExtractedSection(
            section_type=current_section,
            title=current_title,
            content=content_text,
            page_start=1,
            page_end=current_page,
            word_count=len(content_text.split()),
        )

    return sections


def _extract_trl_mentions(text: str) -> List[Dict]:
    mentions: List[Dict] = []
    for m in re.finditer(r"(?i)TRL\s*[\-:]?\s*(\d)\s*(?:to|→|->|–|-)\s*(?:TRL\s*)?(\d)", text):
        mentions.append({"type": "range", "start_trl": int(m.group(1)), "end_trl": int(m.group(2)),
                         "context": text[max(0, m.start()-40):m.end()+40]})
    if not mentions:
        for m in re.finditer(r"(?i)TRL\s*[\-:]?\s*(\d)", text):
            mentions.append({"type": "single", "trl": int(m.group(1)),
                             "context": text[max(0, m.start()-40):m.end()+40]})
    return mentions


def _extract_kpi_mentions(text: str) -> List[str]:
    mentions: List[str] = []
    for pattern in [r"(?i)(?:KPI|key\s+performance\s+indicator)s?\s*[:]\s*([^\n]+)",
                    r"(?i)\d+%\s+(?:increase|decrease|improvement|reduction)"]:
        for m in re.finditer(pattern, text):
            mentions.append(m.group(0).strip())
    return mentions


def _extract_budget_figures(text: str) -> List[Dict]:
    figures: List[Dict] = []
    for m in re.finditer(r"(?i)(?:€|EUR)\s*([\d,\.]+)\s*(?:k|K|M|million|thousand)?", text):
        figures.append({"raw": m.group(0), "context": text[max(0, m.start()-30):m.end()+30]})
    return figures


def _extract_partner_names(text: str) -> List[str]:
    names = set()
    for m in re.finditer(
        r"(?:University|Universit[äéà]t|Institut[eo]?|Centre|Center|Foundation|GmbH|Ltd|AG|BV|NV)\s+\w+",
        text
    ):
        names.add(m.group(0).strip())
    return list(names)[:50]


def _extract_person_names(text: str) -> List[str]:
    return list(set(
        m.group(1)
        for m in re.finditer(r"(?:Prof\.|Dr\.|Mr\.|Ms\.|Mrs\.)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)", text)
    ))


def parse_proposal(file_bytes: bytes, filename: str) -> ParsedProposal:
    """Main entry: parse uploaded proposal file."""
    warnings: List[str] = []

    # Extract text
    lower = filename.lower()
    if lower.endswith(".pdf"):
        full_text, total_pages, page_texts = _extract_text_from_pdf(file_bytes)
    elif lower.endswith((".docx", ".doc")):
        full_text, total_pages, page_texts = _extract_text_from_docx(file_bytes)
    else:
        raise ValueError(f"Desteklenmeyen format: {filename}")

    total_words = len(full_text.split())

    # Detect sections
    sections = _detect_sections(full_text)

    for expected in [SectionType.EXCELLENCE, SectionType.IMPACT, SectionType.IMPLEMENTATION]:
        if expected not in sections:
            warnings.append(f"⚠️ '{expected.value}' bölümü tespit edilemedi. Şablon yapısını kontrol edin.")

    # Entities
    trl_mentions = _extract_trl_mentions(full_text)
    kpi_mentions = _extract_kpi_mentions(full_text)
    budget_figures = _extract_budget_figures(full_text)
    partner_names = _extract_partner_names(full_text)
    person_names = _extract_person_names(full_text)

    acronym_match = re.search(r"(?i)(?:acronym|project\s+title)\s*[:]\s*([A-Z][A-Za-z0-9\-]+)", full_text)
    acronym = acronym_match.group(1) if acronym_match else None

    return ParsedProposal(
        full_text=full_text,
        sections=sections,
        total_pages=total_pages,
        total_words=total_words,
        metadata={"filename": filename},
        warnings=warnings,
        partner_names=partner_names,
        person_names=person_names,
        trl_mentions=trl_mentions,
        kpi_mentions=kpi_mentions,
        budget_figures=budget_figures,
        acronym=acronym,
    )
