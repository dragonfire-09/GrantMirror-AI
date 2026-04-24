import json
from openai import OpenAI
import streamlit as st


client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])


SYSTEM_PROMPT = """
You are a senior Horizon Europe evaluator.

Evaluate the proposal strictly according to Horizon Europe evaluation logic:
1. Excellence
2. Impact
3. Quality and Efficiency of Implementation

Use evaluator-style language similar to an Evaluation Summary Report (ESR).
Do not be overly positive. Identify weaknesses, shortcomings, risks, gaps, and missing evidence.

Return only valid JSON.
"""


def evaluate_proposal(proposal_text, call_info):
    prompt = f"""
Evaluate this Horizon Europe proposal.

CALL INFORMATION:
{call_info}

PROPOSAL TEXT:
{proposal_text[:45000]}

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
  "priority_actions": []
}}

Scores must be between 0 and 5.
Use half-points if appropriate.
The total score must be out of 15.
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    content = response.choices[0].message.content

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {
            "error": "Model response could not be parsed as JSON.",
            "raw_response": content,
        }
