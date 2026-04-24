import json
import re
import streamlit as st
from openai import OpenAI


client = OpenAI(
    api_key=st.secrets["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)


MODEL_NAME = "openai/gpt-oss-120b"


SYSTEM_PROMPT = """
You are a strict Horizon Europe evaluator.

Evaluate the proposal according to Horizon Europe evaluation logic:
1. Excellence
2. Impact
3. Quality and Efficiency of Implementation

You must behave like a real evaluator:
- Penalize vague objectives.
- Penalize weak methodology.
- Penalize generic impact claims.
- Penalize unclear KPIs.
- Penalize weak dissemination, exploitation and communication plans.
- Penalize poor work package logic.
- Penalize unrealistic budgets or resources.
- Penalize weak risk management.
- Penalize unclear consortium roles.
- Do not be overly positive.
- Most proposals should not receive 5/5.
- Use half points when appropriate.
- Write comments in the style of an Evaluation Summary Report.

Return only valid JSON.
Do not include markdown.
Do not include explanations outside JSON.
"""


def extract_json(text: str) -> dict:
    """
    Safely extracts JSON from model response.
    Some free/open models may wrap JSON with extra text.
    """

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)

    if not match:
        raise ValueError("No JSON object found in model response.")

    return json.loads(match.group(0))


def build_prompt(proposal_text: str, call_info: str) -> str:
    return f"""
Evaluate the following Horizon Europe proposal.

CALL INFORMATION:
{call_info}

PROPOSAL TEXT:
{proposal_text[:45000]}

Use the official Horizon Europe scoring logic:
0 = The proposal fails to address the criterion or cannot be assessed.
1 = Poor. The criterion is inadequately addressed, or there are serious inherent weaknesses.
2 = Fair. The proposal broadly addresses the criterion, but there are significant weaknesses.
3 = Good. The proposal addresses the criterion well, but a number of shortcomings are present.
4 = Very Good. The proposal addresses the criterion very well, but a small number of shortcomings are present.
5 = Excellent. The proposal successfully addresses all relevant aspects. Any shortcomings are minor.

Individual threshold:
- Excellence: 3/5
- Impact: 3/5
- Implementation: 3/5

Overall threshold:
- 10/15

Return JSON with this exact structure:

{{
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
  "total_score": 0,
  "threshold_risk": "",
  "likely_esr_summary": "",
  "priority_actions": [],
  "funding_readiness": "",
  "confidence_level": "",
  "call_match_assessment": {{
    "alignment_score": 0,
    "in_scope_risk": "",
    "missing_call_requirements": []
  }}
}}

Scoring rules:
- Scores must be between 0 and 5.
- Use half-points when appropriate.
- Total score must be out of 15.
- Do not give 5 unless the proposal is almost flawless.
- Be critical and evaluator-like.
"""


def evaluate_proposal(proposal_text: str, call_info: str) -> dict:
    prompt = build_prompt(proposal_text, call_info)

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            extra_headers={
                "HTTP-Referer": "https://horizon-evaluator-ai.streamlit.app",
                "X-Title": "Horizon Evaluator AI",
            },
        )

        content = response.choices[0].message.content
        result = extract_json(content)

        return normalize_scores(result)

    except Exception as e:
        return {
            "error": "Evaluation failed.",
            "details": str(e),
        }


def normalize_scores(result: dict) -> dict:
    """
    Ensures scores are numeric and total score is correctly calculated.
    """

    for key in ["excellence", "impact", "implementation"]:
        try:
            result[key]["score"] = float(result[key]["score"])
        except Exception:
            result[key]["score"] = 0.0

        result[key]["score"] = max(0.0, min(5.0, result[key]["score"]))

    total = (
        result["excellence"]["score"]
        + result["impact"]["score"]
        + result["implementation"]["score"]
    )

    result["total_score"] = round(total, 1)

    if total < 10:
        result["threshold_risk"] = "High risk: below the overall Horizon Europe threshold."
    elif (
        result["excellence"]["score"] < 3
        or result["impact"]["score"] < 3
        or result["implementation"]["score"] < 3
    ):
        result["threshold_risk"] = "High risk: one or more individual criteria are below threshold."
    elif total < 12:
        result["threshold_risk"] = "Medium risk: proposal may pass threshold but is unlikely to be competitive."
    elif total < 14:
        result["threshold_risk"] = "Moderate risk: proposal is competitive but still needs strengthening."
    else:
        result["threshold_risk"] = "Low risk: proposal appears highly competitive."

    return result
