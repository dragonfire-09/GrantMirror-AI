"""
GrantMirror-AI: RAG Knowledge Engine.
Retrieves relevant Horizon Europe evaluation knowledge for each criterion.
Uses LLM-enhanced retrieval when available, falls back to keyword matching.
"""
import re
import json
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class KnowledgeDoc:
    doc_id: str
    title: str
    content: str
    category: str  # "official", "esr_pattern", "best_practice", "common_weakness"
    criteria: List[str]  # ["Excellence", "Impact", "Implementation", "all"]
    action_types: List[str]  # ["RIA", "IA", "all"]
    source: str
    weight: float = 1.0  # Higher = more authoritative


# ═══════════════════════════════════════════════════════════
# KNOWLEDGE BASE (from research report)
# ═══════════════════════════════════════════════════════════
KNOWLEDGE_DOCS: List[KnowledgeDoc] = [
    # ── OFFICIAL RULES ──
    KnowledgeDoc(
        "official_scoring", "EC Official Scoring Scale",
        """Official EC scoring scale (0-5, half-point increments):
0 = Proposal fails to address the criterion or cannot be assessed due to missing/incomplete information
1 = Poor: criterion is inadequately addressed, serious inherent weaknesses
2 = Fair: proposal broadly addresses criterion but significant weaknesses
3 = Good: addresses criterion well but with a number of shortcomings (THRESHOLD for RIA/IA/CSA)
4 = Very good: addresses criterion very well but with a small number of shortcomings
5 = Excellent: successfully addresses all relevant aspects; any shortcomings are minor

CRITICAL RULES:
- Evaluate proposal 'as is' — do NOT assume improvements
- Each criterion scored independently
- Same weakness MUST NOT be penalized under multiple criteria
- Score MUST be consistent with written comments
- Half-point scores allowed (3.5, 4.5 etc.)
- Comments must be justified with specific evidence from proposal""",
        "official", ["all"], ["all"], "EC General Annexes & Evaluation Form", 2.0
    ),

    KnowledgeDoc(
        "official_process", "Evaluation Process Structure",
        """Horizon Europe evaluation process (from EC expert briefing 2025-2026):
1. Each proposal evaluated by minimum 3 independent experts
2. Individual Evaluation Reports (IER) produced first
3. Consensus group discussion → Consensus Report (CR)
4. CR usually becomes the ESR sent to applicant
5. Panel reviews for cross-call consistency and ranking
6. Minority opinions possible but rare

IMPLICATIONS FOR SCORING:
- Single score insufficient — system should produce score + confidence interval + consensus risk
- Gray zone around thresholds (3.0 ± 0.5) needs alternative reading
- Panel considers portfolio balance — identical scores may rank differently

AI RULES:
- Official evaluators may NOT delegate evaluation to AI
- AI usable only for ancillary tasks with confidentiality preserved
- This system is a pre-screening tool, NOT official evaluation replacement""",
        "official", ["all"], ["all"], "EC Expert Briefing 2025-2026", 2.0
    ),

    KnowledgeDoc(
        "official_ria_ia_thresholds", "RIA/IA Thresholds and Weights",
        """RIA Thresholds: Excellence 3/5, Impact 3/5, Implementation 3/5. Total threshold: 10/15.
IA Thresholds: Same per-criterion, but Impact weight = 1.5x for ranking. Effective max = 17.5.
Two-stage calls: Stage 1 only Excellence + Impact, threshold 4/5 each, total ~8-8.5.
From 2026-2027: blind evaluation default for two-stage calls.
Page limits: Stage 1 = 10 pages. Full (lump-sum) = 45 pages. Full (non-lump-sum) = 40 pages.
Consortium: minimum 3 entities from 2+ countries (Member States or Associated Countries).""",
        "official", ["all"], ["RIA", "IA"], "EC General Annexes", 2.0
    ),

    # ── EXCELLENCE PATTERNS ──
    KnowledgeDoc(
        "exc_weaknesses", "Excellence: Common Weaknesses from ESR Analysis",
        """Top Excellence weaknesses (LERU 2022 analysis of 129 ESRs + NCP analysis):

1. OBJECTIVES TOO GENERAL: "The objectives are broadly defined but lack specificity and measurable targets"
   Fix: Use SMART framework, include quantified KPIs per objective

2. SOTA INADEQUATE: "State-of-the-art review is superficial; key recent developments not discussed"
   Fix: Include references from last 2-3 years, cite patents, show gap clearly

3. METHODOLOGY VAGUE: "General approach described but lacks specific methods, tools, and validation steps"
   Fix: Detail each method, justify choices, describe validation, link to WPs

4. KPIs MISSING: "No quantified performance indicators to measure progress"
   Fix: Table with KPI, baseline, target, measurement method per objective

5. TRL INCONSISTENCY: "Claimed TRL advancement not convincingly supported by activities"
   Fix: State entry/exit TRL explicitly, map activities to TRL progression

6. INTERDISCIPLINARITY WEAK: "Claimed but not evident in work plan integration"
   Fix: Show where disciplines interact in methodology, not just consortium

7. OPEN SCIENCE BOILERPLATE: "Generic mention without specifying practices"
   Fix: Address EACH mandatory practice (FAIR data, OA publications, RDM plan)

8. GENDER DIMENSION SUPERFICIAL: "Only team composition, not research content"
   Fix: Integrate sex/gender analysis into research design where relevant

PATTERN: Evaluators check OBJECTIVES → KPIs → METHODOLOGY → OUTCOMES chain coherence.
Any break in this chain reduces the score significantly.""",
        "esr_pattern", ["Excellence"], ["all"],
        "LERU ESR Analysis 2022 + Horizon Academy NCP Analysis + Danish UFDS", 1.5
    ),

    KnowledgeDoc(
        "exc_what_works", "Excellence: What Strong Proposals Do",
        """Characteristics of high-scoring Excellence sections (from ESR analysis):

OBJECTIVES:
- Clear, numbered, measurable objectives with KPI table
- Each objective linked to specific WP(s)
- 'Why now' narrative explaining timeliness

SOTA:
- Comprehensive review with recent references (2022+)
- Clear identification of gaps current proposal addresses
- Patent landscape scan where relevant
- Positioning relative to competing approaches
- References to own preliminary results (if not blind eval)

METHODOLOGY:
- Structured by WP or research question
- Each method justified (why this method vs alternatives)
- Validation strategy for each key claim
- Statistical analysis plan where appropriate
- Computational/experimental details sufficient for reproducibility

CROSS-CUTTING:
- Open science: specific DMP outline, named repositories, OA strategy
- Gender: sex/gender variables in research design, gender balance plan
- AI (if used): robustness, reliability, explainability addressed
- Ethics: proactive identification and mitigation""",
        "best_practice", ["Excellence"], ["all"],
        "Bridge2HE Annotated Template + NCP Best Practices", 1.0
    ),

    # ── IMPACT PATTERNS ──
    KnowledgeDoc(
        "imp_weaknesses", "Impact: Common Weaknesses from ESR Analysis",
        """Top Impact weaknesses (LERU + Horizon Academy + Bridge2HE analysis):

1. PATHWAY TO IMPACT VAGUE: "Logic from project outputs to expected outcomes and wider impacts not convincing"
   Fix: Explicit chain — output → outcome → impact with evidence at each step
   NOTE: Only ~30% of evaluator comments use exact 'pathway to impact' terminology

2. TARGET GROUPS UNCLEAR: "Beneficiaries not specifically identified"
   Fix: Named stakeholder categories, size estimates, engagement strategy per group

3. DISSEMINATION GENERIC: "Standard channels listed without justification for audiences"
   Fix: Channel × audience matrix with justification for each combination

4. EXPLOITATION WEAK: "No concrete commercial/policy uptake pathway"
   Fix: Per-result exploitation route, responsible partner, timeline, barriers

5. IMPACT KPIs MISSING: "No baselines, benchmarks, or quantified estimations"
   Fix: Impact indicator table with baseline, target, measurement, timeframe

6. IPR NOT ADDRESSED: "Ownership and management not discussed"
   Fix: IP ownership rules, background IP list, access rights, licensing strategy

7. SUSTAINABILITY ABSENT: "No plan for post-project continuation"
   Fix: Funding sources, business model, institutional embedding after project

CRITICAL: Evaluators check alignment between proposal outcomes and topic-level 
expected outcomes from Work Programme. Misalignment = major weakness.

TERMINOLOGY: Normalize — outputs (project deliverables) → outcomes (direct changes) 
→ impacts (wider long-term effects). LERU found evaluators use varied terminology.""",
        "esr_pattern", ["Impact"], ["all"],
        "LERU ESR Analysis + Horizon Academy + Bridge2HE + Danish UFDS", 1.5
    ),

    # ── IMPLEMENTATION PATTERNS ──
    KnowledgeDoc(
        "impl_weaknesses", "Implementation: Common Weaknesses from ESR Analysis",
        """Top Implementation weaknesses (LERU + Danish + Horizon Academy):

1. WORK PLAN UNCLEAR: "Links between WPs, tasks, and objectives not explicit"
   Fix: Objective-WP mapping table, task descriptions with inputs/outputs

2. DELIVERABLES VAGUE: "Several deliverables described as 'reports' without content specs"
   Fix: Each deliverable with type, content description, verification criteria

3. MILESTONES ADMINISTRATIVE: "Not scientific/technical decision points"
   Fix: Milestones as go/no-go decisions with criteria and alternative paths

4. RISK MITIGATION TAUTOLOGICAL: "If delayed, we will accelerate" — not a real mitigation
   CRITICAL: >50% of negative risk comments target mitigation quality, not risk identification
   Fix: Specific alternative approaches, contingency resources, decision triggers

5. PM ALLOCATION UNJUSTIFIED: "Distribution across partners not justified"
   Fix: PM per partner per WP with brief justification of effort level

6. PARTNER ROLE UNCLEAR: "Specific expertise not demonstrated"
   Fix: Each partner's unique contribution, relevant track record, why essential

7. BUDGET DISPROPORTIONATE: "Allocation doesn't match described scope"
   Fix: Budget narrative linking cost categories to activities

8. GOVERNANCE SUPERFICIAL: "Decision-making mechanisms not specified"
   Fix: Named bodies, meeting frequency, voting rules, conflict resolution

From Danish H2020 analysis (250 proposals, 1745 comments):
'Imbalance' and 'inadequate risk management' among top 6 recurring weakness families.
This pattern is stable from H2020 through Horizon Europe.""",
        "esr_pattern", ["Implementation"], ["all"],
        "LERU + Danish UFDS + Horizon Academy", 1.5
    ),

    # ── SIX CORE WEAKNESS FAMILIES ──
    KnowledgeDoc(
        "six_families", "Six Core Weakness Families (Cross-Cutting)",
        """Six core weakness families (remarkably stable from H2020 2017 → HE 2024-25):

1. LACK_OF_DETAIL — Claims without supporting evidence or specifics
   Affects: Excellence (methodology), Implementation (work plan)
   Signal: Generic language, no numbers, no method names

2. LACK_OF_QUANTIFICATION — Targets, KPIs, impact estimates not quantified
   Affects: Excellence (objectives), Impact (outcomes)
   Signal: "significant impact" without numbers, no baseline/target

3. UNCLEAR_TARGET_GROUPS — Stakeholders/beneficiaries not specifically identified
   Affects: Impact (dissemination, exploitation)
   Signal: "relevant stakeholders" without naming who

4. RESOURCE_IMBALANCE — Person-months or budget not proportional to tasks
   Affects: Implementation
   Signal: Partner with 2 PM but leading a WP, or 30% budget with 10% work

5. INTERNAL_INCOHERENCE — Sections contradict each other or logic chain broken
   Affects: All criteria
   Signal: Objectives mention X but methodology doesn't address it

6. WEAK_RISK_MITIGATION — Risks identified but mitigations generic/tautological
   Affects: Implementation
   Signal: "We will find alternative approaches" without specifying what

PLATFORM STRATEGY: Detect these six families FIRST, then refine by action type and call.""",
        "esr_pattern", ["all"], ["all"],
        "Danish UFDS H2020 Analysis + LERU HE Analysis (synthesized)", 1.8
    ),

    # ── ACTION-TYPE SPECIFIC ──
    KnowledgeDoc(
        "msca_specific", "MSCA-DN Evaluation Specifics",
        """MSCA Doctoral Networks evaluation:
- Scale: 0-100 per criterion (not 0-5)
- Weights: Excellence 50%, Impact 30%, Implementation 20%
- Threshold: 70/100 per criterion AND overall
- Process: ≥3 external experts → consensus → panel → ranking, ESR in ~5 months

UNIQUE ASPECTS (not in standard RIA/IA):
- Training programme quality is CENTRAL (not peripheral)
- Supervision: dual supervision expected (academic + non-academic where relevant)
- Career development: employability must be concretely addressed
- Recruitment: MUST be open, transparent, merit-based, non-discriminatory
- Secondments: well-justified with clear learning objectives
- Non-academic sector involvement valued

KEY DIFFERENCE: A proposal with excellent research but weak training = low score.
Training and career development carry equal weight to research quality.""",
        "official", ["all"], ["MSCA-DN"],
        "REA MSCA Evaluation Process + MSCA Work Programme", 1.5
    ),

    KnowledgeDoc(
        "eic_specific", "EIC Evaluation Specifics",
        """EIC Pathfinder Open:
- Thresholds: Excellence 4/5, Impact 3.5/5, Implementation 3/5
- INCREMENTALISM EXPLICITLY PENALIZED
- Must show: long-term transformative vision, science-to-technology breakthrough
- 'High-risk/high-gain' is expected, not a weakness
- Team capability for exploratory research weighted heavily

EIC Accelerator:
- Short application: GO / NO GO (binary, no score)
- Full application: per-criterion threshold 4/5, total 13/15
- After full app: jury interview → final GO / NO GO
- Focus: breakthrough innovation, market opportunity, team capability, scalability
- Single SME can apply
- Blended finance (grant up to EUR 2.5M + equity up to EUR 15M)
- Commercial track record and go-to-market strategy critical""",
        "official", ["all"], ["EIC-Pathfinder-Open", "EIC-Accelerator"],
        "EIC Work Programme + Access2EIC", 1.5
    ),

    KnowledgeDoc(
        "erc_specific", "ERC Evaluation Specifics",
        """ERC Starting/Consolidator/Advanced/Synergy:
- SINGLE CRITERION: Excellence
- Two sub-dimensions: (a) project ground-breaking nature/feasibility (b) PI quality
- StG/CoG/AdG: two-stage, step 2 includes interview
- Synergy: three-stage
- No numeric threshold — panel-based A/B/C ranking
- PI track record assessed RELATIVE TO CAREER STAGE and opportunities
- Host institution suitability considered
- NO consortium requirement

KEY: PI quality ≈ equal weight to project quality.
No Impact or Implementation criterion — everything under Excellence.""",
        "official", ["Excellence"], ["ERC-StG"],
        "ERC Work Programme", 1.5
    ),

    # ── ANNOTATED TEMPLATE INSIGHTS ──
    KnowledgeDoc(
        "template_signals", "Implicit Quality Signals (from annotated templates)",
        """What evaluators look for beyond official questions (Bridge2HE + Access2EIC):

IMPLICIT EXPECTATIONS:
- After objectives → immediate mapping to WP expected outcomes
- SOTA section → recent refs (2-3 years), patents if applicable
- Methodology → sub-sections matching WPs
- Gantt chart → evaluators quickly scan for timeline realism
- Risk table → minimum 8-10 specific risks with non-trivial mitigations
- Partner table → show complementarity, not just listing
- Budget → big items need explicit justification

FORMATTING SIGNALS (not officially scored but influence reading):
- Tables preferred over long paragraphs for KPIs, risks, deliverables
- Clear numbering helps evaluators reference specific points
- Consistent terminology across sections signals coherence
- Cross-references between sections show integrated thinking

Evaluators don't just read official questions — they have learned implicit 
expectations about WHERE and HOW information appears in the template.""",
        "best_practice", ["all"], ["all"],
        "Bridge2HE Annotated RIA/IA Template + Access2EIC Pathfinder Template", 1.0
    ),
]


# ═══════════════════════════════════════════════════════════
# RETRIEVAL ENGINE
# ═══════════════════════════════════════════════════════════
def retrieve_knowledge(
    query: str,
    criterion: str = "all",
    action_type: str = "all",
    category: Optional[str] = None,
    top_k: int = 5,
) -> List[KnowledgeDoc]:
    """
    Retrieve relevant knowledge documents.
    Uses weighted keyword matching.
    """
    query_words = set(re.findall(r'[a-z]{3,}', query.lower()))

    scored: List[Tuple[KnowledgeDoc, float]] = []

    for doc in KNOWLEDGE_DOCS:
        # Filter by criterion
        if criterion != "all" and "all" not in doc.criteria and criterion not in doc.criteria:
            continue

        # Filter by action type
        if action_type != "all" and "all" not in doc.action_types and action_type not in doc.action_types:
            continue

        # Filter by category
        if category and doc.category != category:
            continue

        # Score by word overlap
        doc_words = set(re.findall(r'[a-z]{3,}', doc.content.lower()))
        title_words = set(re.findall(r'[a-z]{3,}', doc.title.lower()))

        content_overlap = len(query_words & doc_words)
        title_overlap = len(query_words & title_words) * 3  # Title matches worth more

        score = (content_overlap + title_overlap) * doc.weight

        if score > 0:
            scored.append((doc, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [doc for doc, _ in scored[:top_k]]


def get_criterion_context(
    criterion: str,
    action_type: str,
    proposal_excerpt: str = "",
) -> str:
    """
    Get full knowledge context for evaluating a specific criterion.
    Combines official rules + ESR patterns + best practices.
    """
    # Always include official scoring
    chunks = []

    # Official rules
    official = retrieve_knowledge(
        f"{criterion} scoring rules thresholds",
        criterion=criterion,
        action_type=action_type,
        category="official",
        top_k=3,
    )
    for doc in official:
        chunks.append(f"[OFFICIAL — {doc.source}]\n{doc.content}")

    # ESR patterns
    patterns = retrieve_knowledge(
        f"{criterion} weaknesses strengths evaluation",
        criterion=criterion,
        action_type=action_type,
        category="esr_pattern",
        top_k=2,
    )
    for doc in patterns:
        chunks.append(f"[ESR PATTERN — {doc.source}]\n{doc.content}")

    # Best practices
    practices = retrieve_knowledge(
        f"{criterion} best practice quality",
        criterion=criterion,
        action_type=action_type,
        category="best_practice",
        top_k=1,
    )
    for doc in practices:
        chunks.append(f"[BEST PRACTICE — {doc.source}]\n{doc.content}")

    # If proposal excerpt provided, find additional relevant docs
    if proposal_excerpt:
        extra = retrieve_knowledge(
            proposal_excerpt[:500],
            criterion=criterion,
            action_type=action_type,
            top_k=2,
        )
        for doc in extra:
            if doc.content not in "\n".join(chunks):
                chunks.append(f"[RELEVANT — {doc.source}]\n{doc.content}")

    return "\n\n---\n\n".join(chunks) if chunks else "No specific knowledge available for this criterion/action type combination."


def ai_enhanced_retrieval(
    criterion: str,
    action_type: str,
    proposal_section: str,
    llm_call_fn,
) -> str:
    """
    AI-enhanced knowledge retrieval: uses LLM to select most relevant knowledge
    and synthesize it into evaluation guidance.
    """
    # Get base context
    base_context = get_criterion_context(criterion, action_type, proposal_section[:500])

    system_prompt = """You are a Horizon Europe evaluation knowledge synthesizer.
Given knowledge base documents and a proposal section, synthesize the most relevant 
evaluation guidance. Focus on what's specifically relevant to THIS proposal."""

    user_prompt = f"""## CRITERION: {criterion}
## ACTION TYPE: {action_type}

## KNOWLEDGE BASE:
{base_context[:6000]}

## PROPOSAL SECTION EXCERPT:
{proposal_section[:2000]}

## TASK:
Synthesize the most relevant evaluation guidance for this specific proposal.
What should the evaluator particularly look for? What common weaknesses are most likely?

Respond JSON:
{{
  "key_evaluation_points": ["<specific point to check>"],
  "likely_weaknesses": ["<based on knowledge, what weakness is this proposal likely to have>"],
  "relevant_rules": ["<official rules particularly applicable here>"],
  "synthesized_context": "<2-3 paragraph synthesis of relevant knowledge for evaluating this section>"
}}"""

    try:
        raw = llm_call_fn(system_prompt, user_prompt)
        result = json.loads(raw)
        synthesized = result.get("synthesized_context", base_context)
        return f"[AI-SYNTHESIZED GUIDANCE]\n{synthesized}\n\n{base_context}"
    except Exception:
        return base_context
