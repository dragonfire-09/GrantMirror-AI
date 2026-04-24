"""
Enhanced document parser for Horizon Europe proposals.
Detects sections, extracts structured content, and identifies key elements.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import io

import fitz  # PyMuPDF
from docx import Document


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
class ExtractedTable:
    header: List[str]
    rows: List[List[str]]
    section: SectionType
    page_number: int


@dataclass
class ExtractedSection:
    section_type: SectionType
    title: str
    content: str
    page_start: int
    page_end: int
    word_count: int
    tables: List[ExtractedTable] = field(default_factory=list)
    subsections: List["ExtractedSection"] = field(default_factory=list)


@dataclass
class ParsedProposal:
    full_text: str
    sections: Dict[SectionType, ExtractedSection]
    tables: List[ExtractedTable]
    total_pages: int
    total_words: int
    metadata: Dict[str, str]
    warnings: List[str]
    # Extracted entities
    partner_names: List[str]
    person_names: List[str]
    trl_mentions: List[Dict]
    kpi_mentions: List[str]
    budget_figures: List[Dict]
    acronym: Optional[str]


# ── Section detection patterns ──────────────────────────
SECTION_PATTERNS = {
    SectionType.EXCELLENCE: [
        r"(?i)^[\d\.]*\s*(?:section\s*)?1[\.\s]+excellence",
        r"(?i)^[\d\.]*\s*excellence",
        r"(?i)^[\d\.]*\s*scientific?\s+and\s+technical?\s+quality",
        r"(?i)^1\.\s+excellence",
    ],
    SectionType.IMPACT: [
        r"(?i)^[\d\.]*\s*(?:section\s*)?2[\.\s]+impact",
        r"(?i)^[\d\.]*\s*impact",
        r"(?i)^2\.\s+impact",
    ],
    SectionType.IMPLEMENTATION: [
        r"(?i)^[\d\.]*\s*(?:section\s*)?3[\.\s]+(?:quality\s+and\s+efficiency\s+of\s+(?:the\s+)?implementation|implementation)",
        r"(?i)^[\d\.]*\s*quality\s+and\s+efficiency",
        r"(?i)^3\.\s+(?:quality|implementation)",
    ],
    SectionType.OPEN_SCIENCE: [
        r"(?i)open\s+science\s+practices",
        r"(?i)research\s+data\s+management",
    ],
    SectionType.GENDER_DIMENSION: [
        r"(?i)gender\s+dimension",
        r"(?i)sex\s+and\s+gender\s+analysis",
    ],
    SectionType.DISSEMINATION: [
        r"(?i)dissemination\s+(?:and|&)\s+(?:exploitation|communication)",
        r"(?i)dissemination\s+plan",
    ],
    SectionType.EXPLOITATION: [
        r"(?i)exploitation\s+(?:plan|strategy)",
        r"(?i)intellectual\s+property",
        r"(?i)ipr\s+management",
    ],
    SectionType.WORK_PACKAGES: [
        r"(?i)work\s+plan",
        r"(?i)work\s+packages?\s+(?:description|list)",
        r"(?i)list\s+of\s+work\s+packages",
    ],
    SectionType.RISK_TABLE: [
        r"(?i)risk\s+(?:management|assessment|table|analysis)",
        r"(?i)critical\s+risks",
    ],
    SectionType.DELIVERABLES: [
        r"(?i)(?:list\s+of\s+)?deliverables",
        r"(?i)table\s+.*deliverables",
    ],
    SectionType.MILESTONES: [
        r"(?i)(?:list\s+of\s+)?milestones",
        r"(?i)table\s+.*milestones",
    ],
    SectionType.ETHICS: [
        r"(?i)ethics",
        r"(?i)ethical\s+(?:issues|considerations|aspects)",
    ],
    SectionType.CONSORTIUM: [
        r"(?i)consortium",
        r"(?i)participants?\s+(?:description|list)",
        r"(?i)partner\s+(?:description|list)",
    ],
    SectionType.BUDGET: [
        r"(?i)budget\s+(?:table|overview|summary)",
        r"(?i)estimated\s+budget",
    ],
    SectionType.ABSTRACT: [
        r"(?i)abstract",
        r"(?i)summary",
    ],
    SectionType.REFERENCES: [
        r"(?i)references",
        r"(?i)bibliography",
    ],
}


def extract_text_from_pdf(file_bytes: bytes) -> Tuple[str, int, List[Tuple[int, str]]]:
    """Extract text from PDF with page tracking."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    full_text = ""
    page_texts = []
    total_pages = len(doc)

    for page_num in range(total_pages):
        page = doc[page_num]
        text = page.get_text("text")
        page_texts.append((page_num + 1, text))
        full_text += f"\n--- PAGE {page_num + 1} ---\n{text}"

    doc.close()
    return full_text, total_pages, page_texts


def extract_text_from_docx(file_bytes: bytes) -> Tuple[str, int, List[Tuple[int, str]]]:
    """Extract text from DOCX."""
    doc = Document(io.BytesIO(file_bytes))
    paragraphs = []
    for para in doc.paragraphs:
        paragraphs.append(para.text)

    # Extract tables
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells)
            paragraphs.append(row_text)

    full_text = "\n".join(paragraphs)
    # Approximate pages
    words = len(full_text.split())
    approx_pages = max(1, words // 350)

    return full_text, approx_pages, [(1, full_text)]


def detect_sections(
    full_text: str, page_texts: List[Tuple[int, str]]
) -> Dict[SectionType, ExtractedSection]:
    """Detect proposal sections using pattern matching."""
    sections = {}
    lines = full_text.split("\n")

    current_section = SectionType.UNKNOWN
    current_title = ""
    current_content = []
    current_page_start = 1

    for line in lines:
        stripped = line.strip()
        if not stripped:
            current_content.append("")
            continue

        # Check for page marker
        page_match = re.match(r"--- PAGE (\d+) ---", stripped)
        if page_match:
            current_page = int(page_match.group(1))
            continue

        # Check for section headers
        detected = False
        for section_type, patterns in SECTION_PATTERNS.items():
            for pattern in patterns:
                if re.match(pattern, stripped):
                    # Save previous section
                    if current_content and current_section != SectionType.UNKNOWN:
                        content_text = "\n".join(current_content)
                        sections[current_section] = ExtractedSection(
                            section_type=current_section,
                            title=current_title,
                            content=content_text,
                            page_start=current_page_start,
                            page_end=current_page_start,  # Approximate
                            word_count=len(content_text.split()),
                        )

                    current_section = section_type
                    current_title = stripped
                    current_content = []
                    current_page_start = getattr(
                        detect_sections, "_current_page", 1
                    )
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
            page_start=current_page_start,
            page_end=current_page_start,
            word_count=len(content_text.split()),
        )

    return sections


def extract_trl_mentions(text: str) -> List[Dict]:
    """Find TRL level mentions in text."""
    trl_pattern = r"(?i)TRL\s*[\-:]?\s*(\d)\s*(?:to|→|->|–|-)\s*(?:TRL\s*)?(\d)"
    single_trl = r"(?i)TRL\s*[\-:]?\s*(\d)"

    mentions = []
    for m in re.finditer(trl_pattern, text):
        mentions.append({
            "type": "range",
            "start_trl": int(m.group(1)),
            "end_trl": int(m.group(2)),
            "context": text[max(0, m.start() - 50): m.end() + 50],
        })

    if not mentions:
        for m in re.finditer(single_trl, text):
            mentions.append({
                "type": "single",
                "trl": int(m.group(1)),
                "context": text[max(0, m.start() - 50): m.end() + 50],
            })

    return mentions


def extract_kpi_mentions(text: str) -> List[str]:
    """Find KPI/indicator mentions."""
    kpi_patterns = [
        r"(?i)(?:KPI|key\s+performance\s+indicator)s?\s*[:]\s*([^\n]+)",
        r"(?i)(?:target|indicator|metric)\s*[:]\s*([^\n]+)",
        r"(?i)\d+%\s+(?:increase|decrease|improvement|reduction)",
    ]
    mentions = []
    for pattern in kpi_patterns:
        for m in re.finditer(pattern, text):
            mentions.append(m.group(0).strip())
    return mentions


def extract_budget_figures(text: str) -> List[Dict]:
    """Extract budget-related numbers."""
    patterns = [
        r"(?i)(?:€|EUR)\s*([\d,\.]+)\s*(?:k|K|M|million|thousand)?",
        r"(?i)([\d,\.]+)\s*(?:€|EUR|person[\-\s]months?|PM)",
    ]
    figures = []
    for pattern in patterns:
        for m in re.finditer(pattern, text):
            figures.append({
                "raw": m.group(0),
                "context": text[max(0, m.start() - 30): m.end() + 30],
            })
    return figures


def extract_partner_names(text: str) -> List[str]:
    """Extract potential partner/institution names."""
    patterns = [
        r"(?:University|Universit[äéà]t|Institut[eo]?|Centre|Center|Foundation|GmbH|Ltd|S\.?[rA]\.?[lL]\.?|AG|BV|NV|AS|OY)\s+\w+",
        r"\b[A-Z]{2,8}\b(?=\s*[\(\-])",  # Acronyms followed by ( or -
    ]
    names = set()
    for pattern in patterns:
        for m in re.finditer(pattern, text):
            names.add(m.group(0).strip())
    return list(names)[:50]  # Limit


def parse_proposal(
    file_bytes: bytes, filename: str
) -> ParsedProposal:
    """Main entry point: parse uploaded proposal."""
    warnings = []

    # Detect format and extract
    if filename.lower().endswith(".pdf"):
        full_text, total_pages, page_texts = extract_text_from_pdf(file_bytes)
    elif filename.lower().endswith((".docx", ".doc")):
        full_text, total_pages, page_texts = extract_text_from_docx(file_bytes)
    else:
        raise ValueError(f"Unsupported format: {filename}")

    total_words = len(full_text.split())

    # Detect sections
    sections = detect_sections(full_text, page_texts)

    # Check for expected sections
    expected = [SectionType.EXCELLENCE, SectionType.IMPACT, SectionType.IMPLEMENTATION]
    for exp in expected:
        if exp not in sections:
            warnings.append(
                f"⚠️ Could not detect '{exp.value}' section. "
                "Ensure your proposal follows the standard template structure."
            )

    # Extract entities
    trl_mentions = extract_trl_mentions(full_text)
    kpi_mentions = extract_kpi_mentions(full_text)
    budget_figures = extract_budget_figures(full_text)
    partner_names = extract_partner_names(full_text)

    # Try to find acronym
    acronym_match = re.search(
        r"(?i)(?:acronym|project\s+title)\s*[:]\s*([A-Z][A-Za-z0-9\-]+)", full_text
    )
    acronym = acronym_match.group(1) if acronym_match else None

    # Person names (basic heuristic)
    person_pattern = r"(?:Prof\.|Dr\.|Mr\.|Ms\.|Mrs\.)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)"
    person_names = list(
        set(m.group(1) for m in re.finditer(person_pattern, full_text))
    )

    return ParsedProposal(
        full_text=full_text,
        sections=sections,
        tables=[],  # Enhanced table extraction could be added
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
