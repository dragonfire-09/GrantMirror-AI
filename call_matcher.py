import json


def rank_calls_with_ai(proposal_text, calls, llm_call, top_k=20):
    compact_calls = []

    for i, call in enumerate(calls):
        compact_calls.append({
            "index": i,
            "call_id": call.get("call_id", ""),
            "title": call.get("title", ""),
            "deadline": call.get("deadline", ""),
            "action_types": call.get("action_types", []),
            "destination": call.get("destination", ""),
            "description": call.get("description", "")[:600],
            "scope": call.get("scope", "")[:600],
            "keywords": call.get("keywords", []),
            "source": call.get("source", ""),
        })

    prompt = f"""
You are a Horizon Europe call matching expert.

Rank the most suitable calls for this proposal.

PROPOSAL TEXT:
{proposal_text[:8000]}

CALLS:
{json.dumps(compact_calls[:200], ensure_ascii=False)}

Return only valid JSON:

{{
  "ranked_calls": [
    {{
      "index": 0,
      "match_score": 0,
      "fit_level": "High/Medium/Low",
      "reason": "",
      "risks": "",
      "recommended_action": ""
    }}
  ]
}}

Rules:
- match_score must be 0-100
- prioritize topic fit, expected outcomes, action type fit, TRL fit, impact fit
- do not over-score generic matches
- return top {top_k}
"""

    system_prompt = """
You are a strict Horizon Europe funding consultant.
You match proposals to calls based on topic fit, action type fit, expected outcomes, TRL, consortium and impact logic.
Return only JSON.
"""

    raw = llm_call(system_prompt, prompt)

    try:
        data = json.loads(raw)
        ranked = data.get("ranked_calls", [])
    except Exception:
        return []

    output = []

    for item in ranked[:top_k]:
        idx = item.get("index")

        if idx is None or idx >= len(calls):
            continue

        call = calls[idx].copy()
        call["ai_match_score"] = item.get("match_score", 0)
        call["ai_fit_level"] = item.get("fit_level", "")
        call["ai_match_reason"] = item.get("reason", "")
        call["ai_match_risks"] = item.get("risks", "")
        call["ai_recommended_action"] = item.get("recommended_action", "")

        output.append(call)

    return output
