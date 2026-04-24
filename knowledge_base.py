"""
RAG Knowledge Base for Horizon Europe evaluation context.
Stores and retrieves official guidelines, ESR patterns, and call-specific information.
"""
import json
import os
from dataclasses import dataclass
from typing import List, Optional, Dict
from pathlib import Path

try:
    import chromadb
    from chromadb.config import Settings
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


@dataclass
class KnowledgeChunk:
    content: str
    source: str
    category: str  # "official_guide", "esr_pattern", "call_text", "annotated_template"
    metadata: Dict[str, str]
    relevance_score: float = 0.0


class HorizonKnowledgeBase:
    """
    Manages the knowledge base for Horizon Europe evaluation.
    Supports both embedded vector store and fallback keyword search.
    """

    def __init__(self, data_dir: str = "data/knowledge_docs"):
        self.data_dir = Path(data_dir)
        self.chunks: List[KnowledgeChunk] = []
        self.use_vector_store = HAS_CHROMADB and HAS_OPENAI

        if self.use_vector_store:
            self.client = chromadb.Client(Settings(anonymized_telemetry=False))
            self.collection = self.client.get_or_create_collection(
                name="horizon_knowledge",
                metadata={"hnsw:space": "cosine"},
            )

        self._load_built_in_knowledge()

    def _load_built_in_knowledge(self):
        """Load built-in evaluation knowledge."""

        # ── Official scoring descriptors ──
        scoring_knowledge = [
            KnowledgeChunk(
                content="""Official EC Scoring Scale (0-5, half points):
0 - Fails to address the criterion or cannot be assessed due to missing/incomplete information
1 - Poor: criterion inadequately addressed, serious inherent weaknesses
2 - Fair: broadly addresses criterion but significant weaknesses
3 - Good: addresses criterion well but with a number of shortcomings
4 - Very good: addresses criterion very well but with a small number of shortcomings  
5 - Excellent: successfully addresses all relevant aspects; any shortcomings are minor

Key rules:
- Evaluate 'as is' - do not assume improvements
- Each criterion scored independently
- Same weakness must not be penalised under multiple criteria
- Half-point scores allowed (e.g., 3.5, 4.5)
- Score must be consistent with written comments""",
                source="EC General Annexes & Evaluation Form",
                category="official_guide",
                metadata={"type": "scoring_scale", "action_types": "RIA,IA,CSA"},
            ),
            KnowledgeChunk(
                content="""RIA/IA Evaluation Thresholds:
- Per-criterion threshold: 3/5 for each of Excellence, Impact, Implementation
- Total threshold: 10/15
- IA ranking: Impact weighted x1.5 (so effective max = 17.5)
- Two-stage calls: Stage 1 evaluates only Excellence + Impact, threshold 4/5 each, total ~8-8.5
- From 2026-2027: blind evaluation is default for two-stage calls
- Stage 1 page limit: 10 pages
- Full proposal (lump-sum): 45 pages; (non-lump-sum): 40 pages""",
                source="EC General Annexes",
                category="official_guide",
                metadata={"type": "thresholds", "action_types": "RIA,IA"},
            ),
        ]

        # ── ESR weakness patterns (from LERU, NCP, Danish analyses) ──
        esr_patterns = [
            KnowledgeChunk(
                content="""Common Excellence weaknesses from ESR analysis (LERU 2022, 129 ESRs):
1. OBJECTIVES too general: "The objectives are broadly defined but lack specificity and measurable targets"
2. SOTA inadequate: "The state-of-the-art review is superficial; key recent developments in [field] are not discussed"
3. METHODOLOGY vague: "The methodology section describes the general approach but lacks detail on specific methods, tools, and validation steps"
4. KPIs missing: "No quantified performance indicators are provided to measure progress toward objectives"
5. TRL inconsistency: "The claimed TRL advancement from X to Y is not convincingly supported by the described activities"
6. Interdisciplinarity weak: "While the proposal claims interdisciplinary approach, the actual integration of [discipline] is not evident in the work plan"
7. Open science boilerplate: "Open science practices are mentioned generically without specifying which mandatory/recommended practices will be implemented"
8. Gender dimension superficial: "Gender dimension is addressed only through team composition rather than integration into research content"

Pattern: Evaluators specifically look for OBJECTIVES → KPIs → METHODOLOGY → OUTCOMES chain coherence""",
                source="LERU ESR Analysis 2022 + Horizon Academy NCP Analysis",
                category="esr_pattern",
                                metadata={"criterion": "Excellence", "action_types": "RIA,IA,CSA"},
            ),
            KnowledgeChunk(
                content="""Common Impact weaknesses from ESR analysis:
1. PATHWAY TO IMPACT vague: "The pathway from project outputs to expected outcomes and wider impacts is not convincingly described"
2. Target groups unclear: "The proposal does not clearly identify who will benefit and how they will be reached"
3. Dissemination generic: "The dissemination plan lists standard channels (conferences, publications) without justifying why these are appropriate for the target audiences"
4. Exploitation weak: "No concrete exploitation strategy; commercial/policy uptake pathway is not substantiated"
5. KPIs for impact missing: "Impact claims are qualitative; no baselines, benchmarks, or quantified estimations provided"
6. IPR not addressed: "Intellectual property management and ownership arrangements are not discussed"
7. Sustainability absent: "No plan for sustaining results beyond the project lifetime"
8. Terminology confusion: Only ~30% of evaluator comments explicitly reference 'pathways to impact' terminology; 
   many use varied language. System must normalize: outputs → outcomes → impacts chain.

Pattern: Evaluators check alignment between project outcomes and topic-level expected outcomes from Work Programme.
The LERU analysis found that evaluators sometimes weight destination-level wider impacts differently across clusters.""",
                source="LERU ESR Analysis 2022 + Horizon Academy + Bridge2HE",
                category="esr_pattern",
                metadata={"criterion": "Impact", "action_types": "RIA,IA,CSA"},
            ),
            KnowledgeChunk(
                content="""Common Implementation weaknesses from ESR analysis:
1. WORK PLAN unclear: "The work plan lacks sufficient detail; links between WPs, tasks, and objectives are not explicit"
2. Deliverables vague: "Several deliverables are described as 'reports' without specifying content or verification criteria"
3. Milestones not decision-relevant: "Milestones are administrative (e.g., 'report submitted') rather than scientific/technical decision points"
4. RISK MITIGATION generic: "Risks are identified but mitigations are tautological (e.g., 'if delayed, we will accelerate')"
   - LERU finding: >50% of negative risk comments criticize mitigation quality, not risk identification
5. PM ALLOCATION unjustified: "The person-month distribution across partners is not justified; Partner X has significant effort but unclear role"
6. Partner role unclear: "The specific expertise and contribution of [partner] is not convincingly demonstrated"
7. Budget disproportionate: "Budget allocation does not match the described scope of activities for some partners"
8. Governance superficial: "Management structure described but decision-making mechanisms not specified"

Pattern: Danish H2020 analysis (250 proposals, 1745 comments) found 'imbalance' and 'inadequate risk management' 
among top 6 recurring weakness families. This is consistent across H2020 → Horizon Europe.""",
                source="LERU ESR Analysis + Danish UFDS Analysis + Horizon Academy",
                category="esr_pattern",
                metadata={"criterion": "Implementation", "action_types": "RIA,IA,CSA"},
            ),
            KnowledgeChunk(
                content="""Six core weakness families (cross-cutting, from Danish analysis + LERU + NCP):
1. LACK_OF_DETAIL - Sections lack specificity; claims made without supporting evidence
2. LACK_OF_QUANTIFICATION - Targets, KPIs, impact estimates not quantified
3. UNCLEAR_TARGET_GROUPS - Stakeholders/beneficiaries not specifically identified
4. RESOURCE_IMBALANCE - Person-months or budget not proportional to tasks
5. INTERNAL_INCOHERENCE - Sections contradict each other or logical chain broken
6. WEAK_RISK_MITIGATION - Risks identified but mitigations generic/tautological

These six families are remarkably stable from H2020 (2017 analysis) through Horizon Europe (2024-25).
Platform should prioritize detecting these six families first, then refine by action type.""",
                source="Danish UFDS H2020 Analysis + LERU HE Analysis synthesis",
                category="esr_pattern",
                metadata={"criterion": "all", "action_types": "all"},
            ),
            KnowledgeChunk(
                content="""MSCA-specific evaluation patterns:
- Weights: Excellence 50%, Impact 30%, Implementation 20%
- Scale: 0-100 per criterion, threshold 70/100 each and overall
- Excellence focuses heavily on: research quality + training programme + supervision
- Impact uniquely includes: researcher career development, employability, skills acquisition
- Implementation includes: recruitment strategy (must be open, transparent, merit-based, non-discriminatory)
- Secondments must be well-justified with clear learning objectives
- Non-academic sector involvement is valued
- Process: ≥3 external experts → consensus report → panel quality check → ranking
- ESR sent within ~5 months

Key difference from RIA/IA: Training and career development are CENTRAL, not peripheral.
A proposal with excellent research but weak training plan will score poorly.""",
                source="REA MSCA Evaluation Process + MSCA Work Programme",
                category="official_guide",
                metadata={"type": "msca_specific", "action_types": "MSCA-DN,MSCA-PF"},
            ),
            KnowledgeChunk(
                content="""EIC Pathfinder Open evaluation specifics:
- Thresholds: Excellence 4/5, Impact 3.5/5, Implementation 3/5
- Excellence emphasizes: long-term vision, science-to-technology breakthrough, high-risk/high-gain, novelty
- Unlike RIA/IA, incrementalism is explicitly penalized
- 'Foundational science' and 'paradigm shift' language expected
- Team quality and interdisciplinarity especially valued for high-risk research
- Budget typically up to €3-4M, consortium ≥3 from ≥2 countries

EIC Accelerator evaluation specifics:
- Short application: GO / NO GO (binary)
- Full application: per-criterion threshold 4/5, total 13/15
- After full app: jury interview → final GO / NO GO
- Focus: innovation breakthrough, market opportunity, team capability, scalability
- Single company can apply (SME focus)
- Blended finance (grant + equity) possible""",
                source="EIC Work Programme + Access2EIC",
                category="official_guide",
                metadata={"type": "eic_specific", "action_types": "EIC-Pathfinder-Open,EIC-Accelerator"},
            ),
            KnowledgeChunk(
                content="""ERC evaluation specifics:
- Single criterion: EXCELLENCE (research project + PI)
- Two sub-dimensions: (a) ground-breaking nature/ambition/feasibility of project; (b) PI intellectual capacity/creativity/commitment
- StG/CoG/AdG: two-stage, step 2 includes interview
- Synergy: three-stage
- No numeric threshold — panel-based A/B/C ranking
- PI track record assessed relative to career stage and opportunities
- Host institution suitability considered
- No consortium requirement (PI + host institution)

Key difference: No Impact or Implementation criterion. 
Everything assessed under Excellence umbrella.
PI quality is ~equal weight to project quality.""",
                source="ERC Work Programme",
                category="official_guide",
                metadata={"type": "erc_specific", "action_types": "ERC-StG,ERC-CoG,ERC-AdG,ERC-SyG"},
            ),
            KnowledgeChunk(
                content="""Evaluator process and behavior (from EC expert briefing slides):
1. Each proposal evaluated by ≥3 independent experts
2. Individual Evaluation Reports (IER) first, then consensus group discussion
3. Consensus Report (CR) produced — this usually becomes the ESR sent to applicant
4. Panel reviews for cross-call consistency and ranking of tied proposals
5. Minority opinions possible but rare

Key behavioral rules for evaluators:
- Evaluate 'as is' — do not suggest hypothetical improvements
- Comments must be justified — each criticism should point to specific weakness
- Score must be consistent with comments (positive comments + low score = problem)
- Do NOT penalize same weakness under multiple criteria
- AI tools: evaluators may NOT delegate evaluation to AI; may use AI only for ancillary tasks with confidentiality preserved

Implications for platform:
- System should produce score + confidence interval + consensus risk
- Single point estimate insufficient given multi-evaluator process
- Gray zone around thresholds (3.0, 10.0) particularly important""",
                source="EC Expert Briefing Slides 2025-2026",
                category="official_guide",
                metadata={"type": "process", "action_types": "all"},
            ),
            KnowledgeChunk(
                content="""Annotated template insights (Bridge2HE, Access2EIC):
- Evaluators read between the lines of the template structure
- Implicit quality signals expected at specific template locations:
  * After objectives: immediately show how they map to WP expected outcomes
  * SOTA section: must include recent references (last 2-3 years), patents if applicable
  * Methodology: expected to have sub-sections matching WPs
  * Gantt chart: evaluators quickly scan for timeline realism
  * Risk table: should have ≥8-10 specific risks with non-trivial mitigations
  * Partner table: should show complementarity, not just listing
  * Budget justification: big items need explicit justification
  
Bridge2HE annotated template maps real ESR comments to template sections.
Access2EIC Pathfinder template includes evaluator tips and NCP recommendations.

These sources show: evaluators don't just read official questions — 
they have learned implicit expectations about WHERE and HOW information appears.""",
                source="Bridge2HE Annotated RIA/IA Template + Access2EIC Pathfinder Template",
                category="annotated_template",
                metadata={"type": "template_insights", "action_types": "RIA,IA,EIC-Pathfinder-Open"},
            ),
        ]

        self.chunks.extend(scoring_knowledge)
        self.chunks.extend(esr_patterns)

        # Index in vector store if available
        if self.use_vector_store and self.chunks:
            self._index_chunks()

    def _index_chunks(self):
        """Index chunks in ChromaDB for vector search."""
        ids = [f"chunk_{i}" for i in range(len(self.chunks))]
        documents = [c.content for c in self.chunks]
        metadatas = [
            {
                "source": c.source,
                "category": c.category,
                **c.metadata,
            }
            for c in self.chunks
        ]

        # Check if already indexed
        existing = self.collection.count()
        if existing == 0:
            self.collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )

    def retrieve(
        self,
        query: str,
        category: Optional[str] = None,
        action_type: Optional[str] = None,
        criterion: Optional[str] = None,
        top_k: int = 5,
    ) -> List[KnowledgeChunk]:
        """Retrieve relevant knowledge chunks."""
        if self.use_vector_store:
            where_filters = {}
            if category:
                where_filters["category"] = category
            # ChromaDB doesn't support complex filters well, so we do post-filtering

            results = self.collection.query(
                query_texts=[query],
                n_results=min(top_k * 2, len(self.chunks)),
            )

            retrieved = []
            if results and results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i] if results["metadatas"] else {}
                    distance = results["distances"][0][i] if results["distances"] else 1.0

                    # Post-filter
                    if category and meta.get("category") != category:
                        continue
                    if action_type and action_type not in meta.get("action_types", "all"):
                        if meta.get("action_types") != "all":
                            continue
                    if criterion and criterion not in meta.get("criterion", "all"):
                        if meta.get("criterion") != "all":
                            continue

                    retrieved.append(KnowledgeChunk(
                        content=doc,
                        source=meta.get("source", ""),
                        category=meta.get("category", ""),
                        metadata=meta,
                        relevance_score=1.0 - distance,
                    ))

                    if len(retrieved) >= top_k:
                        break

            return retrieved
        else:
            return self._keyword_search(query, category, action_type, criterion, top_k)

    def _keyword_search(
        self,
        query: str,
        category: Optional[str],
        action_type: Optional[str],
        criterion: Optional[str],
        top_k: int,
    ) -> List[KnowledgeChunk]:
        """Fallback keyword-based search."""
        query_words = set(query.lower().split())
        scored = []

        for chunk in self.chunks:
            # Category filter
            if category and chunk.category != category:
                continue
            if action_type and action_type not in chunk.metadata.get("action_types", "all"):
                if chunk.metadata.get("action_types") != "all":
                    continue
            if criterion and criterion not in chunk.metadata.get("criterion", "all"):
                if chunk.metadata.get("criterion") != "all":
                    continue

            chunk_words = set(chunk.content.lower().split())
            overlap = len(query_words & chunk_words)
            score = overlap / max(len(query_words), 1)

            chunk_copy = KnowledgeChunk(
                content=chunk.content,
                source=chunk.source,
                category=chunk.category,
                metadata=chunk.metadata,
                relevance_score=score,
            )
            scored.append(chunk_copy)

        scored.sort(key=lambda x: x.relevance_score, reverse=True)
        return scored[:top_k]

    def get_criterion_context(
        self, criterion: str, action_type: str
    ) -> str:
        """Get all relevant context for evaluating a specific criterion."""
        chunks = self.retrieve(
            query=f"{criterion} evaluation {action_type} weaknesses strengths scoring",
            action_type=action_type,
            criterion=criterion,
            top_k=4,
        )

        if not chunks:
            chunks = self.retrieve(
                query=f"{criterion} evaluation scoring criteria",
                top_k=3,
            )

        return "\n\n---\n\n".join(c.content for c in chunks)

    def add_custom_knowledge(
        self,
        content: str,
        source: str,
        category: str,
        metadata: Optional[Dict] = None,
    ):
        """Allow users to add custom knowledge (e.g., their own ESR patterns)."""
        chunk = KnowledgeChunk(
            content=content,
            source=source,
            category=category,
            metadata=metadata or {},
        )
        self.chunks.append(chunk)

        if self.use_vector_store:
            chunk_id = f"custom_{len(self.chunks)}"
            self.collection.add(
                ids=[chunk_id],
                documents=[content],
                metadatas=[{"source": source, "category": category, **(metadata or {})}],
            )
