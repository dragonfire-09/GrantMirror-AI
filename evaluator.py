"""
Multi-agent evaluator system for Horizon Europe proposals.
Implements criterion-level evaluation with evidence-linked scoring.
Produces both ESR simulation and coaching outputs.
"""
import json
import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

from config import (
    ActionType,
    ActionTypeConfig,
    ACTION_TYPE_CONFIGS,
    CriterionConfig,
    SCORE_DESCRIPTORS_0_5,
    WEAKNESS_TAXONOMY,
    OutputMode,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
)
from document_parser import ParsedProposal, SectionType
from knowledge_base import HorizonKnowledgeBase

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


# ── Data structures ─────────────────────────────────────

@dataclass
class EvidenceLink:
    """Links a comment to specific proposal content."""
    claim: str
    source_text: str  # The actual text from proposal
    location: str  # Section/page reference
    assessment: str  # "strength", "weakness", "missing"


@dataclass
class SubSignalAssessment:
    signal_name: str
    score_contribution: str  # "strong", "adequate", "weak", "missing"
    evidence: List[EvidenceLink]
    comment: str


@dataclass
class CriterionEvaluation:
    criterion_name: str
    score: float
    confidence_low: float
    confidence_high: float
    consensus_risk: str  # "low", "medium", "high"
    strengths: List[str]
    weaknesses: List[str]
    weakness_categories: List[str]  # From WEAKNESS_TAXONOMY
    sub_signal_assessments: List[SubSignalAssessment]
    esr_comment: str  # Official ESR-style comment
    coaching_comment: str  # Actionable improvement advice
    evidence_links: List[EvidenceLink]


@dataclass
class ProposalEvaluation:
    action_type: ActionType
    criteria_evaluations: List[CriterionEvaluation]
    total_score: float
    total_weighted_score: float
    threshold_met: bool
    per_criterion_threshold_met: Dict[str, bool]
    funding_probability: str  # "high", "medium", "low", "very_low"
    overall_esr_summary: str
    overall_coaching_summary: str
    cross_cutting_issues: List[str]
    top_priority_improvements: List[str]


# ── Prompt templates ────────────────────────────────────

SYSTEM_PROMPT_ESR = """You are an experienced Horizon Europe evaluator. You have evaluated hundreds of proposals 
across multiple Framework Programmes. You follow EC evaluation rules strictly:

RULES:
1. Evaluate the proposal 'as is' — do NOT suggest improvements or assume fixes
2. Every criticism must point to a specific weakness in the text
3. Every positive comment must point to a specific strength in the text  
4. Score must be CONSISTENT with your written comments
5. Do NOT penalize the same weakness under multiple criteria
6. Use the official EC scoring scale:
   0 = fails to address / cannot assess
   1 = poor, serious weaknesses
   2 = fair, significant weaknesses  
   3 = good, number of shortcomings
   4 = very good, small number of shortcomings
   5 = excellent, only minor shortcomings
7. Half-point scores (e.g., 3.5, 4.5) are allowed
8. Be specific, evidence-based, and professional
9. Write in third person ("The proposal...", "The methodology...")
10. Keep comments concise but substantive — like a real ESR"""

SYSTEM_PROMPT_COACH = """You are an expert Horizon Europe proposal consultant with deep knowledge of 
evaluation patterns. Your role is to help applicants IMPROVE their proposals. 

Unlike an evaluator (who assesses 'as is'), you:
1. Identify specific weaknesses and explain WHY they hurt the score
2. Provide CONCRETE, ACTIONABLE revision suggestions
3. Prioritize improvements by expected score impact
4. Reference common evaluator expectations from ESR analysis
5. Be constructive but honest — don't soften critical issues"""


def build_criterion_prompt(
    criterion_config: CriterionConfig,
    section_text: str,
    full_proposal_text: str,
    knowledge_context: str,
    action_type: str,
    call_context: Optional[str] = None,
) -> str:
    """Build the evaluation prompt for a specific criterion."""

    official_questions = "\n".join(
        f"  - {q}" for q in criterion_config.official_questions
    )
    practical_checks = "\n".join(
        f"  - {c}" for c in criterion_config.practical_checklist
    )
    sub_signals = ", ".join(criterion_config.sub_signals)

    prompt = f"""## EVALUATION TASK

Evaluate the **{criterion_config.name}** criterion of this {action_type} proposal.

### OFFICIAL EVALUATION QUESTIONS (from EC form):
{official_questions}

### PRACTICAL QUALITY SIGNALS TO CHECK:
{practical_checks}

### SUB-SIGNALS TO ASSESS:
{sub_signals}

### SCORING SCALE:
- 0: Fails to address the criterion
- 1: Poor — serious inherent weaknesses
- 2: Fair — significant weaknesses
- 3: Good — a number of shortcomings (threshold)
- 4: Very good — small number of shortcomings
- 5: Excellent — only minor shortcomings
Half-point scores allowed.

### THRESHOLD:
- Per-criterion threshold: {criterion_config.threshold}/{criterion_config.max_score}

### RELEVANT KNOWLEDGE (from guidelines and ESR analysis):
{knowledge_context}

"""
    if call_context:
        prompt += f"""### CALL/TOPIC SPECIFIC CONTEXT:
{call_context}

"""

    prompt += f"""### PROPOSAL SECTION TEXT:
{section_text[:12000]}

### FULL PROPOSAL CONTEXT (for cross-reference):
{full_proposal_text[:4000]}

### REQUIRED OUTPUT FORMAT (respond in valid JSON):
{{
    "criterion": "{criterion_config.name}",
    "score": <float 0.0-5.0, half-point increments>,
    "confidence_low": <float>,
    "confidence_high": <float>,
    "consensus_risk": "<low|medium|high>",
    "strengths": ["<specific strength with evidence>", ...],
    "weaknesses": ["<specific weakness with evidence>", ...],
    "weakness_categories": ["<from taxonomy: LACK_OF_DETAIL, LACK_OF_QUANTIFICATION, UNCLEAR_TARGET_GROUPS, RESOURCE_IMBALANCE, INTERNAL_INCOHERENCE, WEAK_RISK_MITIGATION, GENERIC_OPEN_SCIENCE, SOTA_GAP, GENERIC_DISSEMINATION, PATHWAY_VAGUE, TRL_INCONSISTENCY, PARTNER_ROLE_UNCLEAR>"],
    "sub_signal_assessments": [
        {{
            "signal": "<signal_name>",
            "rating": "<strong|adequate|weak|missing>",
            "evidence": "<quote or reference from proposal>",
            "comment": "<brief assessment>"
        }}
    ],
    "esr_comment": "<Professional ESR-style paragraph: strengths then weaknesses, no suggestions, evidence-based, consistent with score>",
    "alternative_reading": "<If score is near threshold (3.0±0.5), describe how a different evaluator might read this differently>"
}}

IMPORTANT: 
- Every strength/weakness MUST reference specific content from the proposal
- Score MUST be consistent with the balance of strengths vs weaknesses
- If information is MISSING, that is a weakness — do not assume it exists elsewhere
- Do NOT penalize weaknesses that belong to other criteria"""

    return prompt


class HorizonEvaluator:
    """Multi-agent evaluation system."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        knowledge_base: Optional[HorizonKnowledgeBase] = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.kb = knowledge_base or HorizonKnowledgeBase()

        if HAS_OPENAI and self.api_key:
            self.client = OpenAI(api_key=self.api_key)
            self.llm_available = True
        else:
            self.client = None
            self.llm_available = False

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call the LLM API."""
        if not self.llm_available:
            return self._generate_fallback_response()

        try:
            response = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS,
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content
        except Exception as e:
            return json.dumps({
                "error": str(e),
                "criterion": "unknown",
                "score": 0,
                "strengths": [],
                "weaknesses": [f"LLM evaluation failed: {str(e)}"],
                "esr_comment": "Evaluation could not be completed due to a technical error.",
            })

    def _generate_fallback_response(self) -> str:
        """Generate a structured fallback when LLM is not available."""
        return json.dumps({
            "criterion": "unknown",
            "score": 0,
            "confidence_low": 0,
            "confidence_high": 0,
            "consensus_risk": "high",
            "strengths": [],
            "weaknesses": ["LLM not available — manual evaluation required"],
            "weakness_categories": [],
            "sub_signal_assessments": [],
            "esr_comment": "Automated evaluation not available. Please configure an LLM API key.",
            "alternative_reading": "",
        })

    def _get_section_text(
        self, proposal: ParsedProposal, criterion_name: str
    ) -> str:
        """Get the relevant section text for a criterion."""
        section_map = {
            "Excellence": SectionType.EXCELLENCE,
            "Impact": SectionType.IMPACT,
            "Implementation": SectionType.IMPLEMENTATION,
        }

        section_type = section_map.get(criterion_name)
        if section_type and section_type in proposal.sections:
            return proposal.sections[section_type].content

        # Fallback: try to find in full text
        return proposal.full_text[:8000]

    def evaluate_criterion(
        self,
        proposal: ParsedProposal,
        criterion_config: CriterionConfig,
        action_type: ActionType,
        call_context: Optional[str] = None,
    ) -> CriterionEvaluation:
        """Evaluate a single criterion."""
        # Get section text
        section_text = self._get_section_text(proposal, criterion_config.name)

        # Get knowledge context
        knowledge_context = self.kb.get_criterion_context(
            criterion=criterion_config.name,
            action_type=action_type.value,
        )

        # Build and send prompt
        user_prompt = build_criterion_prompt(
            criterion_config=criterion_config,
            section_text=section_text,
            full_proposal_text=proposal.full_text[:4000],
            knowledge_context=knowledge_context,
            action_type=action_type.value,
            call_context=call_context,
        )

        raw_response = self._call_llm(SYSTEM_PROMPT_ESR, user_prompt)

        # Parse response
        try:
            result = json.loads(raw_response)
        except json.JSONDecodeError:
            result = {
                "score": 0,
                "confidence_low": 0,
                "confidence_high": 0,
                "consensus_risk": "high",
                "strengths": [],
                "weaknesses": ["Failed to parse evaluation response"],
                "weakness_categories": [],
                "sub_signal_assessments": [],
                "esr_comment": "Evaluation parsing error.",
                "alternative_reading": "",
            }

        # Build sub-signal assessments
        sub_assessments = []
        for sa in result.get("sub_signal_assessments", []):
            sub_assessments.append(SubSignalAssessment(
                signal_name=sa.get("signal", ""),
                score_contribution=sa.get("rating", "unknown"),
                evidence=[EvidenceLink(
                    claim=sa.get("comment", ""),
                    source_text=sa.get("evidence", ""),
                    location=criterion_config.name,
                    assessment=sa.get("rating", "unknown"),
                )],
                comment=sa.get("comment", ""),
            ))

        # Build evidence links from strengths and weaknesses
        evidence_links = []
        for s in result.get("strengths", []):
            evidence_links.append(EvidenceLink(
                claim=s,
                source_text="",
                location=criterion_config.name,
                assessment="strength",
            ))
        for w in result.get("weaknesses", []):
            evidence_links.append(EvidenceLink(
                claim=w,
                source_text="",
                location=criterion_config.name,
                assessment="weakness",
            ))

        # Generate coaching comment separately
        coaching_comment = self._generate_coaching_comment(
            criterion_config, result, section_text
        )

        score = float(result.get("score", 0))
        conf_low = float(result.get("confidence_low", max(0, score - 0.5)))
        conf_high = float(result.get("confidence_high", min(5, score + 0.5)))

        return CriterionEvaluation(
            criterion_name=criterion_config.name,
            score=score,
            confidence_low=conf_low,
            confidence_high=conf_high,
            consensus_risk=result.get("consensus_risk", "medium"),
            strengths=result.get("strengths", []),
            weaknesses=result.get("weaknesses", []),
            weakness_categories=result.get("weakness_categories", []),
            sub_signal_assessments=sub_assessments,
            esr_comment=result.get("esr_comment", ""),
            coaching_comment=coaching_comment,
            evidence_links=evidence_links,
        )

    def _generate_coaching_comment(
        self,
        criterion_config: CriterionConfig,
        eval_result: dict,
        section_text: str,
    ) -> str:
        """Generate coaching/improvement advice separately from ESR comment."""
        if not self.llm_available:
            weaknesses = eval_result.get("weaknesses", [])
            if weaknesses:
                return "Priority improvements:\n" + "\n".join(
                    f"• Address: {w}" for w in weaknesses
                )
            return "No specific improvements identified."

        weaknesses = eval_result.get("weaknesses", [])
        categories = eval_result.get("weakness_categories", [])

        coaching_prompt = f"""Based on this evaluation of the {criterion_config.name} criterion:

Score: {eval_result.get('score', 'N/A')}
Weaknesses found: {json.dumps(weaknesses)}
Weakness categories: {json.dumps(categories)}

Section text (excerpt): {section_text[:3000]}

Provide SPECIFIC, ACTIONABLE improvement recommendations:
1. Prioritize by expected score impact (highest impact first)
2. For each weakness, explain WHAT to change and HOW
3. Reference the practical checklist items: {json.dumps(criterion_config.practical_checklist[:5])}
4. Be concrete — "add a table showing..." not "improve the methodology"

Format as a numbered list of improvements."""

        try:
            response = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_COACH},
                    {"role": "user", "content": coaching_prompt},
                ],
                temperature=0.4,
                max_tokens=2000,
            )
            return response.choices[0].message.content
        except Exception:
            return "Coaching comment generation failed."

    def evaluate_proposal(
        self,
        proposal: ParsedProposal,
        action_type: ActionType,
        call_context: Optional[str] = None,
    ) -> ProposalEvaluation:
        """Full proposal evaluation across all criteria."""
        config = ACTION_TYPE_CONFIGS[action_type]
        criteria_evals = []

        for criterion_config in config.criteria:
            eval_result = self.evaluate_criterion(
                proposal=proposal,
                criterion_config=criterion_config,
                action_type=action_type,
                call_context=call_context,
            )
            criteria_evals.append(eval_result)

        # Calculate totals
        total_score = sum(e.score for e in criteria_evals)
        total_weighted = sum(
            e.score * c.weight
            for e, c in zip(criteria_evals, config.criteria)
        )

        # Check thresholds
        per_criterion_met = {}
        for e, c in zip(criteria_evals, config.criteria):
            per_criterion_met[e.criterion_name] = e.score >= c.threshold

        all_criteria_met = all(per_criterion_met.values())
        total_met = total_weighted >= config.total_threshold
        threshold_met = all_criteria_met and total_met

        # Funding probability estimate
        if not threshold_met:
            funding_prob = "very_low"
        elif total_weighted >= config.total_threshold + 3:
            funding_prob = "high"
        elif total_weighted >= config.total_threshold + 1.5:
            funding_prob = "medium"
        else:
            funding_prob = "low"

        # Cross-cutting issues
        cross_cutting = self._detect_cross_cutting_issues(criteria_evals)

        # Priority improvements
        priorities = self._prioritize_improvements(criteria_evals, config)

        # Overall summaries
        overall_esr = self._generate_overall_esr(criteria_evals, config)
        overall_coaching = self._generate_overall_coaching(
            criteria_evals, priorities, config
        )

        return ProposalEvaluation(
            action_type=action_type,
            criteria_evaluations=criteria_evals,
            total_score=total_score,
            total_weighted_score=total_weighted,
            threshold_met=threshold_met,
            per_criterion_threshold_met=per_criterion_met,
            funding_probability=funding_prob,
            overall_esr_summary=overall_esr,
            overall_coaching_summary=overall_coaching,
            cross_cutting_issues=cross_cutting,
            top_priority_improvements=priorities,
        )

    def _detect_cross_cutting_issues(
        self, criteria_evals: List[CriterionEvaluation]
    ) -> List[str]:
        """Detect issues that appear across multiple criteria."""
        all_categories = []
        for e in criteria_evals:
            all_categories.extend(e.weakness_categories)

        # Count categories
        from collections import Counter
        counts = Counter(all_categories)

        issues = []
        for cat, count in counts.items():
            if count > 1 and cat in WEAKNESS_TAXONOMY:
                tax = WEAKNESS_TAXONOMY[cat]
                issues.append(
                    f"⚠️ '{tax['label']}' detected across {count} criteria — "
                    f"this is a systemic issue: {tax['description']}"
                )

        # Check for double-penalization risk
        weakness_texts = []
        for e in criteria_evals:
            weakness_texts.extend(
                (e.criterion_name, w) for w in e.weaknesses
            )

        # Simple duplicate detection
        seen_keywords = {}
        for criterion, weakness in weakness_texts:
            words = set(weakness.lower().split())
            for prev_criterion, prev_words in seen_keywords.items():
                if prev_criterion != criterion:
                    overlap = len(words & prev_words) / max(len(words), 1)
                    if overlap > 0.6:
                        issues.append(
                            f"⚠️ Potential double-penalization: similar weakness "
                            f"noted in both {prev_criterion} and {criterion}"
                        )
            seen_keywords[criterion] = words

        return issues

    def _prioritize_improvements(
        self,
        criteria_evals: List[CriterionEvaluation],
        config: ActionTypeConfig,
    ) -> List[str]:
        """Prioritize improvements by expected score impact."""
        improvements = []

        for eval_result, criterion_config in zip(criteria_evals, config.criteria):
            weight = criterion_config.weight
            gap = criterion_config.max_score - eval_result.score

            if gap <= 0:
                continue

            priority = gap * weight  # Higher weight & bigger gap = higher priority

            for weakness in eval_result.weaknesses:
                improvements.append((priority, eval_result.criterion_name, weakness))

        improvements.sort(key=lambda x: x[0], reverse=True)
        return [
            f"[{name}] {weakness}" for _, name, weakness in improvements[:10]
        ]

    def _generate_overall_esr(
        self,
        criteria_evals: List[CriterionEvaluation],
        config: ActionTypeConfig,
    ) -> str:
        """Generate overall ESR-style summary."""
        lines = []
        for e in criteria_evals:
            lines.append(f"**{e.criterion_name}** ({e.score}/{5.0}):")
            lines.append(e.esr_comment)
            lines.append("")

        total = sum(e.score for e in criteria_evals)
        total_w = sum(
            e.score * c.weight
            for e, c in zip(criteria_evals, config.criteria)
        )
        lines.append(f"**Total Score**: {total_w:.1f}/{config.total_max}")
        lines.append(
            f"**Threshold**: {'Met ✅' if total_w >= config.total_threshold else 'Not met ❌'} "
            f"(required: {config.total_threshold})"
        )

        return "\n".join(lines)

    def _generate_overall_coaching(
        self,
        criteria_evals: List[CriterionEvaluation],
        priorities: List[str],
        config: ActionTypeConfig,
    ) -> str:
        """Generate overall coaching summary."""
        lines = ["## 🎯 Priority Improvement Plan\n"]

        if priorities:
            lines.append("### Top improvements by expected score impact:")
            for i, p in enumerate(priorities, 1):
                lines.append(f"{i}. {p}")
            lines.append("")

        lines.append("### Per-criterion coaching:")
        for e in criteria_evals:
            lines.append(f"\n#### {e.criterion_name} ({e.score}/5.0)")
            lines.append(e.coaching_comment)

        return "\n".join(lines)
