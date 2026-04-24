"""
GrantMirror-AI: Horizon Europe Proposal Pre-Screening & ESR Simulator
AI-powered call matching, RAG knowledge engine, section-aware scoring.
"""
import streamlit as st
import json
import time
import os
from typing import Dict, List, Optional
from collections import Counter
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
    fetch_horizon_calls, fetch_topic_details,
    detect_action_type_from_call, build_call_specific_criteria, CallCache,
)
from call_db import keyword_match_calls, ai_match_calls, build_call_eval_context, HORIZON_CALLS_DB
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

# Initialize cache in session state
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
        messages=[
            {"role": "system", "content": sys_p},
            {"role": "user", "content": usr_p},
        ],
        temperature=temp,
        max_tokens=max_tok,
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
    """Create a simple LLM call function for modules that need it."""
    def _call(sys_prompt, usr_prompt):
        return call_llm(client, sys_prompt, usr_prompt, temp=0.3, max_tok=3000, js=True)
    return _call


# ═══════════════════════════════════════════════════════════
# PROMPTS (enhanced per research report)
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
    """Enhanced funding probability label."""
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
    """Numeric funding probability estimate (0-100)."""
    if not all_met or total < threshold:
        return 5

    if max_score <= 0:
        return 5

    ratio = total / max_score
    # Non-linear mapping based on typical Horizon success rates
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

    # Confidence adjustment based on how close to threshold
    margin = total - threshold
    if margin < 1.0:
        base = int(base * 0.7)  # Close to threshold = less certain

    return min(base, 95)


def _check_double_penalization(criteria: List[Dict]) -> List[str]:
    """Check if similar weaknesses appear in multiple criteria (research report requirement)."""
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
                warnings.append(
                    f"⚠️ Benzer zayıflık {c1} ve {c2}'de tespit edildi — çift cezalandırma riski"
                )
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
            "Excellence": [
                SectionType.EXCELLENCE,
                SectionType.OPEN_SCIENCE,
                SectionType.GENDER_DIMENSION,
            ],
            "Impact": [
                SectionType.IMPACT,
                SectionType.DISSEMINATION,
                SectionType.EXPLOITATION,
            ],
            "Implementation": [
                SectionType.IMPLEMENTATION,
                SectionType.WORK_PACKAGES,
                SectionType.RISK_TABLE,
            ],
        }
        texts = [
            proposal.sections[s].content
            for s in mapping.get(criterion, [])
            if s in proposal.sections
        ]
        if texts:
            return "\n\n".join(texts)
        t = proposal.full_text
        n = len(t)
        if criterion == "Excellence":
            return t[: n // 3]
        elif criterion == "Impact":
            return t[n // 3 : 2 * n // 3]
        return t[2 * n // 3 :]

    def _cross_ctx(self, proposal):
        return "\n".join(
            f"[{s.value}]: {d.content[:400]}"
            for s, d in proposal.sections.items()
            if d.word_count > 50
        )

    def _get_rag_context(self, criterion, action_type, section_text, use_ai_rag=True):
        """Get RAG-enhanced knowledge context."""
        if use_ai_rag:
            try:
                return ai_enhanced_retrieval(
                    criterion, action_type, section_text, self.llm_fn
                )
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

            # SECTION-AWARE: get correct section text
            sec = self._section_text(proposal, cc.name)
            cross = self._cross_ctx(proposal)

            # RAG-ENHANCED: get AI-synthesized knowledge context
            if on_progress:
                on_progress(f"🧠 {cc.name} bilgi tabanı hazırlanıyor...")
            kb_ctx = self._get_rag_context(cc.name, action_type.value, sec, use_ai_rag)

            prompt = build_eval_prompt(cc, sec, cross, kb_ctx, action_type.value, call_ctx)
            raw = call_llm(self.client, SYS_ESR, prompt)

            try:
                r = json.loads(raw)
            except json.JSONDecodeError:
                r = {
                    "criterion": cc.name,
                    "score": 0,
                    "confidence_low": 0,
                    "confidence_high": 0,
                    "consensus_risk": "high",
                    "strengths": [],
                    "weaknesses": ["JSON parse hatası"],
                    "weakness_categories": [],
                    "sub_signal_assessments": [],
                    "esr_comment": "Parse hatası.",
                    "alternative_reading": "",
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

            # Coaching
            if on_progress:
                on_progress(f"💡 {cc.name} koçluk...")
            raw2 = call_llm(
                self.client,
                SYS_COACH,
                build_coach_prompt(
                    cc.name,
                    s,
                    r.get("weaknesses", []),
                    r.get("weakness_categories", []),
                    sec,
                    cc.practical_checklist,
                ),
                temp=0.4,
            )
            try:
                co = json.loads(raw2)
            except json.JSONDecodeError:
                co = {"improvements": [], "summary": "Koçluk üretilemedi."}
            co["criterion"] = cc.name
            results["coaching"].append(co)

        # Aggregation
        results["total_weighted"] = round(total_w, 1)
        results["total_max"] = cfg.total_max
        results["total_threshold"] = cfg.total_threshold
        results["total_threshold_met"] = all_met and total_w >= cfg.total_threshold
        results["all_criteria_met"] = all_met

        # ENHANCED funding probability
        results["funding_probability"] = _calc_funding_probability(
            total_w, cfg.total_max, cfg.total_threshold, all_met
        )
        results["funding_probability_pct"] = _calc_funding_pct(
            total_w, cfg.total_max, cfg.total_threshold, all_met
        )

        # Cross-cutting weakness detection
        cats = []
        for c in results["criteria"]:
            cats.extend(c.get("weakness_categories", []))
        cc2 = Counter(cats)
        results["cross_cutting_issues"] = [
            f"'{WEAKNESS_TAXONOMY[k]['label']}' — {v} kriterde: {WEAKNESS_TAXONOMY[k]['description']}"
            for k, v in cc2.items()
            if v > 1 and k in WEAKNESS_TAXONOMY
        ]

        # Double-penalization check
        results["double_penalization_warnings"] = _check_double_penalization(
            results["criteria"]
        )

        return results


# ═══════════════════════════════════════════════════════════
# UI COMPONENTS
# ═══════════════════════════════════════════════════════════
def render_header():
    st.markdown(
        """
    <div style="text-align:center;padding:1rem 0;">
        <h1 style="font-size:2.4rem;font-weight:800;color:#1a1a2e;margin-bottom:0.2rem;">
            🔬 GrantMirror-AI
        </h1>
        <p style="font-size:1.1rem;color:#555;">
            Horizon Europe Proposal Pre-Screening & ESR Simulator
        </p>
        <p style="font-size:0.85rem;color:#888;">
            Canlı çağrı verisi · AI çağrı eşleştirme · RAG bilgi motoru ·
            Hakem simülasyonu · ESR eleştiri tahmini · Düzeltme planı
        </p>
    </div><hr>""",
        unsafe_allow_html=True,
    )


def render_call_dashboard():
    """Render live call data dashboard."""
    st.markdown("## 📡 Canlı Çağrı Paneli")

    col1, col2, col3 = st.columns(3)
    with col1:
        search = st.text_input("🔍 Arama", placeholder="Anahtar kelime...")
    with col2:
        status_filter = st.selectbox(
            "📋 Durum",
            ["", "Open", "Forthcoming", "Closed"],
            format_func=lambda x: x if x else "Tümü",
        )
    with col3:
        programme_filter = st.selectbox(
            "🏛️ Program",
            ["HORIZON", ""],
            format_func=lambda x: x if x else "Tümü",
        )

    # Fetch with cache
    cache_key = f"calls_{search}_{status_filter}_{programme_filter}"
    cached = st.session_state.call_cache.get(cache_key)

    if cached:
        calls, total = cached
    else:
        with st.spinner("📡 EC API'den çağrılar çekiliyor..."):
            calls, total = fetch_horizon_calls(
                programme=programme_filter,
                status=status_filter,
                search_text=search,
                page_size=30,
            )
            st.session_state.call_cache.set(cache_key, (calls, total))

    if not calls:
        st.info(
            "Çağrı bulunamadı veya API yanıt vermedi. Arama kriterlerini değiştirin."
        )
        return None

    st.markdown(f"**{total}** çağrı bulundu (ilk {len(calls)} gösteriliyor)")

    # Display calls as cards
    selected_call = None
    for i, call in enumerate(calls):
        status = call.get("status", "?")
        status_color = {"Open": "🟢", "Forthcoming": "🟡", "Closed": "🔴"}.get(
            status, "⚪"
        )
        action_types = ", ".join(call.get("action_types", ["?"]))
        deadline = call.get("deadline", "N/A")
        if deadline and len(deadline) > 10:
            deadline = deadline[:10]

        with st.container():
            cols = st.columns([0.5, 4, 1.5, 1.5, 1])
            with cols[0]:
                st.markdown(f"### {status_color}")
            with cols[1]:
                st.markdown(f"**{call.get('title', 'N/A')[:80]}**")
                topics = call.get("topics", [])
                if topics:
                    st.caption(
                        f"Topics: {', '.join(t.get('topic_id', '') for t in topics[:3])}"
                    )
            with cols[2]:
                st.caption(f"📅 {deadline}")
            with cols[3]:
                st.caption(f"🏷️ {action_types}")
            with cols[4]:
                if st.button("Seç", key=f"call_{i}", use_container_width=True):
                    selected_call = call

        st.markdown(
            "<hr style='margin:0.2rem 0;border:none;border-top:1px solid #eee;'>",
            unsafe_allow_html=True,
        )

    return selected_call


def render_call_detail(call_data: Dict) -> Dict:
    """Show selected call details and fetch topic info."""
    st.markdown("### 📋 Seçilen Çağrı Detayı")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Çağrı", call_data.get("call_id", "N/A"))
    with col2:
        st.metric(
            "Son Tarih",
            call_data.get("deadline", "N/A")[:10]
            if call_data.get("deadline")
            else "N/A",
        )
    with col3:
        action_type = detect_action_type_from_call(call_data)
        st.metric("Aksiyon Türü", action_type)

    st.markdown(f"**Başlık**: {call_data.get('title', 'N/A')}")

    # Fetch topic details
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

    # Build call-specific criteria context
    call_context = build_call_specific_criteria(call_data, topic_details)

    st.success(
        f"✅ Aksiyon türü: **{action_type}** | Çağrı-spesifik değerlendirme bağlamı hazır"
    )

    return call_context


def render_score_bar(score, mx, thr, label):
    pct = score / mx * 100 if mx > 0 else 0
    tp = thr / mx * 100 if mx > 0 else 0
    clr = (
        "#2ecc71"
        if score >= thr + 1
        else "#f39c12"
        if score >= thr
        else "#e74c3c"
    )
    st.markdown(
        f"""<div style="margin-bottom:1rem;">
        <div style="display:flex;justify-content:space-between;">
            <span style="font-weight:600;">{label}</span>
            <span style="font-weight:700;color:{clr};">{score}/{mx}</span>
        </div>
        <div style="background:#e8e8e8;border-radius:10px;height:22px;position:relative;overflow:hidden;">
            <div style="background:{clr};width:{pct}%;height:100%;border-radius:10px;"></div>
            <div style="position:absolute;left:{tp}%;top:0;height:100%;width:2px;background:#333;"></div>
        </div>
        <div style="font-size:0.75rem;color:#888;">
            Eşik: {thr} | {'✅' if score >= thr else '❌'}
        </div>
    </div>""",
        unsafe_allow_html=True,
    )


def render_eligibility(elig):
    icon_map = {"pass": "✅", "fail": "❌", "warning": "⚠️", "info": "ℹ️", "unable": "❓"}
    with st.expander(
        f"{'✅' if elig.is_eligible else '❌'} Uygunluk Kontrolü",
        expanded=not elig.is_eligible,
    ):
        for ch in elig.results:
            st.markdown(
                f"{icon_map.get(ch.status.value, '')} **{ch.check_name}**: {ch.message}"
            )
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
        st.metric(
            "Güven Aralığı",
            f"{crit.get('confidence_low', '?')} – {crit.get('confidence_high', '?')}",
        )
    with c2:
        risk = crit.get("consensus_risk", "?")
        ri = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(risk, "⚪")
        st.metric("Uzlaşma Riski", f"{ri} {risk}")
    with c3:
        st.metric("Ağırlıklı Puan", f"{crit.get('weighted_score', 0):.1f}")

    st.markdown("#### 📋 ESR Yorumu")
    st.info(crit.get("esr_comment", "N/A"))

    # Topic alignment (new)
    topic_align = crit.get("topic_alignment", "")
    if topic_align:
        with st.expander("🎯 Çağrı/Topic Uyumu"):
            st.markdown(topic_align)

    col_s, col_w = st.columns(2)
    with col_s:
        st.markdown("##### ✅ Güçlü Yönler")
        for s in crit.get("strengths", []):
            st.markdown(f"- {s}")
        if not crit.get("strengths"):
            st.caption("Tespit edilemedi.")
    with col_w:
        st.markdown("##### ❌ Zayıf Yönler")
        for w in crit.get("weaknesses", []):
            st.markdown(f"- {w}")
        if not crit.get("weaknesses"):
            st.caption("Tespit edilemedi.")

    cats = crit.get("weakness_categories", [])
    if cats:
        st.markdown(
            "**🏷️ Kategoriler:** "
            + " · ".join(
                f"`{WEAKNESS_TAXONOMY.get(c, {}).get('label', c)}`" for c in cats
            )
        )

    subs = crit.get("sub_signal_assessments", [])
    if subs:
        with st.expander("📊 Alt Sinyaller"):
            for sa in subs:
                r = sa.get("rating", "?")
                ic = {
                    "strong": "🟢",
                    "adequate": "🟡",
                    "weak": "🟠",
                    "missing": "🔴",
                }.get(r, "⚪")
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
        st.markdown("#### 🎯 Koçluk")
        for imp in coach.get("improvements", []):
            with st.expander(
                f"🔧 P{imp.get('priority', '?')}: {imp.get('title', '?')} "
                f"({imp.get('expected_score_gain', '?')})"
            ):
                st.markdown(f"**Problem:** {imp.get('problem', '')}")
                st.markdown(f"**Etki:** {imp.get('impact', '')}")
                st.markdown(f"**Çözüm:** {imp.get('solution', '')}")
        if coach.get("summary"):
            st.markdown(f"**Özet:** {coach['summary']}")


def render_overall(results):
    st.markdown("## 📊 Genel Özet")
    c1, c2, c3, c4 = st.columns(4)
    tw = results["total_weighted"]
    thr = results["total_threshold"]
    met = results["total_threshold_met"]

    with c1:
        st.metric(
            "Toplam",
            f"{tw}/{results['total_max']}",
            delta=f"{tw - thr:+.1f}" if met else f"{tw - thr:.1f}",
            delta_color="normal" if met else "inverse",
        )
    with c2:
        pl = {
            "high": "🟢 Yüksek",
            "medium": "🟡 Orta",
            "low": "🟠 Düşük",
            "very_low": "🔴 Çok Düşük",
        }
        fp_label = pl.get(results.get("funding_probability", ""), "?")
        fp_pct = results.get("funding_probability_pct", 0)
        st.metric("Fonlanma Olasılığı", f"{fp_label}", delta=f"~%{fp_pct}")
    with c3:
        ok = sum(1 for c in results["criteria"] if c.get("threshold_met"))
        st.metric("Kriter Eşik", f"{ok}/{len(results['criteria'])}")
    with c4:
        st.metric("Sistemik Sorun", len(results.get("cross_cutting_issues", [])))

    st.markdown("---")
    cols = st.columns(len(results["criteria"]))
    for i, cr in enumerate(results["criteria"]):
        with cols[i]:
            render_score_bar(
                cr["score"],
                cr["max_score"],
                cr["threshold"],
                cr.get("criterion", f"K{i + 1}"),
            )

    # Cross-cutting
    cross = results.get("cross_cutting_issues", [])
    if cross:
        st.markdown("### ⚠️ Kriterler Arası Sistemik Sorunlar")
        for iss in cross:
            st.warning(iss)

    # Double-penalization warnings (research report requirement)
    dp = results.get("double_penalization_warnings", [])
    if dp:
        st.markdown("### 🔄 Çift Cezalandırma Uyarıları")
        for w in dp:
            st.warning(w)


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
def main():
    render_header()

    # Navigation
    page = st.sidebar.radio(
        "📌 Sayfa",
        ["🔬 Değerlendirme", "📡 Canlı Çağrılar"],
        label_visibility="collapsed",
    )

    if page == "📡 Canlı Çağrılar":
        render_calls_page()
    else:
        render_evaluation_page()


def render_calls_page():
    """Page: Live call dashboard."""
    selected_call = render_call_dashboard()

    if selected_call:
        st.markdown("---")
        call_ctx = render_call_detail(selected_call)

        # Store for evaluation page
        st.session_state["selected_call"] = selected_call
        st.session_state["call_context"] = call_ctx

        st.info(
            "💡 Bu çağrı için değerlendirme yapmak isterseniz "
            "**Değerlendirme** sayfasına geçin ve teklif yükleyin."
        )


def render_evaluation_page():
    """Page: Proposal evaluation."""

    # ── SIDEBAR SETTINGS ──
    with st.sidebar:
        st.markdown("## ⚙️ Ayarlar")

        # Check if call was selected from dashboard
        has_call = "selected_call" in st.session_state
        if has_call:
            call_data = st.session_state["selected_call"]
            detected_at = detect_action_type_from_call(call_data)
            st.success(f"📡 Seçili çağrı: {call_data.get('call_id', '?')}")
            st.caption(f"Otomatik aksiyon türü: {detected_at}")
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
            action = st.selectbox(
                "Aksiyon Türü",
                list(labels.keys()),
                format_func=lambda x: labels[x],
            )
            use_call = False

        # Check for auto-detected action type from call matching
        auto_action = st.session_state.get("auto_action_type", None)
        if auto_action and not has_call:
            action = auto_action
            st.info(f"🎯 AI eşleştirmeden algılanan tür: {action.value}")

        cfg = ACTION_TYPE_CONFIGS[action]
        with st.expander("ℹ️ Kriter Detayları"):
            for cr in cfg.criteria:
                st.markdown(
                    f"**{cr.name}** (ağırlık: {cr.weight}, eşik: {cr.threshold}/{cr.max_score})"
                )
                for q in cr.official_questions:
                    st.caption(f"  • {q}")

        st.markdown("---")
        mode = st.radio(
            "Çıktı",
            ["both", "esr_only", "coaching_only"],
            format_func=lambda x: {
                "both": "📋+🎯 Tam",
                "esr_only": "📋 ESR",
                "coaching_only": "🎯 Koçluk",
            }[x],
        )

        st.markdown("---")
        manual_ctx = st.text_area(
            "Ek Bağlam (opsiyonel)",
            height=80,
            placeholder="Work Programme scope, expected outcomes...",
        )

        blind = st.checkbox("🔒 Kimlik taraması", value=cfg.blind_evaluation)

        st.markdown("---")
        st.markdown("### 🧠 AI Ayarları")
        use_ai_rag = st.checkbox(
            "RAG ile zenginleştirilmiş değerlendirme",
            value=True,
            help="AI bilgi tabanını kullanarak her kriter için özel rehberlik üretir",
        )

        st.caption("⚠️ Bu araç resmî EC değerlendirmesinin yerini almaz.")

    # ── MAIN AREA ──
    st.markdown("## 📤 Teklif Yükleme")
    uploaded = st.file_uploader(
        "Horizon Europe Part B (PDF / DOCX)", type=["pdf", "docx", "doc"]
    )

    if not uploaded:
        st.markdown(
            """---
### 🎯 GrantMirror-AI Ne Yapar?
| Özellik | Açıklama |
|---------|----------|
| 📡 Canlı Çağrı | EC API'den açık çağrıları çeker, topic detaylarını gösterir |
| 🎯 AI Eşleştirme | Teklifinizi en uygun çağrılarla otomatik eşleştirir |
| 🧠 RAG Bilgi Motoru | Kriter bazlı AI-destekli bilgi sentezi |
| 📋 ESR Simülasyonu | Çağrıya özel kriter bazlı hakem değerlendirmesi |
| 🔍 Uygunluk | Sayfa, konsorsiyum, bölüm, kör değerlendirme kontrolü |
| 🎯 Koçluk | Somut düzeltme önerileri, önceliklendirilmiş |
| 📊 Güven Aralığı | Puan aralığı + uzlaşma riski + alternatif okuma |
| 🔒 Kimlik Taraması | Kör çağrılar için kimlik ifşa tespiti |
| 🏷️ Taksonomi | 12 zayıflık kategorisi (ESR analizlerinden) |
| 🔄 Çift Ceza Kontrolü | Aynı kusurun birden fazla kriterde cezalandırılması uyarısı |
| 📈 Fonlanma Tahmini | Non-linear olasılık hesaplama (%0-95) |"""
        )
        return

    fb = uploaded.read()
    fn = uploaded.name

    # ── PARSE ──
    with st.spinner("📄 Belge okunuyor..."):
        try:
            proposal = parse_proposal(fb, fn)
        except Exception as e:
            st.error(f"❌ Belge hatası: {e}")
            return

    with st.expander("📄 Belge Özeti"):
        dc1, dc2, dc3 = st.columns(3)
        dc1.metric("Sayfa", proposal.total_pages)
        dc2.metric("Kelime", f"{proposal.total_words:,}")
        dc3.metric("Bölüm", len(proposal.sections))
        for s, d in proposal.sections.items():
            st.write(f"- {s.value}: {d.word_count} kelime")
        for w in proposal.warnings:
            st.warning(w)

    # ── AI CALL MATCHING ──
    st.markdown("### 🎯 Otomatik Çağrı Eşleştirme")

    match_col1, match_col2 = st.columns([1, 1])
    with match_col1:
        use_ai_match = st.checkbox(
            "🧠 AI ile eşleştir (daha doğru, ~10s)", value=True
        )
    with match_col2:
        match_btn = st.button("🔍 Çağrı Eşleştir", use_container_width=True)

    if match_btn or "matched_calls" not in st.session_state:
        with st.spinner("🔍 Teklif analiz ediliyor ve çağrılarla eşleştiriliyor..."):
            if use_ai_match:
                try:
                    client = get_llm_client()
                    matches = ai_match_calls(
                        proposal.full_text, llm_call_wrapper(client), top_k=3
                    )
                except Exception:
                    matches = [
                        {
                            **c,
                            "ai_match_score": round(s * 5, 1),
                            "ai_match_reason": "Keyword match",
                            "suggested_action_type": c["action_types"][0],
                        }
                        for c, s in keyword_match_calls(proposal.full_text, top_k=3)
                    ]
            else:
                matches = [
                    {
                        **c,
                        "ai_match_score": round(s * 5, 1),
                        "ai_match_reason": "Keyword match",
                        "suggested_action_type": c["action_types"][0],
                    }
                    for c, s in keyword_match_calls(proposal.full_text, top_k=3)
                ]
            st.session_state["matched_calls"] = matches

    matches = st.session_state.get("matched_calls", [])

    if matches:
        for i, m in enumerate(matches):
            score = m.get("ai_match_score", 0)
            score_color = "🟢" if score >= 70 else "🟡" if score >= 40 else "🔴"

            with st.expander(
                f"{score_color} {m['call_id']} — Uyum: {score}/100 | "
                f"{', '.join(m.get('action_types', []))}",
                expanded=(i == 0),
            ):
                st.markdown(
                    f"**{m.get('destination', m.get('call_id', ''))}**"
                )
                st.markdown(f"📝 {m.get('ai_match_reason', '')}")
                st.markdown(
                    f"🏷️ Önerilen aksiyon: **{m.get('suggested_action_type', '?')}**"
                )
                st.markdown(f"💰 Bütçe/proje: {m.get('budget_per_project', 'N/A')}")
                st.markdown(f"📅 Son tarih: {m.get('deadline', 'N/A')}")

                st.markdown(
                    f"**Beklenen Çıktılar:** {m.get('expected_outcomes', 'N/A')}"
                )
                st.markdown(f"**Kapsam:** {m.get('scope', 'N/A')}")

                if st.button(f"✅ Bu çağrıyı kullan", key=f"use_match_{i}"):
                    call_ctx_text_auto = build_call_eval_context(m)
                    st.session_state["auto_call_ctx"] = call_ctx_text_auto
                    suggested = m.get("suggested_action_type", "")
                    if suggested:
                        try:
                            st.session_state["auto_action_type"] = (
                                get_action_type_from_string(suggested)
                            )
                        except Exception:
                            pass
                    st.success(
                        f"✅ {m['call_id']} bağlamı değerlendirmeye eklendi!"
                    )
                    st.rerun()
    else:
        st.info(
            "Eşleşen çağrı bulunamadı. Manuel olarak çağrı bağlamı girebilirsiniz."
        )

    # ── ELIGIBILITY ──
    with st.spinner("✅ Uygunluk kontrolleri..."):
        elig = run_eligibility_checks(proposal, action)
    render_eligibility(elig)

    # ── BLIND SCAN ──
    if blind:
        sigs = scan_for_identity_signals(
            proposal.full_text, proposal.partner_names, proposal.person_names
        )
        rpt = generate_deidentification_report(sigs)
        with st.expander(
            f"🔒 Kimlik Taraması ({len(sigs)} sinyal)", expanded=len(sigs) > 0
        ):
            st.markdown(rpt)

    # ── BUILD CALL CONTEXT (combine all sources) ──
    call_ctx_text = ""

    # From auto-matching
    auto_ctx = st.session_state.get("auto_call_ctx", "")
    if auto_ctx:
        call_ctx_text = auto_ctx

    # From live call dashboard
    if has_call and use_call and not call_ctx_text:
        call_context = st.session_state.get("call_context", {})
        call_ctx_text = call_context.get("evaluation_context", "")

    # From manual input
    if manual_ctx:
        call_ctx_text = (
            (call_ctx_text + "\n\n" + manual_ctx) if call_ctx_text else manual_ctx
        )

    # ── EVALUATE ──
    st.markdown("---")
    st.markdown("## 🚀 Değerlendirme")
    n = len(cfg.criteria)
    c_b, c_i = st.columns([1, 2])
    with c_b:
        go = st.button(
            "🔬 Değerlendirmeyi Başlat", type="primary", use_container_width=True
        )
    with c_i:
        ctx_note = " (çağrı bağlamı aktif)" if call_ctx_text else ""
        rag_note = " + RAG" if use_ai_rag else ""
        st.info(
            f"{action.value}: {n} kriter{ctx_note}{rag_note} · ~{n * 30}-{n * 60}s"
        )

    if not go:
        return

    client = get_llm_client()
    kb = HorizonKnowledgeBase()
    ev = Evaluator(client, kb)
    pbar = st.progress(0.0)
    status = st.empty()
    step = [0]
    total = n * 3  # eval + rag + coaching per criterion

    def on_p(msg):
        status.markdown(f"⏳ {msg}")
        step[0] += 1
        pbar.progress(min(step[0] / total, 1.0))

    results = ev.run(proposal, action, call_ctx_text, on_p, use_ai_rag=use_ai_rag)
    pbar.progress(1.0)
    status.markdown("✅ Tamamlandı!")
    time.sleep(0.5)
    status.empty()
    pbar.empty()

    # ── DISPLAY RESULTS ──
    st.markdown("---")
    render_overall(results)
    st.markdown("---")
    st.markdown("## 📝 Kriter Detayları")

    show_coach = mode in ("both", "coaching_only")
    tab_names = [
        c.get("criterion", f"K{i + 1}") for i, c in enumerate(results["criteria"])
    ]
    tabs = st.tabs(tab_names)
    for i, tab in enumerate(tabs):
        with tab:
            cd = results["criteria"][i]
            co = results["coaching"][i] if i < len(results["coaching"]) else {}
            render_criterion(cd, co, show_coach)

    # ── DOWNLOADS ──
    st.markdown("---")
    st.markdown("## 📥 İndir")
    d1, d2, d3 = st.columns(3)
    elig_dicts = [
        {
            "check_name": ch.check_name,
            "status": ch.status.value,
            "message": ch.message,
        }
        for ch in elig.results
    ]

    with d1:
        st.download_button(
            "📊 JSON",
            json.dumps(results, indent=2, ensure_ascii=False),
            f"grantmirror_{fn}.json",
            "application/json",
            use_container_width=True,
        )
    with d2:
        st.download_button(
            "📋 ESR (MD)",
            generate_esr_report(results, elig_dicts),
            f"grantmirror_{fn}_esr.md",
            "text/markdown",
            use_container_width=True,
        )
    with d3:
        st.download_button(
            "🎯 Koçluk (MD)",
            generate_coaching_report(results),
            f"grantmirror_{fn}_coach.md",
            "text/markdown",
            use_container_width=True,
        )

    # ── DEBUG PANEL ──
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
            st.json(
                {
                    "top_match": matches[0].get("call_id", "?"),
                    "match_score": matches[0].get("ai_match_score", 0),
                    "action_type": matches[0].get("suggested_action_type", "?"),
                }
            )
        else:
            st.write("Eşleşme yok")

        st.markdown("### Çağrı Bağlamı")
        if call_ctx_text:
            st.text_area(
                "Context gönderilen",
                call_ctx_text[:1000],
                height=150,
                disabled=True,
            )
        else:
            st.write("Bağlam yok")

        st.markdown("### Bölüm Tespiti")
        for sec_type, sec_data in proposal.sections.items():
            st.write(
                f"- **{sec_type.value}**: {sec_data.word_count} kelime, "
                f"sayfa {sec_data.page_start}-{sec_data.page_end}"
            )

        st.markdown("### Funding Probability Detay")
        fp = results.get("funding_probability_pct", 0)
        tw = results.get("total_weighted", 0)
        tm = results.get("total_max", 0)
        st.write(
            f"Score ratio: {tw}/{tm} = {tw / tm * 100:.1f}%" if tm > 0 else "N/A"
        )
        st.write(f"Funding probability: {fp}%")
        st.progress(fp / 100)

        st.markdown("### RAG Ayarları")
        st.write(f"AI RAG aktif: {use_ai_rag}")
        st.write(f"AI eşleştirme kullanıldı: {use_ai_match}")

        st.markdown("### Ham Sonuçlar (JSON)")
        st.json(results)


if __name__ == "__main__":
    main()
