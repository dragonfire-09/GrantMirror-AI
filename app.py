"""
GrantMirror-AI: Horizon Europe Proposal Pre-Screening & ESR Simulator
AI-powered call matching, RAG knowledge engine, section-aware scoring.
Modern dashboard UI with glassmorphism design.
"""
import streamlit as st
import json
import time
import os
from typing import Dict, List, Optional
from collections import Counter
from datetime import datetime
from openai import OpenAI

from config import (
    ActionType, ACTION_TYPE_CONFIGS, WEAKNESS_TAXONOMY,
    CriterionConfig, get_action_type_from_string,
)
from document_parser import parse_proposal, ParsedProposal, SectionType
from eligibility_checker import run_eligibility_checks, CheckStatus, EligibilityReport
from knowledge_base import HorizonKnowledgeBase
from deidentifier import scan_for_identity_signals, generate_deidentification_report
from report_generator import generate_esr_report, generate_coaching_report
from call_fetcher import (
    fetch_horizon_calls,
    fetch_topic_details,
    detect_action_type_from_call,
    build_call_specific_criteria,
    CallCache,
    calls_to_excel_bytes,
)
from call_db import (
    keyword_match_calls, ai_match_calls, build_call_eval_context,
    HORIZON_CALLS_DB, get_call_stats,
)
from rag_engine import get_criterion_context as rag_get_context, ai_enhanced_retrieval

# ═══════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════
st.set_page_config(
    page_title="GrantMirror-AI",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════
# MODERN CSS THEME
# ═══════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');

:root {
    --gm-primary: #6366f1;
    --gm-primary-light: #818cf8;
    --gm-primary-dark: #4f46e5;
    --gm-secondary: #06b6d4;
    --gm-success: #10b981;
    --gm-warning: #f59e0b;
    --gm-danger: #ef4444;
    --gm-bg: #f8fafc;
    --gm-surface: #ffffff;
    --gm-surface-hover: #f1f5f9;
    --gm-border: #e2e8f0;
    --gm-text: #1e293b;
    --gm-text-secondary: #64748b;
    --gm-text-muted: #94a3b8;
    --gm-radius: 16px;
    --gm-radius-sm: 10px;
    --gm-radius-xs: 6px;
    --gm-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
    --gm-shadow-lg: 0 4px 6px rgba(0,0,0,0.04), 0 10px 24px rgba(0,0,0,0.08);
    --gm-shadow-xl: 0 8px 30px rgba(0,0,0,0.12);
    --gm-transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    color: var(--gm-text);
}
.stApp { background: var(--gm-bg); }

section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1e1b4b 0%, #312e81 50%, #3730a3 100%) !important;
    border-right: none !important;
}
section[data-testid="stSidebar"] * { color: #e0e7ff !important; }
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] .stRadio label,
section[data-testid="stSidebar"] .stCheckbox label,
section[data-testid="stSidebar"] .stTextArea label {
    color: #c7d2fe !important; font-weight: 500 !important; font-size: 0.85rem !important;
}
section[data-testid="stSidebar"] .stMarkdown h2 {
    color: #ffffff !important; font-size: 1.1rem !important; font-weight: 700 !important;
}
section[data-testid="stSidebar"] .stMarkdown h3 {
    color: #a5b4fc !important; font-size: 0.95rem !important; font-weight: 600 !important;
}
section[data-testid="stSidebar"] hr { border-color: rgba(165,180,252,0.2) !important; }
section[data-testid="stSidebar"] .stExpander {
    background: rgba(255,255,255,0.06) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: var(--gm-radius-sm) !important;
}

.gm-card {
    background: var(--gm-surface); border: 1px solid var(--gm-border);
    border-radius: var(--gm-radius); padding: 1.5rem; margin-bottom: 1rem;
    box-shadow: var(--gm-shadow); transition: var(--gm-transition);
}
.gm-card:hover {
    box-shadow: var(--gm-shadow-lg); border-color: var(--gm-primary-light);
    transform: translateY(-1px);
}

.gm-call-card {
    background: var(--gm-surface); border: 1px solid var(--gm-border);
    border-radius: var(--gm-radius); padding: 1.25rem 1.5rem;
    margin-bottom: 0.75rem; box-shadow: var(--gm-shadow);
    transition: var(--gm-transition); position: relative; overflow: hidden;
}
.gm-call-card::before {
    content: ''; position: absolute; left: 0; top: 0; bottom: 0;
    width: 4px; background: var(--gm-primary); border-radius: 0 2px 2px 0;
}
.gm-call-card:hover {
    box-shadow: var(--gm-shadow-lg); border-color: var(--gm-primary-light);
    transform: translateY(-2px);
}
.gm-call-card h4 { color: var(--gm-text); font-weight: 600; font-size: 1rem; line-height: 1.4; margin: 0; }
.gm-call-card p { font-size: 0.85rem; }

.gm-badge-open {
    background: linear-gradient(135deg, #dcfce7, #bbf7d0); color: #166534;
    padding: 0.25rem 0.75rem; border-radius: 20px; font-size: 0.75rem;
    font-weight: 600; display: inline-block; border: 1px solid #86efac;
}
.gm-badge-forthcoming {
    background: linear-gradient(135deg, #fef9c3, #fde68a); color: #854d0e;
    padding: 0.25rem 0.75rem; border-radius: 20px; font-size: 0.75rem;
    font-weight: 600; display: inline-block; border: 1px solid #fcd34d;
}
.gm-badge-closed {
    background: linear-gradient(135deg, #fee2e2, #fecaca); color: #991b1b;
    padding: 0.25rem 0.75rem; border-radius: 20px; font-size: 0.75rem;
    font-weight: 600; display: inline-block; border: 1px solid #fca5a5;
}

.gm-match-high {
    background: linear-gradient(135deg, #10b981, #059669); color: white;
    padding: 0.3rem 0.9rem; border-radius: 20px; font-size: 0.8rem;
    font-weight: 700; display: inline-block;
}
.gm-match-medium {
    background: linear-gradient(135deg, #f59e0b, #d97706); color: white;
    padding: 0.3rem 0.9rem; border-radius: 20px; font-size: 0.8rem;
    font-weight: 700; display: inline-block;
}
.gm-match-low {
    background: linear-gradient(135deg, #ef4444, #dc2626); color: white;
    padding: 0.3rem 0.9rem; border-radius: 20px; font-size: 0.8rem;
    font-weight: 700; display: inline-block;
}

.gm-hero {
    background: linear-gradient(135deg, #1e1b4b 0%, #312e81 40%, #4f46e5 100%);
    border-radius: 20px; padding: 2.5rem 2rem; text-align: center;
    margin-bottom: 2rem; box-shadow: var(--gm-shadow-xl);
    position: relative; overflow: hidden;
}
.gm-hero::before {
    content: ''; position: absolute; top: -50%; left: -50%; width: 200%; height: 200%;
    background: radial-gradient(circle, rgba(99,102,241,0.15) 0%, transparent 60%);
    animation: gm-pulse 8s ease-in-out infinite;
}
@keyframes gm-pulse {
    0%, 100% { transform: scale(1); opacity: 0.5; }
    50% { transform: scale(1.1); opacity: 0.8; }
}
.gm-hero h1 { color: #ffffff !important; font-size: 2.2rem !important; font-weight: 800 !important; margin: 0 0 0.3rem 0 !important; position: relative; }
.gm-hero .gm-subtitle { color: #c7d2fe; font-size: 1rem; font-weight: 400; margin: 0; position: relative; }
.gm-hero .gm-tags { color: #a5b4fc; font-size: 0.8rem; margin-top: 0.8rem; position: relative; }
.gm-hero .gm-tags span {
    background: rgba(255,255,255,0.1); padding: 0.2rem 0.6rem; border-radius: 12px;
    margin: 0 0.15rem; display: inline-block; margin-bottom: 0.3rem;
    border: 1px solid rgba(255,255,255,0.1);
}

.gm-metric {
    background: var(--gm-surface); border: 1px solid var(--gm-border);
    border-radius: var(--gm-radius); padding: 1.2rem 1.5rem; text-align: center;
    box-shadow: var(--gm-shadow); transition: var(--gm-transition);
}
.gm-metric:hover { transform: translateY(-2px); box-shadow: var(--gm-shadow-lg); }
.gm-metric .gm-metric-value { font-size: 1.8rem; font-weight: 800; color: var(--gm-primary); line-height: 1; margin-bottom: 0.3rem; }
.gm-metric .gm-metric-label { font-size: 0.8rem; font-weight: 500; color: var(--gm-text-secondary); text-transform: uppercase; letter-spacing: 0.05em; }
.gm-metric .gm-metric-delta { font-size: 0.75rem; margin-top: 0.2rem; }

.gm-score-container { margin-bottom: 1.2rem; }
.gm-score-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.4rem; }
.gm-score-label { font-weight: 600; font-size: 0.95rem; color: var(--gm-text); }
.gm-score-value { font-weight: 800; font-size: 1.1rem; }
.gm-score-track { background: #e2e8f0; border-radius: 12px; height: 14px; position: relative; overflow: hidden; }
.gm-score-fill { height: 100%; border-radius: 12px; transition: width 1s cubic-bezier(0.4, 0, 0.2, 1); }
.gm-score-fill-green { background: linear-gradient(90deg, #10b981, #34d399); }
.gm-score-fill-yellow { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
.gm-score-fill-red { background: linear-gradient(90deg, #ef4444, #f87171); }
.gm-score-threshold { position: absolute; top: -2px; height: calc(100% + 4px); width: 3px; background: #1e293b; border-radius: 2px; z-index: 2; }
.gm-score-meta { display: flex; justify-content: space-between; margin-top: 0.3rem; font-size: 0.75rem; color: var(--gm-text-muted); }

.gm-section-header { display: flex; align-items: center; gap: 0.6rem; margin: 2rem 0 1rem 0; padding-bottom: 0.5rem; border-bottom: 2px solid var(--gm-border); }
.gm-section-header .gm-section-icon { font-size: 1.4rem; }
.gm-section-header h2 { font-size: 1.3rem !important; font-weight: 700 !important; color: var(--gm-text) !important; margin: 0 !important; }

.gm-feature-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1rem; margin: 1.5rem 0; }
.gm-feature-item { background: var(--gm-surface); border: 1px solid var(--gm-border); border-radius: var(--gm-radius-sm); padding: 1.2rem; transition: var(--gm-transition); }
.gm-feature-item:hover { border-color: var(--gm-primary-light); box-shadow: var(--gm-shadow); transform: translateY(-1px); }
.gm-feature-item .gm-feature-icon { font-size: 1.6rem; margin-bottom: 0.5rem; }
.gm-feature-item h4 { font-size: 0.9rem; font-weight: 600; color: var(--gm-text); margin: 0 0 0.3rem 0; }
.gm-feature-item p { font-size: 0.8rem; color: var(--gm-text-secondary); margin: 0; line-height: 1.5; }

.stButton > button { border-radius: var(--gm-radius-sm) !important; font-weight: 600 !important; font-size: 0.85rem !important; transition: var(--gm-transition) !important; border: 1px solid var(--gm-border) !important; }
.stButton > button[kind="primary"] { background: linear-gradient(135deg, var(--gm-primary), var(--gm-primary-dark)) !important; border: none !important; color: white !important; box-shadow: 0 2px 8px rgba(99,102,241,0.3) !important; }
.stButton > button[kind="primary"]:hover { box-shadow: 0 4px 16px rgba(99,102,241,0.4) !important; transform: translateY(-1px) !important; }

.stExpander { background: var(--gm-surface) !important; border: 1px solid var(--gm-border) !important; border-radius: var(--gm-radius-sm) !important; box-shadow: var(--gm-shadow) !important; margin-bottom: 0.75rem !important; }
div[data-testid="stMetricValue"] { font-weight: 700 !important; }

.stTabs [data-baseweb="tab-list"] { gap: 0.5rem; background: var(--gm-surface); padding: 0.3rem; border-radius: var(--gm-radius-sm); border: 1px solid var(--gm-border); }
.stTabs [data-baseweb="tab"] { border-radius: var(--gm-radius-xs) !important; font-weight: 600 !important; font-size: 0.85rem !important; }
.stTabs [aria-selected="true"] { background: var(--gm-primary) !important; color: white !important; }

[data-testid="stFileUploader"] { border: 2px dashed var(--gm-border) !important; border-radius: var(--gm-radius) !important; padding: 2rem !important; background: var(--gm-surface) !important; transition: var(--gm-transition); }
[data-testid="stFileUploader"]:hover { border-color: var(--gm-primary-light) !important; background: #f5f3ff !important; }

.stDownloadButton > button { background: var(--gm-surface) !important; border: 1px solid var(--gm-border) !important; border-radius: var(--gm-radius-sm) !important; font-weight: 600 !important; transition: var(--gm-transition) !important; }
.stDownloadButton > button:hover { border-color: var(--gm-primary) !important; background: #f5f3ff !important; box-shadow: var(--gm-shadow) !important; }

.stProgress > div > div { background: linear-gradient(90deg, var(--gm-primary), var(--gm-secondary)) !important; border-radius: 10px !important; }
.stAlert { border-radius: var(--gm-radius-sm) !important; }

@media (max-width: 768px) {
    .gm-hero { padding: 1.5rem 1rem; }
    .gm-hero h1 { font-size: 1.6rem !important; }
    .gm-feature-grid { grid-template-columns: 1fr; }
}
</style>
""", unsafe_allow_html=True)

# Initialize cache
if "call_cache" not in st.session_state:
    st.session_state.call_cache = CallCache(ttl_minutes=30)

MODEL_NAME = "openai/gpt-4o-mini"


# ═══════════════════════════════════════════════════════════
# LLM CLIENT & HELPERS
# ═══════════════════════════════════════════════════════════
def get_llm_client() -> OpenAI:
    api_key = st.secrets.get("OPENROUTER_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))
    if not api_key:
        st.error("🔑 OPENROUTER_API_KEY bulunamadı.")
        st.stop()
    return OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")


def call_llm(client, sys_p, usr_p, temp=0.3, max_tok=4000, js=True):
    kw = dict(
        model=MODEL_NAME,
        messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
        temperature=temp, max_tokens=max_tok,
    )
    if js:
        kw["response_format"] = {"type": "json_object"}
    for attempt in range(3):
        try:
            return client.chat.completions.create(**kw).choices[0].message.content
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                return json.dumps({
                    "error": str(e), "score": 0, "strengths": [],
                    "weaknesses": [f"LLM hatası: {e}"],
                    "esr_comment": "Teknik hata.", "confidence_low": 0,
                    "confidence_high": 0, "consensus_risk": "high",
                    "weakness_categories": [], "sub_signal_assessments": [],
                    "alternative_reading": "",
                })


def llm_call_wrapper(client):
    def _call(sys_prompt, usr_prompt):
        return call_llm(client, sys_prompt, usr_prompt, temp=0.3, max_tok=3000, js=True)
    return _call


# ═══════════════════════════════════════════════════════════
# PROMPTS
# ═══════════════════════════════════════════════════════════
SYS_ESR = """You are an experienced Horizon Europe evaluator (10+ years, multiple Framework Programmes).

ABSOLUTE RULES (from EC evaluation form and expert briefing):
1. Evaluate 'as is' — NEVER suggest improvements
2. Every criticism MUST point to specific proposal content or MISSING content
3. Score MUST be CONSISTENT with comment balance
4. Do NOT penalize same weakness under multiple criteria
5. Scale 0-5 half-points: 0=fails, 1=poor, 2=fair, 3=good(threshold), 4=very good, 5=excellent
6. Third person: "The proposal..."
7. Missing information = explicit weakness
8. Concise but substantive like a real ESR

EVALUATION KNOWLEDGE (from LERU 129 ESR analysis + Danish UFDS 1745 comments + NCP analysis):
- Check OBJECTIVES→KPIs→METHODOLOGY→OUTCOMES chain coherence
- Six core weakness families: LACK_OF_DETAIL, LACK_OF_QUANTIFICATION, UNCLEAR_TARGET_GROUPS,
  RESOURCE_IMBALANCE, INTERNAL_INCOHERENCE, WEAK_RISK_MITIGATION
- Open science: reject boilerplate; check specific mandatory/recommended practices
- Gender dimension: must integrate into research content, not just team balance
- Risk mitigation: >50% of negative comments target mitigation quality, not risk identification
- Impact pathway: only ~30% of evaluators use exact 'pathway to impact' terminology —
  normalize: outputs→outcomes→impacts chain
- Dissemination: must justify channels for specific target groups, not just list them

PROCESS AWARENESS:
- Real evaluation: ≥3 independent experts → consensus → panel review
- Your score represents one evaluator; indicate consensus risk
- Gray zone around thresholds (3.0±0.5) requires alternative_reading"""

SYS_COACH = """Expert Horizon Europe proposal consultant with deep knowledge of ESR patterns.
You identify weaknesses, explain WHY they reduce score using evaluation evidence, and give
CONCRETE ACTIONABLE fixes ranked by expected score impact.
Reference the six core weakness families when relevant.
Give example replacement text where possible."""


def build_eval_prompt(crit, sec_text, cross_ctx, kb_ctx, action_type, call_ctx=""):
    qs = "\n".join(f"  • {q}" for q in crit.official_questions)
    checks = "\n".join(f"  • {c}" for c in crit.practical_checklist)
    sigs = ", ".join(crit.sub_signals)
    p = f"""## EVALUATE: {crit.name} ({action_type})

### OFFICIAL EC EVALUATION QUESTIONS:
{qs}

### QUALITY SIGNALS (from real ESR analysis):
{checks}

### SUB-SIGNALS TO ASSESS: {sigs}

### SCORING: 0-5 half-points. Threshold: {crit.threshold}/{crit.max_score}
"""
    if call_ctx:
        p += f"""
### CALL/TOPIC SPECIFIC CONTEXT:
{call_ctx}

IMPORTANT: Check alignment between proposal and topic-level expected outcomes.
"""
    p += f"""
### KNOWLEDGE BASE:
{kb_ctx}

### PROPOSAL — {crit.name} SECTION:
\"\"\"
{sec_text[:15000]}
\"\"\"

### CROSS-REFERENCE (other sections):
\"\"\"
{cross_ctx[:5000]}
\"\"\"

### RESPOND IN THIS EXACT JSON:
{{
  "criterion": "{crit.name}",
  "score": <0.0-5.0 half-point>,
  "confidence_low": <float>,
  "confidence_high": <float>,
  "consensus_risk": "<low|medium|high>",
  "strengths": ["<specific strength WITH evidence from proposal>"],
  "weaknesses": ["<specific weakness WITH evidence or noting MISSING content>"],
  "weakness_categories": ["<from: LACK_OF_DETAIL|LACK_OF_QUANTIFICATION|UNCLEAR_TARGET_GROUPS|RESOURCE_IMBALANCE|INTERNAL_INCOHERENCE|WEAK_RISK_MITIGATION|GENERIC_OPEN_SCIENCE|SOTA_GAP|GENERIC_DISSEMINATION|PATHWAY_VAGUE|TRL_INCONSISTENCY|PARTNER_ROLE_UNCLEAR>"],
  "sub_signal_assessments": [{{"signal":"...","rating":"<strong|adequate|weak|missing>","evidence":"<quote/ref from proposal>","comment":"..."}}],
  "esr_comment": "<2-3 paragraph ESR: P1=strengths, P2=weaknesses, evidence-based, NO suggestions, consistent with score>",
  "topic_alignment": "<How well does the proposal align with the specific call/topic requirements? Only if call context provided>",
  "alternative_reading": "<If score 2.5-3.5: how a stricter/more generous evaluator might differ. Otherwise empty string>"
}}

CRITICAL REMINDERS:
- Every strength/weakness MUST reference specific proposal content
- If required element MISSING, state it as weakness with what is missing
- Score MUST match strength/weakness balance
- Do NOT suggest improvements — only describe what IS and IS NOT present"""
    return p


def build_coach_prompt(name, score, weaknesses, cats, sec_text, checklist):
    return f"""## COACH: {name} (current score: {score}/5.0)

### IDENTIFIED WEAKNESSES:
{json.dumps(weaknesses, indent=2)}

### WEAKNESS CATEGORIES:
{json.dumps(cats)}

### PROPOSAL SECTION TEXT:
\"\"\"
{sec_text[:8000]}
\"\"\"

### QUALITY CHECKLIST:
{json.dumps(checklist[:8])}

### INSTRUCTIONS:
Provide 3-7 SPECIFIC improvements ranked by expected score impact.
For each: explain problem, why it hurts score, and EXACTLY how to fix it.
Give example text/structure where possible.

Respond JSON:
{{
  "improvements": [
    {{
      "priority": 1,
      "title": "<short title>",
      "problem": "<what is wrong>",
      "impact": "<why this hurts the score>",
      "solution": "<exactly how to fix, with example text if possible>",
      "expected_score_gain": "<e.g., +0.5>"
    }}
  ],
  "summary": "<1-2 paragraph overall coaching advice>"
}}"""


# ═══════════════════════════════════════════════════════════
# FUNDING PROBABILITY HELPERS
# ═══════════════════════════════════════════════════════════
def _calc_funding_probability(total, max_score, threshold, all_met):
    if not all_met or total < threshold:
        return "very_low"
    ratio = total / max_score if max_score > 0 else 0
    if ratio >= 0.90:
        return "high"
    elif ratio >= 0.80:
        return "medium"
    elif ratio >= 0.70:
        return "low"
    return "very_low"


def _calc_funding_pct(total, max_score, threshold, all_met):
    if not all_met or total < threshold:
        return 5
    if max_score <= 0:
        return 5
    ratio = total / max_score
    if ratio >= 0.95:
        base = 85
    elif ratio >= 0.90:
        base = 70
    elif ratio >= 0.85:
        base = 50
    elif ratio >= 0.80:
        base = 30
    elif ratio >= 0.75:
        base = 15
    elif ratio >= 0.67:
        base = 10
    else:
        base = 5
    margin = total - threshold
    if margin < 1.0:
        base = int(base * 0.7)
    return min(base, 95)


def _check_double_penalization(criteria: List[Dict]) -> List[str]:
    warnings = []
    all_weaknesses = []
    for c in criteria:
        for w in c.get("weaknesses", []):
            all_weaknesses.append((c.get("criterion", "?"), set(w.lower().split())))
    for i, (c1, w1) in enumerate(all_weaknesses):
        for j, (c2, w2) in enumerate(all_weaknesses):
            if i >= j or c1 == c2:
                continue
            overlap = len(w1 & w2) / max(len(w1 | w2), 1)
            if overlap > 0.5:
                warnings.append(f"⚠️ Benzer zayıflık {c1} ve {c2}'de tespit edildi — çift cezalandırma riski")
                break
    return warnings


# ═══════════════════════════════════════════════════════════
# EVALUATOR ENGINE
# ═══════════════════════════════════════════════════════════
class Evaluator:
    def __init__(self, client, kb):
        self.client = client
        self.kb = kb
        self.llm_fn = llm_call_wrapper(client)

    def _section_text(self, proposal, criterion):
        mapping = {
            "Excellence": [SectionType.EXCELLENCE, SectionType.OPEN_SCIENCE, SectionType.GENDER_DIMENSION],
            "Impact": [SectionType.IMPACT, SectionType.DISSEMINATION, SectionType.EXPLOITATION],
            "Implementation": [SectionType.IMPLEMENTATION, SectionType.WORK_PACKAGES, SectionType.RISK_TABLE],
        }
        texts = [proposal.sections[s].content for s in mapping.get(criterion, []) if s in proposal.sections]
        if texts:
            return "\n\n".join(texts)
        t = proposal.full_text
        n = len(t)
        if criterion == "Excellence":
            return t[: n // 3]
        elif criterion == "Impact":
            return t[n // 3: 2 * n // 3]
        return t[2 * n // 3:]

    def _cross_ctx(self, proposal):
        return "\n".join(
            f"[{s.value}]: {d.content[:400]}" for s, d in proposal.sections.items() if d.word_count > 50
        )

    def _get_rag_context(self, criterion, action_type, section_text, use_ai_rag=True):
        if use_ai_rag:
            try:
                return ai_enhanced_retrieval(criterion, action_type, section_text, self.llm_fn)
            except Exception:
                pass
        return rag_get_context(criterion, action_type, section_text[:500])

    def run(self, proposal, action_type, call_ctx="", on_progress=None, use_ai_rag=True):
        cfg = ACTION_TYPE_CONFIGS[action_type]
        results = {"action_type": action_type.value, "criteria": [], "coaching": []}
        total_w = 0.0
        all_met = True

        for i, cc in enumerate(cfg.criteria):
            if on_progress:
                on_progress(f"📝 {i + 1}/{len(cfg.criteria)}: {cc.name}...")
            sec = self._section_text(proposal, cc.name)
            cross = self._cross_ctx(proposal)
            if on_progress:
                on_progress(f"🧠 {cc.name} bilgi tabanı hazırlanıyor...")
            kb_ctx = self._get_rag_context(cc.name, action_type.value, sec, use_ai_rag)
            prompt = build_eval_prompt(cc, sec, cross, kb_ctx, action_type.value, call_ctx)
            raw = call_llm(self.client, SYS_ESR, prompt)
            try:
                r = json.loads(raw)
            except json.JSONDecodeError:
                r = {
                    "criterion": cc.name, "score": 0, "confidence_low": 0,
                    "confidence_high": 0, "consensus_risk": "high",
                    "strengths": [], "weaknesses": ["JSON parse hatası"],
                    "weakness_categories": [], "sub_signal_assessments": [],
                    "esr_comment": "Parse hatası.", "alternative_reading": "",
                    "topic_alignment": "",
                }
            s = max(0.0, min(5.0, round(float(r.get("score", 0)) * 2) / 2))
            r["score"] = s
            r["confidence_low"] = max(0.0, float(r.get("confidence_low", s - 0.5)))
            r["confidence_high"] = min(5.0, float(r.get("confidence_high", s + 0.5)))
            r["weight"] = cc.weight
            r["threshold"] = cc.threshold
            r["max_score"] = cc.max_score
            r["threshold_met"] = s >= cc.threshold
            r["weighted_score"] = s * cc.weight
            total_w += r["weighted_score"]
            if not r["threshold_met"]:
                all_met = False
            results["criteria"].append(r)

            if on_progress:
                on_progress(f"💡 {cc.name} koçluk...")
            raw2 = call_llm(
                self.client, SYS_COACH,
                build_coach_prompt(cc.name, s, r.get("weaknesses", []),
                                   r.get("weakness_categories", []), sec, cc.practical_checklist),
                temp=0.4,
            )
            try:
                co = json.loads(raw2)
            except json.JSONDecodeError:
                co = {"improvements": [], "summary": "Koçluk üretilemedi."}
            co["criterion"] = cc.name
            results["coaching"].append(co)

        results["total_weighted"] = round(total_w, 1)
        results["total_max"] = cfg.total_max
        results["total_threshold"] = cfg.total_threshold
        results["total_threshold_met"] = all_met and total_w >= cfg.total_threshold
        results["all_criteria_met"] = all_met
        results["funding_probability"] = _calc_funding_probability(total_w, cfg.total_max, cfg.total_threshold, all_met)
        results["funding_probability_pct"] = _calc_funding_pct(total_w, cfg.total_max, cfg.total_threshold, all_met)

        cats = []
        for c in results["criteria"]:
            cats.extend(c.get("weakness_categories", []))
        cc2 = Counter(cats)
        results["cross_cutting_issues"] = [
            f"'{WEAKNESS_TAXONOMY[k]['label']}' — {v} kriterde: {WEAKNESS_TAXONOMY[k]['description']}"
            for k, v in cc2.items() if v > 1 and k in WEAKNESS_TAXONOMY
        ]
        results["double_penalization_warnings"] = _check_double_penalization(results["criteria"])
        return results


# ═══════════════════════════════════════════════════════════
# UI COMPONENTS
# ═══════════════════════════════════════════════════════════
def render_header():
    st.markdown("""
    <div class="gm-hero">
        <h1>🔬 GrantMirror-AI</h1>
        <p class="gm-subtitle">Horizon Europe Proposal Pre-Screening & ESR Simulator</p>
        <div class="gm-tags">
            <span>📡 Canlı Çağrı</span>
            <span>🎯 AI Eşleştirme</span>
            <span>🧠 RAG Motor</span>
            <span>📋 ESR Simülasyon</span>
            <span>🎯 Koçluk</span>
            <span>📊 Güven Aralığı</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_call_dashboard():
    """Render live call data dashboard — ALL calls + auto-refresh."""
    st.markdown("""
    <div class="gm-section-header">
        <span class="gm-section-icon">📡</span>
        <h2>Canlı Çağrı Paneli</h2>
    </div>
    """, unsafe_allow_html=True)

    # Filters
    col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
    with col1:
        search = st.text_input("🔍 Arama", placeholder="Anahtar kelime...")
    with col2:
        status_filter = st.selectbox(
            "📋 Durum", ["", "Open", "Forthcoming", "Closed"],
            format_func=lambda x: x if x else "Tümü",
        )
    with col3:
        dest_options = [""] + sorted(set(
            c.get("destination", "") for c in HORIZON_CALLS_DB if c.get("destination")
        ))
        dest_filter = st.selectbox(
            "🏛️ Küme/Program", dest_options,
            format_func=lambda x: x.split("–")[-1].strip() if "–" in x else (x if x else "Tümü"),
        )
    with col4:
        st.markdown("<div style='height:1.6rem'></div>", unsafe_allow_html=True)
        refresh_btn = st.button("🔄", help="Yenile", use_container_width=True)

    # Auto-refresh
    auto_col1, auto_col2 = st.columns([1, 3])
    with auto_col1:
        auto_refresh = st.checkbox("⏰ Otomatik güncelle", value=False)
    with auto_col2:
        if auto_refresh:
            refresh_interval = st.select_slider(
                "Aralık", options=[30, 60, 120, 300], value=60,
                format_func=lambda x: f"{x}s" if x < 60 else f"{x // 60}dk",
            )
            st.caption(f"Her {refresh_interval}s'de bir yenilenir")
        else:
            refresh_interval = 300

    # Source
    source_col1, source_col2 = st.columns(2)
    with source_col1:
        use_live_api = st.checkbox("🌐 EC API'den canlı çek", value=True,
                                    help="Açıksa EC API'den güncel veri çeker, kapalıysa yerel veritabanı")
    with source_col2:
        if use_live_api:
            max_results = st.number_input("Maks sonuç", min_value=10, max_value=500, value=100, step=50)
        else:
            max_results = len(HORIZON_CALLS_DB)

    # Auto-refresh logic
    if auto_refresh:
        last_refresh = st.session_state.get("last_refresh_time", 0)
        if time.time() - last_refresh > refresh_interval:
            st.session_state["last_refresh_time"] = time.time()
            st.session_state.call_cache.clear()
            st.rerun()

    if refresh_btn:
        st.session_state.call_cache.clear()
        if "dashboard_calls" in st.session_state:
            del st.session_state["dashboard_calls"]
        st.rerun()

    # Fetch
    cache_key = f"dash_{search}_{status_filter}_{dest_filter}_{use_live_api}_{max_results}"
    cached = st.session_state.call_cache.get(cache_key)

    if cached:
        calls, total = cached
    else:
        if use_live_api:
            with st.spinner("📡 EC API'den çağrılar çekiliyor (tüm sayfalar)..."):
                api_calls, api_total = fetch_horizon_calls(
                    programme="HORIZON", status=status_filter, search_text=search,
                    page_size=100, max_pages=max(1, max_results // 100), fetch_all=True,
                )
            api_ids = set(c.get("call_id", "") for c in api_calls)
            local_calls = [lc for lc in HORIZON_CALLS_DB if lc["call_id"] not in api_ids]
            all_calls = api_calls + local_calls
        else:
            all_calls = list(HORIZON_CALLS_DB)

        # Apply filters
        filtered = all_calls
        if status_filter:
            filtered = [c for c in filtered if c.get("status", "").lower() == status_filter.lower()]
        if dest_filter:
            filtered = [c for c in filtered if dest_filter.lower() in c.get("destination", "").lower()]
        if search:
            kw = search.lower()
            filtered = [
                c for c in filtered
                if kw in c.get("title", "").lower()
                or kw in c.get("call_id", "").lower()
                or kw in " ".join(c.get("keywords", [])).lower()
                or kw in c.get("scope", "").lower()
                or kw in c.get("destination", "").lower()
            ]
        calls = filtered
        total = len(calls)
        st.session_state.call_cache.set(cache_key, (calls, total))

    if not calls:
        st.info("Çağrı bulunamadı. Filtreleri değiştirin veya yenileyin.")
        return None

    # Stats bar
    open_count = sum(1 for c in calls if c.get("status") == "Open")
    forth_count = sum(1 for c in calls if c.get("status") == "Forthcoming")
    closed_count = sum(1 for c in calls if c.get("status") == "Closed")

    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.markdown(f'<div class="gm-metric"><div class="gm-metric-value">{total}</div><div class="gm-metric-label">Toplam</div></div>', unsafe_allow_html=True)
    with s2:
        st.markdown(f'<div class="gm-metric"><div class="gm-metric-value" style="color:#10b981;">{open_count}</div><div class="gm-metric-label">Açık</div></div>', unsafe_allow_html=True)
    with s3:
        st.markdown(f'<div class="gm-metric"><div class="gm-metric-value" style="color:#f59e0b;">{forth_count}</div><div class="gm-metric-label">Yaklaşan</div></div>', unsafe_allow_html=True)
    with s4:
        st.markdown(f'<div class="gm-metric"><div class="gm-metric-value" style="color:#ef4444;">{closed_count}</div><div class="gm-metric-label">Kapanmış</div></div>', unsafe_allow_html=True)

    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    # Excel export
    excel_bytes = calls_to_excel_bytes(calls)
    st.download_button(
        label=f"📥 Tüm Çağrıları Excel Olarak İndir ({total} çağrı)",
        data=excel_bytes, file_name="horizon_calls.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    # Sort
    sort_col1, _ = st.columns([1, 3])
    with sort_col1:
        sort_by = st.selectbox(
            "Sırala", ["deadline", "title", "status"],
            format_func=lambda x: {"deadline": "📅 Son Tarih", "title": "🔤 Başlık", "status": "📋 Durum"}[x],
            label_visibility="collapsed",
        )
    if sort_by == "deadline":
        calls = sorted(calls, key=lambda c: c.get("deadline", "9999"))
    elif sort_by == "title":
        calls = sorted(calls, key=lambda c: c.get("title", "").lower())
    elif sort_by == "status":
        order = {"Open": 0, "Forthcoming": 1, "Closed": 2}
        calls = sorted(calls, key=lambda c: order.get(c.get("status", ""), 9))

    # Pagination
    items_per_page = 20
    total_pages = max(1, (total + items_per_page - 1) // items_per_page)
    if total > items_per_page:
        _, pc, _ = st.columns([1, 2, 1])
        with pc:
            current_page = st.number_input(f"Sayfa (1-{total_pages})", min_value=1, max_value=total_pages, value=1, step=1)
        start_idx = (current_page - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, total)
        page_calls = calls[start_idx:end_idx]
        st.caption(f"Gösterilen: {start_idx + 1}-{end_idx} / {total}")
    else:
        page_calls = calls
        current_page = 1

    # Call cards
    selected_call = None
    for i, call in enumerate(page_calls):
        status = call.get("status", "?")
        badge_class = {"Open": "gm-badge-open", "Forthcoming": "gm-badge-forthcoming", "Closed": "gm-badge-closed"}.get(status, "gm-badge-closed")
        action_types = ", ".join(call.get("action_types", ["?"]))
        deadline = call.get("deadline", "N/A")
        if deadline and len(deadline) > 10:
            deadline = deadline[:10]
        destination = call.get("destination", "")
        dest_short = destination.split("–")[-1].strip() if "–" in destination else destination
        budget = call.get("budget_per_project", call.get("budget_total", ""))

        days_label = ""
        if deadline and deadline != "N/A":
            try:
                dl = datetime.strptime(deadline[:10], "%Y-%m-%d")
                days_left = (dl - datetime.now()).days
                if days_left > 0:
                    if days_left <= 7:
                        days_label = f'<span style="color:#ef4444;font-weight:700;font-size:0.75rem;">⏰ {days_left} gün kaldı!</span>'
                    elif days_left <= 30:
                        days_label = f'<span style="color:#f59e0b;font-weight:600;font-size:0.75rem;">📅 {days_left} gün kaldı</span>'
                    else:
                        days_label = f'<span style="color:#64748b;font-size:0.75rem;">📅 {days_left} gün</span>'
                elif days_left == 0:
                    days_label = '<span style="color:#ef4444;font-weight:700;font-size:0.75rem;">🔥 Bugün son gün!</span>'
            except Exception:
                pass

        global_idx = (current_page - 1) * items_per_page + i

        st.markdown(f"""
        <div class="gm-call-card">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div style="flex:1;">
                    <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">
                        <span class="{badge_class}">{status}</span>
                        {f'<span style="background:#f1f5f9;padding:0.15rem 0.5rem;border-radius:12px;font-size:0.7rem;color:#475569;border:1px solid #e2e8f0;">{dest_short}</span>' if dest_short else ''}
                        {days_label}
                    </div>
                    <h4 style="margin:0.6rem 0 0.2rem 0;font-size:0.95rem;line-height:1.4;">{call.get('title', 'N/A')[:150]}</h4>
                    <p style="color:#667085;margin:0;font-size:0.82rem;">{call.get('call_id', 'N/A')}</p>
                    <div style="display:flex;gap:1rem;margin-top:0.4rem;flex-wrap:wrap;">
                        <span style="color:#667085;font-size:0.8rem;">🏷️ {action_types}</span>
                        <span style="color:#667085;font-size:0.8rem;">📅 {deadline}</span>
                        {f'<span style="color:#667085;font-size:0.8rem;">💰 {budget}</span>' if budget else ''}
                    </div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("Bu çağrıyı seç →", key=f"call_{global_idx}", use_container_width=True):
            selected_call = call

    if total > items_per_page:
        st.caption(f"Sayfa {current_page}/{total_pages} · Toplam {total} çağrı")

    last_t = st.session_state.get("last_refresh_time", 0)
    if last_t:
        ago = int(time.time() - last_t)
        st.caption(f"🕐 Son güncelleme: {ago}s önce" if ago < 60 else f"🕐 Son güncelleme: {ago // 60}dk önce")
    if auto_refresh:
        st.caption(f"⏰ Otomatik güncelleme aktif ({refresh_interval}s)")

    return selected_call


def render_call_detail(call_data: Dict) -> Dict:
    st.markdown("""
    <div class="gm-section-header">
        <span class="gm-section-icon">📋</span>
        <h2>Seçilen Çağrı Detayı</h2>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Çağrı", call_data.get("call_id", "N/A"))
    with col2:
        st.metric("Son Tarih", call_data.get("deadline", "N/A")[:10] if call_data.get("deadline") else "N/A")
    with col3:
        action_type = detect_action_type_from_call(call_data)
        st.metric("Aksiyon Türü", action_type)

    st.markdown(f"**Başlık**: {call_data.get('title', 'N/A')}")

    topics = call_data.get("topics", [])
    topic_details = None
    if topics:
        tid = topics[0].get("topic_id", "")
        if tid:
            cached_topic = st.session_state.call_cache.get(f"topic_{tid}")
            if cached_topic:
                topic_details = cached_topic
            else:
                with st.spinner(f"📡 Topic detayları çekiliyor: {tid}..."):
                    topic_details = fetch_topic_details(tid)
                    if topic_details:
                        st.session_state.call_cache.set(f"topic_{tid}", topic_details)

    if topic_details and topic_details.get("description"):
        with st.expander("📝 Topic Açıklaması", expanded=False):
            st.markdown(topic_details["description"][:3000])

    call_context = build_call_specific_criteria(call_data, topic_details)
    st.success(f"✅ Aksiyon türü: **{action_type}** | Çağrı-spesifik değerlendirme bağlamı hazır")
    return call_context


def render_score_bar(score, mx, thr, label):
    pct = score / mx * 100 if mx > 0 else 0
    tp = thr / mx * 100 if mx > 0 else 0
    if score >= thr + 1:
        fill_class, color = "gm-score-fill-green", "#10b981"
    elif score >= thr:
        fill_class, color = "gm-score-fill-yellow", "#f59e0b"
    else:
        fill_class, color = "gm-score-fill-red", "#ef4444"
    st.markdown(f"""
    <div class="gm-score-container">
        <div class="gm-score-header">
            <span class="gm-score-label">{label}</span>
            <span class="gm-score-value" style="color:{color};">{score}/{mx}</span>
        </div>
        <div class="gm-score-track">
            <div class="gm-score-fill {fill_class}" style="width:{pct}%;"></div>
            <div class="gm-score-threshold" style="left:{tp}%;"></div>
        </div>
        <div class="gm-score-meta">
            <span>Eşik: {thr}</span>
            <span>{'✅ Geçti' if score >= thr else '❌ Geçemedi'}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_eligibility(elig):
    icon_map = {"pass": "✅", "fail": "❌", "warning": "⚠️", "info": "ℹ️", "unable": "❓"}
    with st.expander(f"{'✅' if elig.is_eligible else '❌'} Uygunluk Kontrolü", expanded=not elig.is_eligible):
        for ch in elig.results:
            st.markdown(f"{icon_map.get(ch.status.value, '')} **{ch.check_name}**: {ch.message}")
            if ch.details:
                st.caption(ch.details)


def render_criterion(crit, coach, show_coach):
    name = crit.get("criterion", "?")
    score = crit.get("score", 0)
    mx = crit.get("max_score", 5)
    thr = crit.get("threshold", 3)
    render_score_bar(score, mx, thr, name)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f'<div class="gm-metric"><div class="gm-metric-value" style="font-size:1.2rem;">{crit.get("confidence_low", "?")} – {crit.get("confidence_high", "?")}</div><div class="gm-metric-label">Güven Aralığı</div></div>', unsafe_allow_html=True)
    with c2:
        risk = crit.get("consensus_risk", "?")
        ri = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(risk, "⚪")
        st.markdown(f'<div class="gm-metric"><div class="gm-metric-value" style="font-size:1.2rem;">{ri} {risk}</div><div class="gm-metric-label">Uzlaşma Riski</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="gm-metric"><div class="gm-metric-value" style="font-size:1.2rem;">{crit.get("weighted_score", 0):.1f}</div><div class="gm-metric-label">Ağırlıklı Puan</div></div>', unsafe_allow_html=True)

    st.markdown("")
    st.markdown("#### 📋 ESR Yorumu")
    st.info(crit.get("esr_comment", "N/A"))

    topic_align = crit.get("topic_alignment", "")
    if topic_align:
        with st.expander("🎯 Çağrı/Topic Uyumu"):
            st.markdown(topic_align)

    col_s, col_w = st.columns(2)
    with col_s:
        st.markdown("##### ✅ Güçlü Yönler")
        for s_item in crit.get("strengths", []):
            st.markdown(f"- {s_item}")
        if not crit.get("strengths"):
            st.caption("Tespit edilemedi.")
    with col_w:
        st.markdown("##### ❌ Zayıf Yönler")
        for w_item in crit.get("weaknesses", []):
            st.markdown(f"- {w_item}")
        if not crit.get("weaknesses"):
            st.caption("Tespit edilemedi.")

    cats = crit.get("weakness_categories", [])
    if cats:
        badges = " ".join(
            f'<span style="background:#f1f5f9;border:1px solid #e2e8f0;padding:0.2rem 0.6rem;border-radius:12px;font-size:0.75rem;font-weight:600;color:#475569;margin-right:0.3rem;">{WEAKNESS_TAXONOMY.get(c, {}).get("label", c)}</span>'
            for c in cats
        )
        st.markdown(f"**🏷️ Kategoriler:** {badges}", unsafe_allow_html=True)

    subs = crit.get("sub_signal_assessments", [])
    if subs:
        with st.expander("📊 Alt Sinyaller"):
            for sa in subs:
                r = sa.get("rating", "?")
                ic = {"strong": "🟢", "adequate": "🟡", "weak": "🟠", "missing": "🔴"}.get(r, "⚪")
                st.markdown(f"{ic} **{sa.get('signal', '?')}** — {r}")
                if sa.get("evidence"):
                    st.caption(f'Kanıt: "{sa["evidence"][:150]}"')
                if sa.get("comment"):
                    st.caption(sa["comment"])

    alt = crit.get("alternative_reading", "")
    if alt:
        with st.expander("🔄 Alternatif Okuma"):
            st.markdown(alt)

    if show_coach and coach:
        st.markdown("---")
        st.markdown("#### 🎯 Koçluk Önerileri")
        for imp in coach.get("improvements", []):
            with st.expander(f"🔧 P{imp.get('priority', '?')}: {imp.get('title', '?')} ({imp.get('expected_score_gain', '?')})"):
                st.markdown(f"**Problem:** {imp.get('problem', '')}")
                st.markdown(f"**Etki:** {imp.get('impact', '')}")
                st.markdown(f"**Çözüm:** {imp.get('solution', '')}")
        if coach.get("summary"):
            st.markdown(f"**📝 Özet:** {coach['summary']}")


def render_overall(results):
    st.markdown("""
    <div class="gm-section-header">
        <span class="gm-section-icon">📊</span>
        <h2>Genel Değerlendirme Özeti</h2>
    </div>
    """, unsafe_allow_html=True)

    tw = results["total_weighted"]
    tm = results["total_max"]
    thr = results["total_threshold"]
    met = results["total_threshold_met"]
    fp = results.get("funding_probability", "very_low")
    fp_pct = results.get("funding_probability_pct", 0)
    pl = {"high": "🟢 Yüksek", "medium": "🟡 Orta", "low": "🟠 Düşük", "very_low": "🔴 Çok Düşük"}
    fp_label = pl.get(fp, "?")
    ok = sum(1 for c in results["criteria"] if c.get("threshold_met"))
    total_criteria = len(results["criteria"])
    sys_issues = len(results.get("cross_cutting_issues", []))

    total_color = "#10b981" if met else "#f59e0b" if tw >= thr * 0.8 else "#ef4444"
    fp_color = {"high": "#10b981", "medium": "#f59e0b", "low": "#f97316", "very_low": "#ef4444"}.get(fp, "#ef4444")

    c1, c2, c3, c4 = st.columns(4)
    delta_val = tw - thr
    delta_sign = "+" if delta_val >= 0 else ""
        with c1:
        st.markdown(f"""
        <div class="gm-metric">
            <div class="gm-metric-value" style="color:{total_color};">{tw}/{tm}</div>
            <div class="gm-metric-label">Toplam Ağırlıklı Puan</div>
            <div class="gm-metric-delta" style="color:{total_color};">{delta_sign}{delta_val:.1f} eşikten</div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="gm-metric">
            <div class="gm-metric-value" style="color:{fp_color};">%{fp_pct}</div>
            <div class="gm-metric-label">Fonlanma Olasılığı</div>
            <div class="gm-metric-delta" style="color:{fp_color};">{fp_label}</div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        crit_color = "#10b981" if ok == total_criteria else "#f59e0b" if ok > 0 else "#ef4444"
        st.markdown(f"""
        <div class="gm-metric">
            <div class="gm-metric-value" style="color:{crit_color};">{ok}/{total_criteria}</div>
            <div class="gm-metric-label">Kriter Eşik Geçen</div>
            <div class="gm-metric-delta">{'✅ Tümü geçti' if ok == total_criteria else '⚠️ Eksik var'}</div>
        </div>
        """, unsafe_allow_html=True)
    with c4:
        sys_color = "#10b981" if sys_issues == 0 else "#f59e0b" if sys_issues <= 2 else "#ef4444"
        st.markdown(f"""
        <div class="gm-metric">
            <div class="gm-metric-value" style="color:{sys_color};">{sys_issues}</div>
            <div class="gm-metric-label">Sistemik Sorun</div>
            <div class="gm-metric-delta">{'✅ Temiz' if sys_issues == 0 else '⚠️ Dikkat'}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

    cols = st.columns(len(results["criteria"]))
    for i, cr in enumerate(results["criteria"]):
        with cols[i]:
            render_score_bar(cr["score"], cr["max_score"], cr["threshold"], cr.get("criterion", f"K{i + 1}"))

    cross = results.get("cross_cutting_issues", [])
    if cross:
        st.markdown("### ⚠️ Kriterler Arası Sistemik Sorunlar")
        for iss in cross:
            st.warning(iss)

    dp = results.get("double_penalization_warnings", [])
    if dp:
        st.markdown("### 🔄 Çift Cezalandırma Uyarıları")
        for w in dp:
            st.warning(w)


# ═══════════════════════════════════════════════════════════
# PAGES
# ═══════════════════════════════════════════════════════════
def render_calls_page():
    selected_call = render_call_dashboard()
    if selected_call:
        st.markdown("---")
        call_ctx = render_call_detail(selected_call)
        st.session_state["selected_call"] = selected_call
        st.session_state["call_context"] = call_ctx
        col_a, col_b = st.columns(2)
        with col_a:
            st.info("💡 Değerlendirme yapmak için **Değerlendirme** sayfasına geçin.")
        with col_b:
            if st.button("🔬 Değerlendirmeye Git", type="primary", use_container_width=True):
                st.session_state["page_nav"] = "eval"
                st.rerun()


def render_evaluation_page():
    # ── SIDEBAR ──
    with st.sidebar:
        st.markdown("## ⚙️ Ayarlar")

        has_call = "selected_call" in st.session_state
        if has_call:
            call_data = st.session_state["selected_call"]
            detected_at = detect_action_type_from_call(call_data)
            st.success(f"📡 {call_data.get('call_id', '?')}")
            st.caption(f"Otomatik: {detected_at}")
            action = get_action_type_from_string(detected_at)
            use_call = st.checkbox("Çağrı bağlamını kullan", value=True)
        else:
            labels = {
                ActionType.RIA: "🔬 RIA",
                ActionType.IA: "🚀 IA",
                ActionType.CSA: "🤝 CSA",
                ActionType.MSCA_DN: "🎓 MSCA-DN",
                ActionType.EIC_PATHFINDER_OPEN: "💡 EIC Pathfinder",
                ActionType.EIC_ACCELERATOR: "📈 EIC Accelerator",
                ActionType.ERC_STG: "⭐ ERC StG",
            }
            action = st.selectbox("Aksiyon Türü", list(labels.keys()), format_func=lambda x: labels[x])
            use_call = False

        auto_action = st.session_state.get("auto_action_type", None)
        if auto_action and not has_call:
            action = auto_action
            st.info(f"🎯 AI: {action.value}")

        cfg = ACTION_TYPE_CONFIGS[action]
        with st.expander("ℹ️ Kriter Detayları"):
            for cr in cfg.criteria:
                st.markdown(f"**{cr.name}** (ağırlık: {cr.weight}, eşik: {cr.threshold}/{cr.max_score})")
                for q in cr.official_questions:
                    st.caption(f"  • {q}")

        st.markdown("---")
        mode = st.radio(
            "Çıktı", ["both", "esr_only", "coaching_only"],
            format_func=lambda x: {"both": "📋+🎯 Tam", "esr_only": "📋 ESR", "coaching_only": "🎯 Koçluk"}[x],
        )

        st.markdown("---")
        manual_ctx = st.text_area("Ek Bağlam (opsiyonel)", height=80, placeholder="Work Programme scope, expected outcomes...")
        blind = st.checkbox("🔒 Kimlik taraması", value=cfg.blind_evaluation)

        st.markdown("---")
        st.markdown("### 🧠 AI Ayarları")
        use_ai_rag = st.checkbox("RAG ile zenginleştirilmiş değerlendirme", value=True,
                                  help="AI bilgi tabanını kullanarak her kriter için özel rehberlik üretir")
        st.caption("⚠️ Bu araç resmî EC değerlendirmesinin yerini almaz.")

    # ── MAIN ──
    st.markdown("""
    <div class="gm-section-header">
        <span class="gm-section-icon">📤</span>
        <h2>Teklif Yükleme</h2>
    </div>
    """, unsafe_allow_html=True)

    uploaded = st.file_uploader("Horizon Europe Part B (PDF / DOCX)", type=["pdf", "docx", "doc"])

    if not uploaded:
        st.markdown("""
        <div class="gm-section-header">
            <span class="gm-section-icon">🎯</span>
            <h2>GrantMirror-AI Ne Yapar?</h2>
        </div>
        <div class="gm-feature-grid">
            <div class="gm-feature-item"><div class="gm-feature-icon">📡</div><h4>Canlı Çağrı Verisi</h4><p>EC API'den açık çağrıları gerçek zamanlı çeker, Excel'e aktarır</p></div>
            <div class="gm-feature-item"><div class="gm-feature-icon">🎯</div><h4>AI Çağrı Eşleştirme</h4><p>Teklifinizi en uygun çağrılarla otomatik eşleştirir</p></div>
            <div class="gm-feature-item"><div class="gm-feature-icon">🧠</div><h4>RAG Bilgi Motoru</h4><p>Kriter bazlı AI-destekli bilgi sentezi</p></div>
            <div class="gm-feature-item"><div class="gm-feature-icon">📋</div><h4>ESR Simülasyonu</h4><p>Çağrıya özel kriter bazlı hakem değerlendirmesi</p></div>
            <div class="gm-feature-item"><div class="gm-feature-icon">🎯</div><h4>Akıllı Koçluk</h4><p>Somut düzeltme önerileri, beklenen puan etkisiyle</p></div>
            <div class="gm-feature-item"><div class="gm-feature-icon">📊</div><h4>Güven & Uzlaşma</h4><p>Puan aralığı + uzlaşma riski + fonlanma olasılığı</p></div>
            <div class="gm-feature-item"><div class="gm-feature-icon">🔒</div><h4>Kimlik Taraması</h4><p>Kör çağrılar için kimlik ifşa tespiti</p></div>
            <div class="gm-feature-item"><div class="gm-feature-icon">🏷️</div><h4>Zayıflık Taksonomisi</h4><p>12 kategorili sınıflandırma + çift ceza kontrolü</p></div>
        </div>
        """, unsafe_allow_html=True)
        return

    fb = uploaded.read()
    fn = uploaded.name

    # Parse
    with st.spinner("📄 Belge okunuyor ve yapısı analiz ediliyor..."):
        try:
            proposal = parse_proposal(fb, fn)
        except Exception as e:
            st.error(f"❌ Belge hatası: {e}")
            return

    with st.expander("📄 Belge Özeti", expanded=False):
        dc1, dc2, dc3, dc4 = st.columns(4)
        with dc1:
            st.markdown(f'<div class="gm-metric"><div class="gm-metric-value">{proposal.total_pages}</div><div class="gm-metric-label">Sayfa</div></div>', unsafe_allow_html=True)
        with dc2:
            st.markdown(f'<div class="gm-metric"><div class="gm-metric-value">{proposal.total_words:,}</div><div class="gm-metric-label">Kelime</div></div>', unsafe_allow_html=True)
        with dc3:
            st.markdown(f'<div class="gm-metric"><div class="gm-metric-value">{len(proposal.sections)}</div><div class="gm-metric-label">Bölüm</div></div>', unsafe_allow_html=True)
        with dc4:
            st.markdown(f'<div class="gm-metric"><div class="gm-metric-value">{len(proposal.trl_mentions)}</div><div class="gm-metric-label">TRL Ref</div></div>', unsafe_allow_html=True)
        for s, d in proposal.sections.items():
            st.write(f"- **{s.value}**: {d.word_count} kelime (sayfa {d.page_start}-{d.page_end})")
        for w in proposal.warnings:
            st.warning(w)

    # ── AI CALL MATCHING ──
    st.markdown("""
    <div class="gm-section-header">
        <span class="gm-section-icon">🎯</span>
        <h2>Otomatik Çağrı Eşleştirme</h2>
    </div>
    """, unsafe_allow_html=True)

    match_col1, match_col2 = st.columns([1, 1])
    with match_col1:
        use_ai_match = st.checkbox("🧠 AI ile eşleştir (daha doğru, ~10s)", value=True)
    with match_col2:
        match_btn = st.button("🔍 Çağrı Eşleştir", use_container_width=True)

    if match_btn or "matched_calls" not in st.session_state:
        with st.spinner("🔍 Teklif analiz ediliyor ve çağrılarla eşleştiriliyor..."):
            if use_ai_match:
                try:
                    client = get_llm_client()
                    matches = ai_match_calls(proposal.full_text, llm_call_wrapper(client), top_k=5)
                except Exception:
                    matches = [
                        {**c, "ai_match_score": round(s * 100, 1), "ai_match_reason": "Keyword match",
                         "suggested_action_type": c["action_types"][0]}
                        for c, s in keyword_match_calls(proposal.full_text, top_k=5)
                    ]
            else:
                matches = [
                    {**c, "ai_match_score": round(s * 100, 1), "ai_match_reason": "Keyword match",
                     "suggested_action_type": c["action_types"][0]}
                    for c, s in keyword_match_calls(proposal.full_text, top_k=5)
                ]
            st.session_state["matched_calls"] = matches

    matches = st.session_state.get("matched_calls", [])

    if matches:
        for i, m in enumerate(matches):
            score = m.get("ai_match_score", 0)
            if score >= 70:
                match_badge, score_icon = "gm-match-high", "🟢"
            elif score >= 40:
                match_badge, score_icon = "gm-match-medium", "🟡"
            else:
                match_badge, score_icon = "gm-match-low", "🔴"

            with st.expander(
                f"{score_icon} {m['call_id']} — Uyum: {score}/100 | {', '.join(m.get('action_types', []))}",
                expanded=(i == 0),
            ):
                st.markdown(f"""
                <div class="gm-card" style="margin-bottom:1rem;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.8rem;">
                        <h4 style="margin:0;color:#1e293b;">{m.get('destination', m.get('call_id', ''))}</h4>
                        <span class="{match_badge}">Uyum: {score}/100</span>
                    </div>
                    <p style="color:#64748b;font-size:0.9rem;margin:0.5rem 0;">📝 {m.get('ai_match_reason', '')}</p>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;margin-top:0.8rem;">
                        <div><strong style="color:#64748b;font-size:0.8rem;">🏷️ Aksiyon:</strong> {m.get('suggested_action_type', '?')}</div>
                        <div><strong style="color:#64748b;font-size:0.8rem;">💰 Bütçe:</strong> {m.get('budget_per_project', 'N/A')}</div>
                        <div><strong style="color:#64748b;font-size:0.8rem;">📅 Son Tarih:</strong> {m.get('deadline', 'N/A')}</div>
                        <div><strong style="color:#64748b;font-size:0.8rem;">📊 Durum:</strong> {m.get('status', 'N/A')}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                with st.expander("📋 Detaylar"):
                    st.markdown(f"**Beklenen Çıktılar:** {m.get('expected_outcomes', 'N/A')}")
                    st.markdown(f"**Kapsam:** {m.get('scope', 'N/A')}")

                if st.button(f"✅ Bu çağrıyı kullan", key=f"use_match_{i}"):
                    st.session_state["auto_call_ctx"] = build_call_eval_context(m)
                    suggested = m.get("suggested_action_type", "")
                    if suggested:
                        try:
                            st.session_state["auto_action_type"] = get_action_type_from_string(suggested)
                        except Exception:
                            pass
                    st.success(f"✅ {m['call_id']} bağlamı değerlendirmeye eklendi!")
                    st.rerun()
    else:
        st.info("Eşleşen çağrı bulunamadı. Manuel olarak çağrı bağlamı girebilirsiniz.")

    # Eligibility
    with st.spinner("✅ Uygunluk kontrolleri çalıştırılıyor..."):
        elig = run_eligibility_checks(proposal, action)
    render_eligibility(elig)

    # Blind scan
    if blind:
        sigs = scan_for_identity_signals(proposal.full_text, proposal.partner_names, proposal.person_names)
        rpt = generate_deidentification_report(sigs)
        with st.expander(f"🔒 Kimlik Taraması ({len(sigs)} sinyal)", expanded=len(sigs) > 0):
            st.markdown(rpt)

    # Build call context
    call_ctx_text = ""
    auto_ctx = st.session_state.get("auto_call_ctx", "")
    if auto_ctx:
        call_ctx_text = auto_ctx
    if has_call and use_call and not call_ctx_text:
        call_context = st.session_state.get("call_context", {})
        call_ctx_text = call_context.get("evaluation_context", "")
    if manual_ctx:
        call_ctx_text = (call_ctx_text + "\n\n" + manual_ctx) if call_ctx_text else manual_ctx

    # ── EVALUATE ──
    st.markdown("""
    <div class="gm-section-header">
        <span class="gm-section-icon">🚀</span>
        <h2>Değerlendirme</h2>
    </div>
    """, unsafe_allow_html=True)

    n = len(cfg.criteria)
    c_b, c_i = st.columns([1, 2])
    with c_b:
        go = st.button("🔬 Değerlendirmeyi Başlat", type="primary", use_container_width=True)
    with c_i:
        ctx_note = " + 📡 Çağrı" if call_ctx_text else ""
        rag_note = " + 🧠 RAG" if use_ai_rag else ""
        st.info(f"**{action.value}**: {n} kriter{ctx_note}{rag_note} · ~{n * 30}-{n * 60}s")

    if not go:
        return

    client = get_llm_client()
    kb = HorizonKnowledgeBase()
    ev = Evaluator(client, kb)
    pbar = st.progress(0.0)
    status_el = st.empty()
    step = [0]
    total_steps = n * 3

    def on_p(msg):
        status_el.markdown(f"⏳ {msg}")
        step[0] += 1
        pbar.progress(min(step[0] / total_steps, 1.0))

    results = ev.run(proposal, action, call_ctx_text, on_p, use_ai_rag=use_ai_rag)
    pbar.progress(1.0)
    status_el.markdown("✅ Değerlendirme tamamlandı!")
    time.sleep(0.5)
    status_el.empty()
    pbar.empty()

    # Display
    st.markdown("---")
    render_overall(results)

    st.markdown("""
    <div class="gm-section-header">
        <span class="gm-section-icon">📝</span>
        <h2>Kriter Detayları</h2>
    </div>
    """, unsafe_allow_html=True)

    show_coach = mode in ("both", "coaching_only")
    tab_names = [c.get("criterion", f"K{i + 1}") for i, c in enumerate(results["criteria"])]
    tabs = st.tabs(tab_names)
    for i, tab in enumerate(tabs):
        with tab:
            cd = results["criteria"][i]
            co = results["coaching"][i] if i < len(results["coaching"]) else {}
            render_criterion(cd, co, show_coach)

    # Downloads
    st.markdown("""
    <div class="gm-section-header">
        <span class="gm-section-icon">📥</span>
        <h2>Raporları İndir</h2>
    </div>
    """, unsafe_allow_html=True)

    d1, d2, d3 = st.columns(3)
    elig_dicts = [{"check_name": ch.check_name, "status": ch.status.value, "message": ch.message} for ch in elig.results]
    with d1:
        st.download_button("📊 JSON Rapor", json.dumps(results, indent=2, ensure_ascii=False),
                           f"grantmirror_{fn}.json", "application/json", use_container_width=True)
    with d2:
        st.download_button("📋 ESR Rapor (MD)", generate_esr_report(results, elig_dicts),
                           f"grantmirror_{fn}_esr.md", "text/markdown", use_container_width=True)
    with d3:
        st.download_button("🎯 Koçluk Rapor (MD)", generate_coaching_report(results),
                           f"grantmirror_{fn}_coach.md", "text/markdown", use_container_width=True)

    # DEBUG
    with st.expander("🔧 DEBUG Panel"):
        st.markdown("### Sistem Bilgileri")
        dcol1, dcol2, dcol3 = st.columns(3)
        with dcol1:
            st.metric("Proposal Uzunluğu", f"{proposal.total_words:,} kelime")
            st.metric("Sayfa Sayısı", proposal.total_pages)
        with dcol2:
            st.metric("Tespit Edilen Bölüm", len(proposal.sections))
            st.metric("TRL Referansı", len(proposal.trl_mentions))
        with dcol3:
            st.metric("KPI Referansı", len(proposal.kpi_mentions))
            st.metric("Partner Adı", len(proposal.partner_names))

        st.markdown("### Eşleşen Çağrı")
        if matches:
            st.json({"top_match": matches[0].get("call_id", "?"),
                      "match_score": matches[0].get("ai_match_score", 0),
                      "action_type": matches[0].get("suggested_action_type", "?")})
        else:
            st.write("Eşleşme yok")

        st.markdown("### Çağrı Bağlamı")
        if call_ctx_text:
            st.text_area("Context", call_ctx_text[:1000], height=150, disabled=True)
        else:
            st.write("Bağlam yok")

        st.markdown("### Bölüm Tespiti")
        for sec_type, sec_data in proposal.sections.items():
            st.write(f"- **{sec_type.value}**: {sec_data.word_count} kelime, sayfa {sec_data.page_start}-{sec_data.page_end}")

        st.markdown("### Funding Probability Detay")
        fp_dbg = results.get("funding_probability_pct", 0)
        tw_dbg = results.get("total_weighted", 0)
        tm_dbg = results.get("total_max", 0)
        st.write(f"Score ratio: {tw_dbg}/{tm_dbg} = {tw_dbg / tm_dbg * 100:.1f}%" if tm_dbg > 0 else "N/A")
        st.write(f"Funding probability: {fp_dbg}%")
        st.progress(fp_dbg / 100)

        st.markdown("### AI Ayarları")
        st.write(f"AI RAG aktif: {use_ai_rag}")
        st.write(f"AI eşleştirme: {use_ai_match}")
        st.write(f"Model: {MODEL_NAME}")
        st.write(f"Call DB boyutu: {len(HORIZON_CALLS_DB)} çağrı")

        st.markdown("### Ham Sonuçlar")
        st.json(results)


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
def main():
    render_header()

    nav = st.session_state.pop("page_nav", None)

    page = st.sidebar.radio(
        "📌 Sayfa",
        ["🔬 Değerlendirme", "📡 Canlı Çağrılar"],
        index=0 if nav != "eval" else 0,
        label_visibility="collapsed",
    )

    with st.sidebar:
        st.markdown("---")
        stats = get_call_stats()
        st.caption(
            f"📊 DB: {stats['total']} çağrı | "
            f"🟢 {stats['open']} açık | "
            f"🟡 {stats['forthcoming']} yaklaşan"
        )

    if page == "📡 Canlı Çağrılar":
        render_calls_page()
    else:
        render_evaluation_page()


if __name__ == "__main__":
    main()
        
