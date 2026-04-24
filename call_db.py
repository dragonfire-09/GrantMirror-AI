"""
GrantMirror-AI: AI-powered call matching.
Uses LLM to semantically match proposals to calls.
Falls back to keyword matching if LLM unavailable.
"""
import json
import re
from typing import Dict, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════
# CALL DATABASE (expandable — add real calls here)
# ═══════════════════════════════════════════════════════════
HORIZON_CALLS_DB = [
    {
        "call_id": "HORIZON-CL4-2025-HUMAN-01",
        "cluster": "Cluster 4 - Digital, Industry, Space",
        "action_types": ["RIA", "IA"],
        "keywords": ["ai", "artificial intelligence", "digital", "industry", "human-centric", "robotics", "data", "cybersecurity", "manufacturing", "iot"],
        "expected_outcomes": "AI-driven digital transformation of European industry with human-centric approaches ensuring trustworthy AI, digital sovereignty, and competitive manufacturing",
        "scope": "Projects should address next-generation AI systems, human-robot interaction, digital twins for manufacturing, cybersecurity for industrial systems, or data spaces for industrial applications.",
        "destination": "A human-centred and ethical development of digital and industrial technologies",
        "trl_range": "TRL 2-6",
        "budget_per_project": "EUR 3-8M",
        "deadline": "2025-02-19",
    },
    {
        "call_id": "HORIZON-CL6-2025-BIODIV-01",
        "cluster": "Cluster 6 - Food, Bioeconomy, Natural Resources",
        "action_types": ["RIA", "IA", "CSA"],
        "keywords": ["biodiversity", "ecosystem", "nature", "soil", "agriculture", "food", "climate", "sustainability", "bioeconomy", "forestry", "water", "circular"],
        "expected_outcomes": "Halt and reverse biodiversity loss, sustainable food systems, climate-resilient agriculture, nature-based solutions for ecosystem restoration",
        "scope": "Projects addressing biodiversity monitoring, sustainable agriculture, soil health, carbon farming, nature-based solutions, ecosystem services valuation, or food system transformation.",
        "destination": "Biodiversity and ecosystem services",
        "trl_range": "TRL 2-5",
        "budget_per_project": "EUR 4-7M",
        "deadline": "2025-02-19",
    },
    {
        "call_id": "HORIZON-HLTH-2025-DISEASE-03",
        "cluster": "Cluster 1 - Health",
        "action_types": ["RIA"],
        "keywords": ["health", "disease", "therapeutics", "clinical", "cancer", "rare disease", "infectious", "genomics", "personalized medicine", "diagnostics", "pharmaceutical", "biomarker"],
        "expected_outcomes": "Novel therapeutic approaches, improved diagnostics, personalized medicine strategies, and better understanding of disease mechanisms",
        "scope": "Projects should address novel drug targets, advanced therapy development, diagnostic innovation, disease mechanism elucidation, or clinical trial methodologies.",
        "destination": "Tackling diseases and reducing disease burden",
        "trl_range": "TRL 2-5",
        "budget_per_project": "EUR 4-8M",
        "deadline": "2025-04-16",
    },
    {
        "call_id": "HORIZON-CL5-2025-D3-01",
        "cluster": "Cluster 5 - Climate, Energy, Mobility",
        "action_types": ["RIA", "IA"],
        "keywords": ["energy", "clean", "renewable", "hydrogen", "battery", "solar", "wind", "grid", "efficiency", "carbon capture", "transport", "mobility", "electric", "fuel cell"],
        "expected_outcomes": "Accelerated clean energy transition, sustainable transport solutions, improved energy efficiency, and climate-neutral technologies",
        "scope": "Projects addressing renewable energy technologies, energy storage, smart grids, hydrogen production, carbon capture, sustainable transport, or energy efficiency in buildings and industry.",
        "destination": "Sustainable, secure and competitive energy supply",
        "trl_range": "TRL 3-7",
        "budget_per_project": "EUR 3-10M",
        "deadline": "2025-03-05",
    },
    {
        "call_id": "HORIZON-CL3-2025-FCT-01",
        "cluster": "Cluster 3 - Civil Security for Society",
        "action_types": ["RIA", "IA"],
        "keywords": ["security", "cybersecurity", "border", "crime", "terrorism", "resilience", "disaster", "crisis", "critical infrastructure", "forensics"],
        "expected_outcomes": "Enhanced security capabilities, improved crisis management, better protection of critical infrastructure, and strengthened cybersecurity",
        "scope": "Projects should address cyber threat detection, critical infrastructure protection, disaster response, border security technologies, or counter-terrorism approaches.",
        "destination": "Fighting crime and terrorism",
        "trl_range": "TRL 3-7",
        "budget_per_project": "EUR 3-6M",
        "deadline": "2025-11-20",
    },
    {
        "call_id": "HORIZON-CL2-2025-HERITAGE-01",
        "cluster": "Cluster 2 - Culture, Creativity, Inclusive Society",
        "action_types": ["RIA", "CSA"],
        "keywords": ["culture", "heritage", "democracy", "social", "inclusion", "migration", "governance", "education", "creative", "arts", "media", "language"],
        "expected_outcomes": "Innovative approaches to cultural heritage preservation, enhanced democratic governance, social inclusion, and creative industries",
        "scope": "Projects addressing cultural heritage digitization, democratic innovation, social cohesion, migration research, creative industries, or media literacy.",
        "destination": "Innovative research on cultural heritage and cultural and creative industries",
        "trl_range": "TRL 2-5",
        "budget_per_project": "EUR 2-5M",
        "deadline": "2025-09-18",
    },
    {
        "call_id": "HORIZON-MSCA-2025-DN-01",
        "cluster": "MSCA",
        "action_types": ["MSCA-DN"],
        "keywords": ["doctoral", "training", "researcher", "mobility", "interdisciplinary", "skills", "career", "supervision", "network", "phd"],
        "expected_outcomes": "High-quality doctoral training through international, interdisciplinary and intersectoral research networks",
        "scope": "Doctoral Networks implementing joint research training programmes for doctoral candidates with mandatory mobility and secondments.",
        "destination": "MSCA Doctoral Networks",
        "trl_range": "N/A",
        "budget_per_project": "EUR 2-4M",
        "deadline": "2025-11-27",
    },
    {
        "call_id": "EIC-PATHFINDER-2025-OPEN",
        "cluster": "EIC",
        "action_types": ["EIC-Pathfinder"],
        "keywords": ["breakthrough", "deep-tech", "visionary", "high-risk", "frontier", "disruptive", "paradigm", "foundational", "quantum", "biotech", "nanotech"],
        "expected_outcomes": "Radically new future technologies based on breakthrough science-to-technology research",
        "scope": "Pathfinder Open supports visionary research to explore the feasibility of radically new technologies. High-risk/high-gain approach essential.",
        "destination": "EIC Pathfinder Open",
        "trl_range": "TRL 1-3",
        "budget_per_project": "EUR 3-4M",
        "deadline": "2025-04-16",
    },
    {
        "call_id": "EIC-ACCELERATOR-2025-01",
        "cluster": "EIC",
        "action_types": ["EIC-Accelerator"],
        "keywords": ["sme", "startup", "scale-up", "market", "commercialization", "innovation", "deep-tech", "investment", "growth", "product"],
        "expected_outcomes": "Support high-impact SMEs and startups to scale up deep-tech innovations with market-creating potential",
        "scope": "Single SMEs with breakthrough innovation close to market (TRL 5-8), seeking blended finance (grant + equity) to scale.",
        "destination": "EIC Accelerator",
        "trl_range": "TRL 5-8",
        "budget_per_project": "EUR 0.5-17.5M",
        "deadline": "2025-03-05",
    },
    {
        "call_id": "HORIZON-WIDERA-2025-ACCESS-01",
        "cluster": "Widening",
        "action_types": ["CSA"],
        "keywords": ["widening", "teaming", "twinning", "era", "research excellence", "capacity building", "networking", "collaboration"],
        "expected_outcomes": "Strengthen research and innovation capacity across Europe, reduce disparities between countries",
        "scope": "Teaming, twinning and ERA Chairs to boost R&I excellence in widening countries through partnerships with leading institutions.",
        "destination": "Widening participation and spreading excellence",
        "trl_range": "N/A",
        "budget_per_project": "EUR 1-15M",
        "deadline": "2025-09-25",
    },
]


# ═══════════════════════════════════════════════════════════
# KEYWORD-BASED MATCHING (fast, no LLM needed)
# ═══════════════════════════════════════════════════════════
def keyword_match_calls(
    proposal_text: str,
    top_k: int = 5,
) -> List[Tuple[Dict, float]]:
    """
    Match proposal text to calls using keyword overlap scoring.
    Returns list of (call_dict, score) tuples sorted by relevance.
    """
    text_lower = proposal_text.lower()
    words = set(re.findall(r'[a-z]{3,}', text_lower))

    scored = []
    for call in HORIZON_CALLS_DB:
        score = 0.0

        # Keyword matches (weighted)
        kw_matches = sum(1 for kw in call["keywords"] if kw in text_lower)
        score += kw_matches * 3.0

        # Scope word overlap
        scope_words = set(re.findall(r'[a-z]{4,}', call["scope"].lower()))
        scope_overlap = len(words & scope_words)
        score += scope_overlap * 1.0

        # Expected outcomes overlap
        outcome_words = set(re.findall(r'[a-z]{4,}', call["expected_outcomes"].lower()))
        outcome_overlap = len(words & outcome_words)
        score += outcome_overlap * 1.5

        # Cluster/destination keyword bonus
        dest_words = set(re.findall(r'[a-z]{4,}', call.get("destination", "").lower()))
        dest_overlap = len(words & dest_words)
        score += dest_overlap * 2.0

        # Action type hints in text
        for at in call["action_types"]:
            if at.lower() in text_lower:
                score += 5.0

        if score > 0:
            scored.append((call, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


# ═══════════════════════════════════════════════════════════
# AI-POWERED MATCHING (uses LLM for semantic understanding)
# ═══════════════════════════════════════════════════════════
def ai_match_calls(
    proposal_text: str,
    llm_call_fn,  # function(system_prompt, user_prompt) -> str
    top_k: int = 3,
) -> List[Dict]:
    """
    Use LLM to semantically match proposal to most relevant calls.
    llm_call_fn should be a function that takes (system_prompt, user_prompt) and returns JSON string.
    """
    # First do keyword pre-filter to get top candidates
    keyword_results = keyword_match_calls(proposal_text, top_k=6)

    if not keyword_results:
        return []

    # Build candidate descriptions for LLM
    candidates = []
    for call, kw_score in keyword_results:
        candidates.append({
            "call_id": call["call_id"],
            "cluster": call["cluster"],
            "destination": call.get("destination", ""),
            "scope_summary": call["scope"][:300],
            "expected_outcomes": call["expected_outcomes"][:200],
            "action_types": call["action_types"],
            "keyword_score": round(kw_score, 1),
        })

    # Extract proposal summary (first 2000 chars)
    proposal_summary = proposal_text[:2000]

    system_prompt = """You are a Horizon Europe call matching expert. 
Analyze the proposal text and rank the candidate calls by relevance.
Consider: thematic alignment, methodology fit, TRL match, action type appropriateness."""

    user_prompt = f"""## PROPOSAL EXCERPT:
\"\"\"{proposal_summary}\"\"\"

## CANDIDATE CALLS:
{json.dumps(candidates, indent=2)}

## TASK:
Rank these calls by relevance to the proposal. For each, provide:
- match_score (0-100)
- match_reason (1-2 sentences why it matches or doesn't)
- suggested_action_type (which action type best fits)

Respond JSON:
{{
  "rankings": [
    {{
      "call_id": "...",
      "match_score": <0-100>,
      "match_reason": "...",
      "suggested_action_type": "..."
    }}
  ],
  "best_match_explanation": "1-2 sentences on why the top match is best"
}}"""

    try:
        raw = llm_call_fn(system_prompt, user_prompt)
        result = json.loads(raw)
        rankings = result.get("rankings", [])

        # Enrich with full call data
        enriched = []
        for r in rankings[:top_k]:
            cid = r.get("call_id", "")
            full_call = next((c for c in HORIZON_CALLS_DB if c["call_id"] == cid), None)
            if full_call:
                enriched.append({
                    **full_call,
                    "ai_match_score": r.get("match_score", 0),
                    "ai_match_reason": r.get("match_reason", ""),
                    "suggested_action_type": r.get("suggested_action_type", ""),
                })

        result["enriched_matches"] = enriched
        return enriched

    except Exception:
        # Fallback to keyword results
        return [
            {**call, "ai_match_score": round(score * 5, 1), "ai_match_reason": "Keyword-based match", "suggested_action_type": call["action_types"][0]}
            for call, score in keyword_results[:top_k]
        ]


# ═══════════════════════════════════════════════════════════
# CALL CONTEXT BUILDER
# ═══════════════════════════════════════════════════════════
def build_call_eval_context(call: Dict) -> str:
    """Build evaluation context text from a matched call."""
    parts = [
        f"MATCHED CALL: {call['call_id']}",
        f"CLUSTER: {call.get('cluster', 'N/A')}",
        f"DESTINATION: {call.get('destination', 'N/A')}",
        f"ACTION TYPES: {', '.join(call.get('action_types', []))}",
        f"TRL RANGE: {call.get('trl_range', 'N/A')}",
        f"BUDGET/PROJECT: {call.get('budget_per_project', 'N/A')}",
        f"DEADLINE: {call.get('deadline', 'N/A')}",
        "",
        f"EXPECTED OUTCOMES:\n{call.get('expected_outcomes', 'N/A')}",
        "",
        f"SCOPE:\n{call.get('scope', 'N/A')}",
    ]

    if call.get("ai_match_reason"):
        parts.append(f"\nMATCH ANALYSIS: {call['ai_match_reason']}")

    return "\n".join(parts)
