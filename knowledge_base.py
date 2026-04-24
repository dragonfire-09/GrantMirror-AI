"""
RAG Knowledge Base — built-in Horizon Europe evaluation knowledge.
Works without external vector DB (pure keyword search fallback).
"""
from dataclasses import dataclass
from typing import List, Optional, Dict


@dataclass
class KnowledgeChunk:
    content: str
    source: str
    category: str
    metadata: Dict[str, str]
    relevance_score: float = 0.0


class HorizonKnowledgeBase:
    def __init__(self):
        self.chunks: List[KnowledgeChunk] = []
        self._load_built_in()

    def _load_built_in(self):
        self.chunks = [
            KnowledgeChunk(
                content="""Official EC Scoring Scale (0-5, half points):
0 - Fails to address the criterion or cannot be assessed
1 - Poor: serious inherent weaknesses
2 - Fair: significant weaknesses
3 - Good: a number of shortcomings (THRESHOLD for RIA/IA/CSA)
4 - Very good: small number of shortcomings
5 - Excellent: only minor shortcomings
Rules: Evaluate 'as is', each criterion independently, same weakness not penalised twice, half-point allowed, score must match comments.""",
                source="EC General Annexes", category="official_guide",
                metadata={"criterion": "all", "action_types": "all"},
            ),
            KnowledgeChunk(
                content="""Common Excellence weaknesses (LERU 2022 ESR analysis, 129 ESRs + NCP analysis):
1. Objectives too general — lack specificity and measurable targets
2. SOTA inadequate — superficial, missing key recent developments
3. Methodology vague — general approach but lacks specific methods, tools, validation
4. KPIs missing — no quantified performance indicators
5. TRL inconsistency — claimed advancement not supported by described activities
6. Interdisciplinarity weak — claimed but not evident in work plan
7. Open science boilerplate — generic mention without specifying which practices
8. Gender dimension superficial — only team composition, not research content
Pattern: Evaluators look for OBJECTIVES→KPIs→METHODOLOGY→OUTCOMES chain coherence""",
                source="LERU ESR Analysis 2022 + Horizon Academy NCP Analysis",
                category="esr_pattern", metadata={"criterion": "Excellence", "action_types": "all"},
            ),
            KnowledgeChunk(
                content="""Common Impact weaknesses (ESR analysis):
1. Pathway to impact vague — not convincing logic from outputs to outcomes to impacts
2. Target groups unclear — beneficiaries not specifically identified
3. Dissemination generic — standard channels listed without justification for target audiences
4. Exploitation weak — no concrete commercial/policy uptake pathway
5. KPIs for impact missing — no baselines, benchmarks, quantified estimations
6. IPR not addressed — ownership and management not discussed
7. Sustainability absent — no plan for post-project continuation
Only ~30% of evaluator comments explicitly use 'pathways to impact' terminology.
Evaluators check alignment between project outcomes and topic-level expected outcomes from Work Programme.""",
                source="LERU + Horizon Academy + Bridge2HE", category="esr_pattern",
                metadata={"criterion": "Impact", "action_types": "all"},
            ),
            KnowledgeChunk(
                content="""Common Implementation weaknesses (ESR analysis):
1. Work plan unclear — links between WPs, tasks, objectives not explicit
2. Deliverables vague — described as 'reports' without content/verification criteria
3. Milestones administrative — not scientific/technical decision points
4. Risk mitigation tautological — 'if delayed, we will accelerate' (>50% of negative risk comments)
5. PM allocation unjustified — distribution across partners not justified
6. Partner roles unclear — specific expertise not demonstrated
7. Budget disproportionate — allocation doesn't match scope
8. Governance superficial — decision-making mechanisms not specified
Danish H2020 analysis (250 proposals, 1745 comments): 'imbalance' and 'inadequate risk management' among top 6 families.""",
                source="LERU + Danish UFDS + Horizon Academy", category="esr_pattern",
                metadata={"criterion": "Implementation", "action_types": "all"},
            ),
            KnowledgeChunk(
                content="""Six core weakness families (stable from H2020 to Horizon Europe):
1. LACK_OF_DETAIL — claims without supporting evidence
2. LACK_OF_QUANTIFICATION — targets/KPIs/impact not quantified
3. UNCLEAR_TARGET_GROUPS — stakeholders not specifically identified
4. RESOURCE_IMBALANCE — PM/budget not proportional to tasks
5. INTERNAL_INCOHERENCE — sections contradict or logic chain broken
6. WEAK_RISK_MITIGATION — risks identified but mitigations generic""",
                source="Danish UFDS + LERU synthesis", category="esr_pattern",
                metadata={"criterion": "all", "action_types": "all"},
            ),
            KnowledgeChunk(
                content="""Evaluator process (EC expert briefing):
- Each proposal: ≥3 independent experts → Individual Evaluation Reports
- Consensus group discussion → Consensus Report (usually becomes ESR)
- Panel review for cross-call consistency and ranking
- Evaluate 'as is', comments must be justified, score consistent with comments
- Do NOT penalize same weakness under multiple criteria
- AI tools: evaluators may NOT delegate evaluation to AI
- System should produce score + confidence interval + consensus risk""",
                source="EC Expert Briefing 2025-2026", category="official_guide",
                metadata={"criterion": "all", "action_types": "all"},
            ),
            KnowledgeChunk(
                content="""MSCA-specific: Weights 50/30/20, scale 0-100, threshold 70 per criterion and overall.
Excellence = research quality + training programme + supervision.
Impact = career development + employability + dissemination.
Implementation = work plan + management + recruitment strategy (must be open, transparent).
Training and career development are CENTRAL, not peripheral.""",
                source="REA MSCA Process", category="official_guide",
                metadata={"criterion": "all", "action_types": "MSCA-DN"},
            ),
            KnowledgeChunk(
                content="""EIC Pathfinder: thresholds Excellence 4, Impact 3.5, Implementation 3.
Emphasizes long-term vision, science-to-technology breakthrough, high-risk/high-gain, novelty.
Incrementalism explicitly penalized.
EIC Accelerator: short app GO/NOGO, full app 4/5 per criterion, total 13/15, then jury interview.
Focus: innovation breakthrough, market opportunity, team, scalability.""",
                source="EIC Work Programme + Access2EIC", category="official_guide",
                metadata={"criterion": "all", "action_types": "EIC-Pathfinder-Open,EIC-Accelerator"},
            ),
        ]

    def get_criterion_context(self, criterion: str, action_type: str) -> str:
        """Get all relevant context for evaluating a specific criterion."""
        relevant = []
        for chunk in self.chunks:
            crit_match = chunk.metadata.get("criterion", "all") in (criterion, "all")
            at_field = chunk.metadata.get("action_types", "all")
            at_match = at_field == "all" or action_type in at_field
            if crit_match and at_match:
                relevant.append(chunk.content)

        if not relevant:
            # Fallback: return everything
            relevant = [c.content for c in self.chunks[:3]]

        return "\n\n---\n\n".join(relevant)
