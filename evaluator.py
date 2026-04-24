import json
import re
import statistics
import streamlit as st
from openai import OpenAI


client = OpenAI(
    api_key=st.secrets["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)

MODEL_NAME = "openai/gpt-oss-120b"


REVIEWER_PERSONAS = {
    "Evaluator 1 - Strict Scientific Reviewer": """
You are a strict Horizon Europe scientific evaluator.
Focus mainly on Excellence, methodology, ambition, novelty, state of the art, TRL logic, open science and scientific credibility.
Be critical and do not over-score.
""",
    "Evaluator 2 - Impact and Policy Reviewer": """
You are a Horizon Europe impact evaluator.
Focus mainly on Impact, expected outcomes, EU policy alignment, exploitation, dissemination, communication, stakeholders, KPIs and pathway to impact.
Be critical and do not over-score.
""",
    "Evaluator 3 - Implementation and Budget Reviewer": """
You are a Horizon Europe implementation evaluator.
Focus mainly on work plan, work packages, deliverables, milestones, budget realism, partner roles, consortium capacity, governance and risk management.
Be critical and do not over-score.
"""
}


BASE_SYSTEM_PROMPT = """
You are evaluating a Horizon Europe proposal.

Use the official scoring logic:
0 = Cannot be assessed or fails to address the criterion.
1 = Poor.
2 = Fair.
3 = Good, but with shortcomings.
4 = Very good, but with minor shortcomings.
5 = Excellent, only minor issues.

Thresholds:
- Excellence: 3/5
- Impact: 3/5
- Implementation: 3/5
- Overall: 10/15

Return only valid JSON.
Do not include markdown.
"""


def extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("No JSON found in model response.")
        return json.loads(match.group(0))


def build_prompt(proposal_text: str, call_info: str, persona_name: str) -> str:
    return f"""
You are: {persona_name}

CALL INFORMATION:
{call_info}

PROPOSAL TEXT:
{proposal_text[:45000]}

Evaluate the proposal and return JSON using exactly this structure:

{{
  "reviewer": "{persona_name}",
  "excellence": {{
    "score": 0,
    "strengths": [],
    "weaknesses": [],
    "critical_comments": [],
    "recommendations": []
  }},
  "impact": {{
    "score": 0,
    "strengths": [],
    "weaknesses": [],
    "critical_comments": [],
    "recommendations": []
  }},
  "implementation": {{
    "score": 0,
    "strengths": [],
    "weaknesses": [],
    "critical_comments": [],
    "recommendations": []
  }},
  "overall_comment": "",
  "call_match_assessment": {{
    "alignment_score": 0,
    "in_scope_risk": "",
    "missing_call_requirements": []
  }}
}}

Important:
- Scores must be between 0 and 5.
- Use half-points when appropriate.
- Do not give 5 unless almost flawless.
- Be evaluator-like, concrete and critical.
"""


def normalize_single_review(result: dict) -> dict:
    for key in ["excellence", "impact", "implementation"]:
        try:
            score = float(result[key]["score"])
        except Exception:
            score = 0.0

        result[key]["score"] = max(0.0, min(5.0, score))

    total = (
        result["excellence"]["score"]
        + result["impact"]["score"]
        + result["implementation"]["score"]
    )

    result["total_score"] = round(total, 1)
    return result


def run_single_evaluator(proposal_text: str, call_info: str, persona_name: str, persona_prompt: str) -> dict:
    system_prompt = BASE_SYSTEM_PROMPT + "\n" + persona_prompt
    user_prompt = build_prompt(proposal_text, call_info, persona_name)

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.25,
        extra_headers={
            "HTTP-Referer": "https://horizon-evaluator-ai.streamlit.app",
            "X-Title": "Horizon Evaluator AI",
        },
    )

    content = response.choices[0].message.content
    result = extract_json(content)
    return normalize_single_review(result)


def calculate_confidence(scores: list) -> dict:
    if len(scores) < 2:
        return {
            "confidence_score": 50,
            "confidence_level": "Low",
            "score_variance": 0,
            "score_std": 0,
        }

    std = statistics.stdev(scores)
    variance = statistics.variance(scores)

    if std <= 0.3:
        confidence = 90
        level = "High"
    elif std <= 0.6:
        confidence = 75
        level = "Medium-High"
    elif std <= 1.0:
        confidence = 60
        level = "Medium"
    else:
        confidence = 40
        level = "Low"

    return {
        "confidence_score": confidence,
        "confidence_level": level,
        "score_variance": round(variance, 2),
        "score_std": round(std, 2),
    }


def calculate_funding_probability(total_score: float, confidence_score: int) -> int:
    """
    Simple MVP-level funding probability estimator.
    This is not a real EC probability model.
    """

    if total_score < 10:
        base = 5
    elif total_score < 11:
        base = 15
    elif total_score < 12:
        base = 30
    elif total_score < 13:
        base = 45
    elif total_score < 14:
        base = 60
    elif total_score < 14.5:
        base = 75
    else:
        base = 88

    confidence_adjustment = (confidence_score - 70) * 0.2
    probability = base + confidence_adjustment

    return int(max(1, min(95, round(probability))))


def build_consensus(reviews: list) -> dict:
    excellence_scores = [r["excellence"]["score"] for r in reviews]
    impact_scores = [r["impact"]["score"] for r in reviews]
    implementation_scores = [r["implementation"]["score"] for r in reviews]
    total_scores = [r["total_score"] for r in reviews]

    consensus_excellence = round(statistics.mean(excellence_scores), 1)
    consensus_impact = round(statistics.mean(impact_scores), 1)
    consensus_implementation = round(statistics.mean(implementation_scores), 1)
    consensus_total = round(statistics.mean(total_scores), 1)

    confidence = calculate_confidence(total_scores)
    funding_probability = calculate_funding_probability(
        consensus_total,
        confidence["confidence_score"]
    )

    if consensus_total < 10:
        threshold_risk = "High risk: below overall Horizon Europe threshold."
    elif consensus_excellence < 3 or consensus_impact < 3 or consensus_implementation < 3:
        threshold_risk = "High risk: one or more criteria are below individual threshold."
    elif consensus_total < 12:
        threshold_risk = "Medium risk: may pass threshold but unlikely to be funded."
    elif consensus_total < 14:
        threshold_risk = "Moderate risk: competitive but needs strengthening."
    else:
        threshold_risk = "Low risk: appears highly competitive."

    all_priority_actions = []

    for review in reviews:
        for section in ["excellence", "impact", "implementation"]:
            all_priority_actions.extend(review[section].get("recommendations", []))

    priority_actions = list(dict.fromkeys(all_priority_actions))[:10]

    return {
        "consensus_scores": {
            "excellence": consensus_excellence,
            "impact": consensus_impact,
            "implementation": consensus_implementation,
            "total": consensus_total,
        },
        "threshold_risk": threshold_risk,
        "confidence": confidence,
        "funding_probability": funding_probability,
        "priority_actions": priority_actions,
        "reviewer_scores": [
            {
                "reviewer": r["reviewer"],
                "excellence": r["excellence"]["score"],
                "impact": r["impact"]["score"],
                "implementation": r["implementation"]["score"],
                "total": r["total_score"],
            }
            for r in reviews
        ],
    }


def evaluate_proposal(proposal_text: str, call_info: str) -> dict:
    try:
        reviews = []

        for persona_name, persona_prompt in REVIEWER_PERSONAS.items():
            review = run_single_evaluator(
                proposal_text,
                call_info,
                persona_name,
                persona_prompt
            )
            reviews.append(review)

        consensus = build_consensus(reviews)

        return {
            "reviews": reviews,
            "consensus": consensus,
        }

    except Exception as e:
        return {
            "error": "Evaluation failed.",
            "details": str(e),
        }
