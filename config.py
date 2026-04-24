"""
GrantMirror-AI Configuration — all constants, thresholds, action type configs.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class ActionType(str, Enum):
    RIA = "RIA"
    IA = "IA"
    CSA = "CSA"
    MSCA_DN = "MSCA-DN"
    EIC_PATHFINDER_OPEN = "EIC-Pathfinder-Open"
    EIC_ACCELERATOR = "EIC-Accelerator"
    ERC_STG = "ERC-StG"


class OutputMode(str, Enum):
    ESR_SIMULATION = "esr_simulation"
    COACHING = "coaching"


@dataclass
class CriterionConfig:
    name: str
    weight: float
    threshold: float
    max_score: float
    sub_signals: List[str]
    official_questions: List[str]
    practical_checklist: List[str]


@dataclass
class ActionTypeConfig:
    action_type: ActionType
    criteria: List[CriterionConfig]
    total_threshold: float
    total_max: float
    page_limit_stage1: Optional[int]
    page_limit_full: Optional[int]
    min_consortium_size: int
    min_countries: int
    blind_evaluation: bool
    scoring_scale: str
    special_rules: List[str] = field(default_factory=list)


# ── RIA ──────────────────────────────────────────────────
_RIA_EXCELLENCE = CriterionConfig(
    name="Excellence",
    weight=1.0,
    threshold=3.0,
    max_score=5.0,
    sub_signals=[
        "objective_clarity", "ambition_beyond_sota", "methodology_soundness",
        "interdisciplinarity", "open_science", "gender_dimension", "trl_logic", "kpi_quality",
    ],
    official_questions=[
        "Clarity and pertinence of the project's objectives",
        "Soundness of the proposed methodology",
        "Credibility of the interdisciplinary approach",
        "Adequate consideration of open science practices",
        "Appropriate consideration of the gender dimension",
    ],
    practical_checklist=[
        "Are objectives SMART or at least measurable?",
        "Is the state-of-the-art review current (last 3 years)?",
        "Are patent/publication references provided for SOTA claims?",
        "Is there a clear 'why now' narrative?",
        "Is TRL entry and exit explicitly stated?",
        "Are KPIs defined with baselines and targets?",
        "Is the methodology detailed enough to be reproducible?",
        "Are open science practices addressed specifically (not boilerplate)?",
        "Is the gender dimension integrated into research content?",
        "Is AI use addressed with robustness/reliability if applicable?",
    ],
)

_RIA_IMPACT = CriterionConfig(
    name="Impact",
    weight=1.0,
    threshold=3.0,
    max_score=5.0,
    sub_signals=[
        "pathway_to_impact", "expected_outcomes_alignment", "stakeholder_engagement",
        "exploitation_plan", "dissemination_plan", "communication_plan",
        "ipr_management", "kpi_impact", "wider_societal_impact",
    ],
    official_questions=[
        "Credibility of the pathways to achieve the expected outcomes and impacts",
        "Suitability of the measures to maximise expected outcomes and impacts",
        "Quality of the proposed measures to exploit and disseminate the project results",
    ],
    practical_checklist=[
        "Is there a clear logic chain: outputs to outcomes to impacts?",
        "Are WP expected outcomes aligned with topic expected outcomes?",
        "Are target groups identified with specificity?",
        "Is exploitation strategy concrete (not generic)?",
        "Are dissemination channels justified (not just listed)?",
        "Are baselines, benchmarks and assumptions stated for impact claims?",
        "Are quantified estimations provided?",
        "Is IPR ownership and management addressed?",
        "Is there a sustainability plan post-project?",
    ],
)

_RIA_IMPLEMENTATION = CriterionConfig(
    name="Implementation",
    weight=1.0,
    threshold=3.0,
    max_score=5.0,
    sub_signals=[
        "workplan_coherence", "wp_task_deliverable_alignment", "milestone_quality",
        "risk_management", "mitigation_specificity", "resource_allocation",
        "pm_justification", "partner_role_fit", "budget_justification",
        "governance", "timeline_realism",
    ],
    official_questions=[
        "Quality and effectiveness of the work plan",
        "Appropriateness of the management structures and procedures",
        "Complementarity of the participants and extent to which the consortium has the necessary expertise",
        "Appropriateness of the allocation of tasks and resources",
    ],
    practical_checklist=[
        "Is each WP clearly linked to objectives?",
        "Are deliverables concrete and verifiable?",
        "Are milestones decision-relevant (not just report submitted)?",
        "Are risks specific (not generic categories)?",
        "Are mitigations non-tautological and actionable?",
        "Is person-month allocation justified per partner?",
        "Is any partner role unclear or underspecified?",
        "Is the budget proportional to tasks?",
        "Is the Gantt chart / timeline realistic?",
        "Is governance described with decision-making mechanisms?",
    ],
)

RIA_CONFIG = ActionTypeConfig(
    action_type=ActionType.RIA,
    criteria=[_RIA_EXCELLENCE, _RIA_IMPACT, _RIA_IMPLEMENTATION],
    total_threshold=10.0,
    total_max=15.0,
    page_limit_stage1=10,
    page_limit_full=45,
    min_consortium_size=3,
    min_countries=2,
    blind_evaluation=True,
    scoring_scale="0-5_half",
    special_rules=[
        "Evaluate proposal 'as is' — do not suggest improvements in ESR mode",
        "Same weakness must not be penalised under multiple criteria",
        "Lump-sum: budget coherence checked differently",
    ],
)

# ── IA ───────────────────────────────────────────────────
IA_CONFIG = ActionTypeConfig(
    action_type=ActionType.IA,
    criteria=[
        CriterionConfig(
            name="Excellence", weight=1.0, threshold=3.0, max_score=5.0,
            sub_signals=_RIA_EXCELLENCE.sub_signals,
            official_questions=_RIA_EXCELLENCE.official_questions,
            practical_checklist=_RIA_EXCELLENCE.practical_checklist + [
                "Is the innovation beyond current market offerings clear?",
            ],
        ),
        CriterionConfig(
            name="Impact", weight=1.5, threshold=3.0, max_score=5.0,
            sub_signals=_RIA_IMPACT.sub_signals + ["market_analysis", "business_model"],
            official_questions=_RIA_IMPACT.official_questions,
            practical_checklist=_RIA_IMPACT.practical_checklist + [
                "Is there a credible market analysis?",
                "Is the business model or adoption pathway described?",
            ],
        ),
        _RIA_IMPLEMENTATION,
    ],
    total_threshold=10.0,
    total_max=17.5,
    page_limit_stage1=10,
    page_limit_full=45,
    min_consortium_size=3,
    min_countries=2,
    blind_evaluation=True,
    scoring_scale="0-5_half",
    special_rules=["Impact weight is 1.5 for ranking purposes"],
)

# ── CSA ──────────────────────────────────────────────────
CSA_CONFIG = ActionTypeConfig(
    action_type=ActionType.CSA,
    criteria=[
        CriterionConfig(
            name="Excellence", weight=1.0, threshold=3.0, max_score=5.0,
            sub_signals=["objective_clarity", "concept_quality", "methodology_soundness", "stakeholder_mapping"],
            official_questions=["Clarity and pertinence of the project's objectives",
                                "Quality of the proposed coordination/support activities"],
            practical_checklist=["Are coordination/support objectives clearly defined?",
                                 "Is the methodology for achieving coordination goals sound?",
                                 "Are relevant stakeholders identified?"],
        ),
        CriterionConfig(
            name="Impact", weight=1.0, threshold=3.0, max_score=5.0,
            sub_signals=["pathway_to_impact", "policy_relevance", "dissemination_plan", "sustainability"],
            official_questions=_RIA_IMPACT.official_questions,
            practical_checklist=["Is policy relevance clearly demonstrated?",
                                 "Are coordination outcomes measurable?",
                                 "Is there a sustainability plan?"],
        ),
        CriterionConfig(
            name="Implementation", weight=1.0, threshold=3.0, max_score=5.0,
            sub_signals=["workplan_coherence", "resource_allocation", "governance"],
            official_questions=_RIA_IMPLEMENTATION.official_questions,
            practical_checklist=_RIA_IMPLEMENTATION.practical_checklist,
        ),
    ],
    total_threshold=10.0, total_max=15.0,
    page_limit_stage1=None, page_limit_full=40,
    min_consortium_size=1, min_countries=1,
    blind_evaluation=False, scoring_scale="0-5_half", special_rules=[],
)

# ── MSCA-DN ──────────────────────────────────────────────
MSCA_DN_CONFIG = ActionTypeConfig(
    action_type=ActionType.MSCA_DN,
    criteria=[
        CriterionConfig(
            name="Excellence", weight=0.5, threshold=70.0, max_score=100.0,
            sub_signals=["research_quality", "training_programme", "supervision_quality",
                         "interdisciplinarity", "open_science", "gender_dimension"],
            official_questions=["Quality and pertinence of the research programme",
                                "Quality and innovative nature of the training programme",
                                "Quality of the supervision arrangements"],
            practical_checklist=["Is each DC research project clearly defined?",
                                 "Is the training programme structured with transferable skills?",
                                 "Is supervision dual (academic + non-academic)?",
                                 "Are secondments well justified?"],
        ),
        CriterionConfig(
            name="Impact", weight=0.3, threshold=70.0, max_score=100.0,
            sub_signals=["career_development", "employability", "dissemination", "communication", "exploitation"],
            official_questions=["Contribution to structuring doctoral training",
                                "Credibility of the measures to enhance career perspectives",
                                "Suitability of the measures to maximise impact"],
            practical_checklist=["Is researcher employability concretely addressed?",
                                 "Are career development measures specific?",
                                 "Are dissemination plans researcher-centred?"],
        ),
        CriterionConfig(
            name="Implementation", weight=0.2, threshold=70.0, max_score=100.0,
            sub_signals=["workplan_coherence", "consortium_quality", "management", "recruitment_strategy"],
            official_questions=["Coherence and effectiveness of the work plan",
                                "Appropriateness of the management structure",
                                "Quality of the consortium",
                                "Appropriate recruitment strategy"],
            practical_checklist=["Is the recruitment strategy open and transparent?",
                                 "Is the management structure clearly described?",
                                 "Are partner roles and contributions balanced?"],
        ),
    ],
    total_threshold=70.0, total_max=100.0,
    page_limit_stage1=None, page_limit_full=30,
    min_consortium_size=3, min_countries=2,
    blind_evaluation=False, scoring_scale="0-100",
    special_rules=["Weights: Excellence 50%, Impact 30%, Implementation 20%",
                    "Per-criterion threshold: 70/100", "Overall threshold: 70/100 weighted"],
)

# ── EIC Pathfinder Open ──────────────────────────────────
EIC_PATHFINDER_OPEN_CONFIG = ActionTypeConfig(
    action_type=ActionType.EIC_PATHFINDER_OPEN,
    criteria=[
        CriterionConfig(
            name="Excellence", weight=1.0, threshold=4.0, max_score=5.0,
            sub_signals=["long_term_vision", "breakthrough_potential", "high_risk_high_gain",
                         "novelty", "foundational_science", "interdisciplinarity"],
            official_questions=["Long term vision", "Science-towards-technology breakthrough",
                                "Novelty and ambition of the research"],
            practical_checklist=["Is the long-term transformative vision compelling?",
                                 "Is the science-to-technology breakthrough clearly articulated?",
                                 "Is the high-risk/high-gain nature evident?",
                                 "Is this genuinely novel or incremental improvement?"],
        ),
        CriterionConfig(
            name="Impact", weight=1.0, threshold=3.5, max_score=5.0,
            sub_signals=["innovation_potential", "transformation_pathway", "societal_impact"],
            official_questions=["Innovation potential",
                                "Potential for future societal and economic impact"],
            practical_checklist=["Is the innovation potential beyond current paradigms?",
                                 "Is the pathway from research to eventual application sketched?"],
        ),
        CriterionConfig(
            name="Implementation", weight=1.0, threshold=3.0, max_score=5.0,
            sub_signals=["workplan_quality", "team_quality", "resource_allocation"],
            official_questions=["Quality and efficiency of the implementation"],
            practical_checklist=["Is the team capable of this high-risk research?",
                                 "Is the work plan appropriate for exploratory research?"],
        ),
    ],
    total_threshold=12.0, total_max=15.0,
    page_limit_stage1=None, page_limit_full=25,
    min_consortium_size=3, min_countries=2,
    blind_evaluation=False, scoring_scale="0-5_half",
    special_rules=["Excellence threshold: 4.0", "Impact threshold: 3.5",
                    "Implementation threshold: 3.0", "Focus on high-risk/high-gain"],
)

# ── EIC Accelerator ──────────────────────────────────────
EIC_ACCELERATOR_CONFIG = ActionTypeConfig(
    action_type=ActionType.EIC_ACCELERATOR,
    criteria=[
        CriterionConfig(
            name="Excellence", weight=1.0, threshold=4.0, max_score=5.0,
            sub_signals=["innovation_breakthrough", "technology_readiness", "ip_position", "competitive_advantage"],
            official_questions=["Breakthrough nature of the innovation",
                                "Maturity/readiness of the innovation", "Competitive position and IP"],
            practical_checklist=["Is the innovation clearly beyond existing solutions?",
                                 "Is TRL accurately assessed with evidence?",
                                 "Is IP position strong and defensible?"],
        ),
        CriterionConfig(
            name="Impact", weight=1.0, threshold=4.0, max_score=5.0,
            sub_signals=["market_opportunity", "scalability", "team_capability", "commercialisation_strategy"],
            official_questions=["Scale of the market opportunity",
                                "Team capability to deliver", "Commercialisation strategy"],
            practical_checklist=["Is market size and growth substantiated?",
                                 "Is the go-to-market strategy concrete?",
                                 "Does the team have commercial track record?"],
        ),
        CriterionConfig(
            name="Implementation", weight=1.0, threshold=4.0, max_score=5.0,
            sub_signals=["workplan_quality", "risk_management", "milestones", "financial_plan"],
            official_questions=["Quality of the work plan and risk management",
                                "Adequacy of the financial plan"],
            practical_checklist=["Is the development roadmap realistic?",
                                 "Are financial projections credible?",
                                 "Are risks well identified with mitigation?"],
        ),
    ],
    total_threshold=13.0, total_max=15.0,
    page_limit_stage1=None, page_limit_full=None,
    min_consortium_size=1, min_countries=1,
    blind_evaluation=False, scoring_scale="0-5_half",
    special_rules=["Short application: GO / NO GO",
                    "Full application: per-criterion threshold 4/5, total 13/15",
                    "Jury interview follows full application"],
)

# ── ERC StG ──────────────────────────────────────────────
ERC_STG_CONFIG = ActionTypeConfig(
    action_type=ActionType.ERC_STG,
    criteria=[
        CriterionConfig(
            name="Excellence", weight=1.0, threshold=0.0, max_score=0.0,
            sub_signals=["groundbreaking_nature", "methodology_feasibility",
                         "pi_intellectual_capacity", "pi_creativity", "pi_track_record"],
            official_questions=["Ground-breaking nature, ambition and feasibility of the research project",
                                "Intellectual capacity, creativity and commitment of the PI"],
            practical_checklist=["Is the research question genuinely frontier?",
                                 "Is the PI track record exceptional for career stage?",
                                 "Is the methodology feasible within the timeframe?",
                                 "Is the host institution suitable?"],
        ),
    ],
    total_threshold=0.0, total_max=0.0,
    page_limit_stage1=5, page_limit_full=15,
    min_consortium_size=1, min_countries=1,
    blind_evaluation=False, scoring_scale="panel_abc",
    special_rules=["Single criterion: Excellence", "Two-stage with interview at step 2",
                    "Panel-based ranking, not numeric threshold"],
)

# ── Registry ─────────────────────────────────────────────
ACTION_TYPE_CONFIGS: Dict[ActionType, ActionTypeConfig] = {
    ActionType.RIA: RIA_CONFIG,
    ActionType.IA: IA_CONFIG,
    ActionType.CSA: CSA_CONFIG,
    ActionType.MSCA_DN: MSCA_DN_CONFIG,
    ActionType.EIC_PATHFINDER_OPEN: EIC_PATHFINDER_OPEN_CONFIG,
    ActionType.EIC_ACCELERATOR: EIC_ACCELERATOR_CONFIG,
    ActionType.ERC_STG: ERC_STG_CONFIG,
}

SCORE_DESCRIPTORS_0_5 = {
    0: "Fails to address the criterion or cannot be assessed",
    1: "Poor - serious inherent weaknesses",
    2: "Fair - significant weaknesses",
    3: "Good - a number of shortcomings",
    4: "Very good - small number of shortcomings",
    5: "Excellent - only minor shortcomings",
}

WEAKNESS_TAXONOMY = {
    "LACK_OF_DETAIL": {"label": "Insufficient Detail", "description": "Claims made without supporting detail"},
    "LACK_OF_QUANTIFICATION": {"label": "Missing Quantification", "description": "Targets/KPIs/impact estimates not quantified"},
    "UNCLEAR_TARGET_GROUPS": {"label": "Unclear Target Groups", "description": "Stakeholders/beneficiaries not specifically identified"},
    "RESOURCE_IMBALANCE": {"label": "Resource Imbalance", "description": "Person-months or budget not proportional to tasks"},
    "INTERNAL_INCOHERENCE": {"label": "Internal Incoherence", "description": "Sections contradict each other or logic chain broken"},
    "WEAK_RISK_MITIGATION": {"label": "Weak Risk Mitigation", "description": "Risks identified but mitigations generic/tautological"},
    "GENERIC_OPEN_SCIENCE": {"label": "Generic Open Science", "description": "Open science addressed with boilerplate"},
    "SOTA_GAP": {"label": "State-of-the-Art Gap", "description": "SOTA review missing, outdated, or insufficient"},
    "GENERIC_DISSEMINATION": {"label": "Generic Dissemination", "description": "D&E plan lists channels without justification"},
    "PATHWAY_VAGUE": {"label": "Vague Pathway to Impact", "description": "Logic chain from outputs to impacts not convincing"},
    "TRL_INCONSISTENCY": {"label": "TRL Inconsistency", "description": "TRL entry/exit unclear or inconsistent"},
    "PARTNER_ROLE_UNCLEAR": {"label": "Unclear Partner Roles", "description": "Partner involvement not justified"},
}
