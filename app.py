"""
GrantMirror-AI: Horizon Europe Proposal Pre-Screening & ESR Simulator
"""
import streamlit as st
import json
import time
import os
import re
from style_utils import inject_modern_css, render_modern_header
from call_matcher import rank_calls_with_ai
from typing import Dict, List, Optional
from collections import Counter
from datetime import datetime, timedelta
from openai import OpenAI

def clean_html(text):
    if not text:
        return ""

    text = re.sub(r"<[^>]+>", " ", str(text))
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()

from config import (
    ActionType, ACTION_TYPE_CONFIGS, WEAKNESS_TAXONOMY,
    CriterionConfig, get_action_type_from_string,
)
from document_parser import parse_proposal, ParsedProposal, SectionType
from eligibility_checker import run_eligibility_checks, CheckStatus, EligibilityReport
from knowledge_base import HorizonKnowledgeBase
from deidentifier import scan_for_identity_signals, generate_deidentification_report
from report_generator import (
    generate_esr_report,
    generate_coaching_report,
    markdown_to_pdf_bytes,
)
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
from news_fetcher import (
    get_news_with_fallback,
    get_news_sources_status,
    _news_cache,
)

# ═══════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════
st.set_page_config(
    page_title="GrantMirror-AI",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html,body,[class*="css"]{font-family:'Inter',-apple-system,sans-serif!important}
.stApp{background:#f8fafc}
section[data-testid="stSidebar"]{background:linear-gradient(180deg,#1e1b4b,#312e81,#3730a3)!important}
section[data-testid="stSidebar"] *{color:#e0e7ff!important}
section[data-testid="stSidebar"] .stMarkdown h2{color:#fff!important;font-weight:700!important}
section[data-testid="stSidebar"] hr{border-color:rgba(165,180,252,.2)!important}
section[data-testid="stSidebar"] .stExpander{background:rgba(255,255,255,.06)!important;border:1px solid rgba(255,255,255,.1)!important;border-radius:10px!important}
div[data-testid="stMetricValue"]{font-weight:700!important;font-size:1.4rem!important}
div[data-testid="stMetricLabel"]{font-weight:500!important;text-transform:uppercase!important;font-size:.75rem!important;letter-spacing:.03em!important}
div[data-testid="stVerticalBlockBorderWrapper"]{border-radius:12px!important}
.stButton>button{border-radius:10px!important;font-weight:600!important;transition:all .2s!important}
.stButton>button[kind="primary"]{background:linear-gradient(135deg,#6366f1,#4f46e5)!important;border:none!important;color:#fff!important;box-shadow:0 2px 8px rgba(99,102,241,.3)!important}
.stButton>button[kind="primary"]:hover{box-shadow:0 4px 16px rgba(99,102,241,.4)!important;transform:translateY(-1px)!important}
.stExpander{background:#fff!important;border:1px solid #e2e8f0!important;border-radius:12px!important;box-shadow:0 1px 3px rgba(0,0,0,.04)!important}
.stTabs [data-baseweb="tab-list"]{gap:.5rem;background:#fff;padding:.3rem;border-radius:10px;border:1px solid #e2e8f0}
.stTabs [aria-selected="true"]{background:#6366f1!important;color:#fff!important;border-radius:8px!important}
[data-testid="stFileUploader"]{border:2px dashed #e2e8f0!important;border-radius:16px!important;padding:2rem!important;background:#fff!important}
[data-testid="stFileUploader"]:hover{border-color:#818cf8!important;background:#f5f3ff!important}
.stDownloadButton>button{background:#fff!important;border:1px solid #e2e8f0!important;border-radius:10px!important;font-weight:600!important}
.stDownloadButton>button:hover{border-color:#6366f1!important;background:#f5f3ff!important}
.stProgress>div>div{background:linear-gradient(90deg,#6366f1,#06b6d4)!important;border-radius:10px!important}
.stAlert{border-radius:10px!important}
div[data-testid="stContainer"]{border-radius:12px!important}
</style>""", unsafe_allow_html=True)

if "call_cache" not in st.session_state:
    st.session_state.call_cache = CallCache(ttl_minutes=30)

MODEL_NAME = "openai/gpt-4o-mini"


# ═══════════════════════════════════════════════════════════
# LLM
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
                    "esr_comment": "Teknik hata.",
                    "confidence_low": 0, "confidence_high": 0,
                    "consensus_risk": "high", "weakness_categories": [],
                    "sub_signal_assessments": [], "alternative_reading": "",
                })


def llm_call_wrapper(client):
    def _call(s, u):
        return call_llm(client, s, u, temp=0.3, max_tok=3000, js=True)
    return _call


# ═══════════════════════════════════════════════════════════
# PROMPTS
# ═══════════════════════════════════════════════════════════
SYS_ESR = (
    "You are an experienced Horizon Europe evaluator (10+ years). "
    "RULES: 1.Evaluate 'as is' 2.Every criticism MUST point to specific content "
    "3.Score MUST match comment balance 4.Do NOT penalize same weakness twice "
    "5.Scale 0-5 half-points 6.Third person 7.Missing info=weakness 8.Concise like real ESR. "
    "KNOWLEDGE: Check OBJECTIVES-KPIs-METHODOLOGY-OUTCOMES chain. "
    "Six weakness families: LACK_OF_DETAIL, LACK_OF_QUANTIFICATION, "
    "UNCLEAR_TARGET_GROUPS, RESOURCE_IMBALANCE, INTERNAL_INCOHERENCE, "
    "WEAK_RISK_MITIGATION. Gray zone 3.0 plus-minus 0.5 needs alternative_reading."
)

SYS_COACH = (
    "Expert Horizon Europe consultant. Identify weaknesses, explain WHY they "
    "reduce score, give CONCRETE ACTIONABLE fixes ranked by score impact."
)


def build_eval_prompt(crit, sec_text, cross_ctx, kb_ctx, action_type, call_ctx=""):
    qs = "\n".join(f"  - {q}" for q in crit.official_questions)
    checks = "\n".join(f"  - {c}" for c in crit.practical_checklist)
    sigs = ", ".join(crit.sub_signals)
    p = (
        f"## EVALUATE: {crit.name} ({action_type})\n\n"
        f"QUESTIONS:\n{qs}\n\nSIGNALS:\n{checks}\n\n"
        f"SUB-SIGNALS: {sigs}\n\n"
        f"SCORING: 0-5 half-points. Threshold: {crit.threshold}/{crit.max_score}\n"
    )
    if call_ctx:
        p += f"\nCALL CONTEXT:\n{call_ctx}\n"
    p += (
        f"\nKNOWLEDGE:\n{kb_ctx}\n\n"
        f'PROPOSAL SECTION:\n"""\n{sec_text[:15000]}\n"""\n\n'
        f'CROSS-REF:\n"""\n{cross_ctx[:5000]}\n"""\n\n'
        f'RESPOND JSON: {{"criterion":"{crit.name}","score":<0-5>,'
        f'"confidence_low":<f>,"confidence_high":<f>,'
        f'"consensus_risk":"<low|medium|high>",'
        f'"strengths":["..."],"weaknesses":["..."],'
        f'"weakness_categories":["..."],'
        f'"sub_signal_assessments":[{{"signal":"...","rating":"<strong|adequate|weak|missing>",'
        f'"evidence":"...","comment":"..."}}],'
        f'"esr_comment":"<2-3 paragraphs>",'
        f'"topic_alignment":"...","alternative_reading":"..."}}'
    )
    return p


def build_coach_prompt(name, score, weaknesses, cats, sec_text, checklist):
    return (
        f"## COACH: {name} (score: {score}/5)\n\n"
        f"WEAKNESSES: {json.dumps(weaknesses)}\n"
        f"CATEGORIES: {json.dumps(cats)}\n"
        f'TEXT:\n"""\n{sec_text[:8000]}\n"""\n'
        f"CHECKLIST: {json.dumps(checklist[:8])}\n\n"
        f"Provide 3-7 improvements. JSON: "
        f'{{"improvements":[{{"priority":1,"title":"...","problem":"...",'
        f'"impact":"...","solution":"...","expected_score_gain":"+0.5"}}],'
        f'"summary":"..."}}'
    )


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════
def _calc_funding_probability(total, mx, thr, all_met):
    if not all_met or total < thr:
        return "very_low"
    r = total / mx if mx > 0 else 0
    if r >= 0.9:
        return "high"
    if r >= 0.8:
        return "medium"
    if r >= 0.7:
        return "low"
    return "very_low"


def _calc_funding_pct(total, mx, thr, all_met):
    if not all_met or total < thr or mx <= 0:
        return 5
    r = total / mx
    if r >= 0.95:
        base = 85
    elif r >= 0.9:
        base = 70
    elif r >= 0.85:
        base = 50
    elif r >= 0.8:
        base = 30
    elif r >= 0.75:
        base = 15
    elif r >= 0.67:
        base = 10
    else:
        base = 5
    if total - thr < 1.0:
        base = int(base * 0.7)
    return min(base, 95)


def _check_double_penalization(criteria):
    warnings = []
    ws = [
        (c.get("criterion", "?"), set(w.lower().split()))
        for c in criteria
        for w in c.get("weaknesses", [])
    ]
    for i, (c1, w1) in enumerate(ws):
        for j, (c2, w2) in enumerate(ws):
            if i >= j or c1 == c2:
                continue
            if len(w1 & w2) / max(len(w1 | w2), 1) > 0.5:
                warnings.append(
                    f"Benzer zayıflık {c1} ve {c2} — çift cezalandırma riski"
                )
                break
    return warnings


# ═══════════════════════════════════════════════════════════
# EVALUATOR
# ═══════════════════════════════════════════════════════════
class Evaluator:
    def __init__(self, client, kb):
        self.client = client
        self.kb = kb
        self.llm_fn = llm_call_wrapper(client)

    def _sec(self, p, c):
        m = {
            "Excellence": [
                SectionType.EXCELLENCE, SectionType.OPEN_SCIENCE,
                SectionType.GENDER_DIMENSION,
            ],
            "Impact": [
                SectionType.IMPACT, SectionType.DISSEMINATION,
                SectionType.EXPLOITATION,
            ],
            "Implementation": [
                SectionType.IMPLEMENTATION, SectionType.WORK_PACKAGES,
                SectionType.RISK_TABLE,
            ],
        }
        texts = [
            p.sections[s].content
            for s in m.get(c, [])
            if s in p.sections
        ]
        if texts:
            return "\n\n".join(texts)
        t, n = p.full_text, len(p.full_text)
        if c == "Excellence":
            return t[:n // 3]
        if c == "Impact":
            return t[n // 3:2 * n // 3]
        return t[2 * n // 3:]

    def _cross(self, p):
        return "\n".join(
            f"[{s.value}]: {d.content[:400]}"
            for s, d in p.sections.items()
            if d.word_count > 50
        )

    def _rag(self, criterion, at, sec, ai):
        if ai:
            try:
                return ai_enhanced_retrieval(criterion, at, sec, self.llm_fn)
            except Exception:
                pass
        return rag_get_context(criterion, at, sec[:500])

    def run(self, proposal, action_type, call_ctx="", on_progress=None, use_ai_rag=True):
        cfg = ACTION_TYPE_CONFIGS[action_type]
        results = {"action_type": action_type.value, "criteria": [], "coaching": []}
        tw, am = 0.0, True

        for i, cc in enumerate(cfg.criteria):
            if on_progress:
                on_progress(f"📝 {i + 1}/{len(cfg.criteria)}: {cc.name}...")
            sec = self._sec(proposal, cc.name)
            cross = self._cross(proposal)

            if on_progress:
                on_progress(f"🧠 {cc.name} bilgi tabanı...")
            kb = self._rag(cc.name, action_type.value, sec, use_ai_rag)

            raw = call_llm(
                self.client, SYS_ESR,
                build_eval_prompt(cc, sec, cross, kb, action_type.value, call_ctx),
            )
            try:
                r = json.loads(raw)
            except json.JSONDecodeError:
                r = {
                    "criterion": cc.name, "score": 0,
                    "confidence_low": 0, "confidence_high": 0,
                    "consensus_risk": "high", "strengths": [],
                    "weaknesses": ["JSON parse hatası"],
                    "weakness_categories": [], "sub_signal_assessments": [],
                    "esr_comment": "Parse hatası.", "alternative_reading": "",
                    "topic_alignment": "",
                }
            s = max(0.0, min(5.0, round(float(r.get("score", 0)) * 2) / 2))
            r.update({
                "score": s,
                "confidence_low": max(0.0, float(r.get("confidence_low", s - 0.5))),
                "confidence_high": min(5.0, float(r.get("confidence_high", s + 0.5))),
                "weight": cc.weight,
                "threshold": cc.threshold,
                "max_score": cc.max_score,
                "threshold_met": s >= cc.threshold,
                "weighted_score": s * cc.weight,
            })
            tw += r["weighted_score"]
            if not r["threshold_met"]:
                am = False
            results["criteria"].append(r)

            if on_progress:
                on_progress(f"💡 {cc.name} koçluk...")
            raw2 = call_llm(
                self.client, SYS_COACH,
                build_coach_prompt(
                    cc.name, s, r.get("weaknesses", []),
                    r.get("weakness_categories", []),
                    sec, cc.practical_checklist,
                ),
                temp=0.4,
            )
            try:
                co = json.loads(raw2)
            except json.JSONDecodeError:
                co = {"improvements": [], "summary": "Koçluk üretilemedi."}
            co["criterion"] = cc.name
            results["coaching"].append(co)

        results.update({
            "total_weighted": round(tw, 1),
            "total_max": cfg.total_max,
            "total_threshold": cfg.total_threshold,
            "total_threshold_met": am and tw >= cfg.total_threshold,
            "all_criteria_met": am,
            "funding_probability": _calc_funding_probability(
                tw, cfg.total_max, cfg.total_threshold, am,
            ),
            "funding_probability_pct": _calc_funding_pct(
                tw, cfg.total_max, cfg.total_threshold, am,
            ),
        })
        cats = [
            c2
            for c in results["criteria"]
            for c2 in c.get("weakness_categories", [])
        ]
        cc2 = Counter(cats)
        results["cross_cutting_issues"] = [
            f"'{WEAKNESS_TAXONOMY[k]['label']}' — {v} kriterde: "
            f"{WEAKNESS_TAXONOMY[k]['description']}"
            for k, v in cc2.items()
            if v > 1 and k in WEAKNESS_TAXONOMY
        ]
        results["double_penalization_warnings"] = _check_double_penalization(
            results["criteria"]
        )
        return results


# ═══════════════════════════════════════════════════════════
# UI COMPONENTS
# ═══════════════════════════════════════════════════════════
def render_polished_header():
    st.markdown(
        """
        <div class="gm-top-hero">
            <h1>🔬 GrantMirror-AI</h1>
            <p>Horizon Europe proposal pre-screening, call matching and ESR-style evaluator simulation.</p>
            <div class="gm-hero-badges">
                <span class="gm-hero-badge">📡 Live Calls</span>
                <span class="gm-hero-badge">🎯 AI Matching</span>
                <span class="gm-hero-badge">🧠 RAG Engine</span>
                <span class="gm-hero-badge">📋 ESR Simulation</span>
                <span class="gm-hero-badge">📊 Funding Probability</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_call_card(call, index):
    """Bir çağrı kartı — tüm alanlar HTML temizlenmiş."""
    status = call.get("status", "?")
    icons = {"Open": "🟢", "Forthcoming": "🟡", "Closed": "🔴"}
    si = icons.get(status, "⚪")

    at = ", ".join(call.get("action_types", ["?"]))
    dl = call.get("deadline", "N/A")
    if dl and len(dl) > 10:
        dl = dl[:10]

    dest = clean_html(call.get("destination", ""))
    ds = dest.split("–")[-1].strip() if "–" in dest else dest
    budget = clean_html(
        call.get("budget_per_project", call.get("budget_total", ""))
    )
    source = call.get("source", "")
    link = call.get("link", "")

    # Başlık temizle
    title = clean_html(call.get("title", "N/A"))
    call_id = clean_html(call.get("call_id", "N/A"))

    days_text = ""
    if dl and dl != "N/A":
        try:
            dt = datetime.strptime(dl[:10], "%Y-%m-%d")
            days = (dt - datetime.now()).days
            if days < 0:
                days_text = f"⏰ {abs(days)} gün önce kapandı"
            elif days == 0:
                days_text = "🔥 Bugün son gün!"
            elif days <= 7:
                days_text = f"⏰ {days} gün kaldı!"
            elif days <= 30:
                days_text = f"📅 {days} gün kaldı"
            elif days <= 90:
                days_text = f"📅 {days} gün"
            else:
                days_text = f"📅 ~{days // 30} ay"
        except Exception:
            pass

    with st.container(border=True):
        tag_line = f"{si} **{status}**"
        if ds:
            tag_line += f" · 🏛️ {ds}"
        if source:
            tag_line += f" · 📡 {source}"
        if days_text:
            tag_line += f" · {days_text}"
        st.markdown(tag_line)

        st.markdown(f"**{title[:150]}**")

        info = f"🆔 `{call_id}` · 🏷️ {at} · 📅 {dl}"
        if budget:
            info += f" · 💰 {budget}"
        if link:
            info += f" · [🔗 Detay]({link})"
        st.caption(info)

        return st.button("Seç →", key=f"call_{index}", use_container_width=True)


def render_score_bar(score, mx, thr, label):
    pct = score / mx if mx > 0 else 0
    met = score >= thr
    color_icon = "✅" if met else "❌"
    st.markdown(f"**{label}** — {score}/{mx} {color_icon}")
    st.progress(min(pct, 1.0))
    st.caption(f"Eşik: {thr} | {'Geçti' if met else 'Geçemedi'}")


def render_eligibility(elig):
    icons = {"pass": "✅", "fail": "❌", "warning": "⚠️", "info": "ℹ️", "unable": "❓"}
    with st.expander(
        f"{'✅' if elig.is_eligible else '❌'} Uygunluk Kontrolü",
        expanded=not elig.is_eligible,
    ):
        for ch in elig.results:
            st.markdown(
                f"{icons.get(ch.status.value, '')} "
                f"**{ch.check_name}**: {ch.message}"
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
            f'{crit.get("confidence_low", "?")} – {crit.get("confidence_high", "?")}',
        )
    with c2:
        risk = crit.get("consensus_risk", "?")
        ri = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(risk, "⚪")
        st.metric("Uzlaşma Riski", f"{ri} {risk}")
    with c3:
        st.metric("Ağırlıklı Puan", f'{crit.get("weighted_score", 0):.1f}')

    st.markdown("#### 📋 ESR Yorumu")
    st.info(crit.get("esr_comment", "N/A"))

    ta = crit.get("topic_alignment", "")
    if ta:
        with st.expander("🎯 Çağrı Uyumu"):
            st.markdown(ta)

    col_s, col_w = st.columns(2)
    with col_s:
        st.markdown("##### ✅ Güçlü Yönler")
        for si in crit.get("strengths", []):
            st.markdown(f"- {si}")
        if not crit.get("strengths"):
            st.caption("Tespit edilemedi.")
    with col_w:
        st.markdown("##### ❌ Zayıf Yönler")
        for wi in crit.get("weaknesses", []):
            st.markdown(f"- {wi}")
        if not crit.get("weaknesses"):
            st.caption("Tespit edilemedi.")

    cats = crit.get("weakness_categories", [])
    if cats:
        labels = [WEAKNESS_TAXONOMY.get(c, {}).get("label", c) for c in cats]
        st.markdown(
            "**🏷️ Kategoriler:** " + " · ".join(f"`{l}`" for l in labels)
        )

    subs = crit.get("sub_signal_assessments", [])
    if subs:
        with st.expander("📊 Alt Sinyaller"):
            for sa in subs:
                r = sa.get("rating", "?")
                ic = {
                    "strong": "🟢", "adequate": "🟡",
                    "weak": "🟠", "missing": "🔴",
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
        st.divider()
        st.markdown("#### 🎯 Koçluk Önerileri")
        for imp in coach.get("improvements", []):
            with st.expander(
                f"🔧 P{imp.get('priority', '?')}: "
                f"{imp.get('title', '?')} ({imp.get('expected_score_gain', '?')})"
            ):
                st.markdown(f"**Problem:** {imp.get('problem', '')}")
                st.markdown(f"**Etki:** {imp.get('impact', '')}")
                st.markdown(f"**Çözüm:** {imp.get('solution', '')}")
        if coach.get("summary"):
            st.markdown(f"**📝 Özet:** {coach['summary']}")


def render_overall(results):
    st.markdown("## 📊 Genel Değerlendirme Özeti")
    tw = results["total_weighted"]
    tm = results["total_max"]
    thr = results["total_threshold"]
    met = results["total_threshold_met"]
    fp = results.get("funding_probability", "very_low")
    fp_pct = results.get("funding_probability_pct", 0)
    pl = {
        "high": "🟢 Yüksek", "medium": "🟡 Orta",
        "low": "🟠 Düşük", "very_low": "🔴 Çok Düşük",
    }
    ok = sum(1 for c in results["criteria"] if c.get("threshold_met"))
    tc = len(results["criteria"])
    si = len(results.get("cross_cutting_issues", []))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        dv = tw - thr
        st.metric(
            "Toplam Puan", f"{tw}/{tm}",
            delta=f"{dv:+.1f}",
            delta_color="normal" if met else "inverse",
        )
    with c2:
        st.metric("Fonlanma", pl.get(fp, "?"), delta=f"~%{fp_pct}")
    with c3:
        st.metric(
            "Kriter Eşik", f"{ok}/{tc}",
            delta="✅" if ok == tc else "⚠️",
            delta_color="normal" if ok == tc else "inverse",
        )
    with c4:
        st.metric(
            "Sistemik Sorun", si,
            delta="✅" if si == 0 else "⚠️",
            delta_color="normal" if si == 0 else "inverse",
        )

    st.divider()
    cols = st.columns(len(results["criteria"]))
    for i, cr in enumerate(results["criteria"]):
        with cols[i]:
            render_score_bar(
                cr["score"], cr["max_score"], cr["threshold"],
                cr.get("criterion", f"K{i + 1}"),
            )

    cross = results.get("cross_cutting_issues", [])
    if cross:
        st.markdown("### ⚠️ Sistemik Sorunlar")
        for iss in cross:
            st.warning(iss)
    dp = results.get("double_penalization_warnings", [])
    if dp:
        st.markdown("### 🔄 Çift Cezalandırma")
        for w in dp:
            st.warning(w)


# ═══════════════════════════════════════════════════════════
# CALL DASHBOARD
# ═══════════════════════════════════════════════════════════
def render_call_dashboard():
    st.markdown("## 📡 Canlı Çağrı Paneli")

    col1, col2, col3, col4 = st.columns([3, 2, 2, 1])

    with col1:
        search = st.text_input("🔍 Arama", placeholder="Anahtar kelime...")

    with col2:
        status_filter = st.selectbox(
        "📋 Durum",
        ["", "Open", "Forthcoming"],
        index=0,
        format_func=lambda x: {
            "": "Open + Forthcoming",
            "Open": "Açık",
            "Forthcoming": "Yaklaşan",
        }.get(x, x),
    )
    
    with col3:
        dest_options = [""] + sorted(
            set(
                clean_html(c.get("destination", ""))
                for c in HORIZON_CALLS_DB
                if c.get("destination")
            )
        )

        dest_filter = st.selectbox(
            "🏛️ Küme",
            dest_options,
            format_func=lambda x: (
                x.split("–")[-1].strip() if "–" in x else (x if x else "Tümü")
            ),
        )

    with col4:
        st.markdown("")
        refresh_btn = st.button("🔄", help="Yenile", use_container_width=True)

    ac1, ac2 = st.columns([1, 3])

    with ac1:
        auto_refresh = st.checkbox("⏰ Otomatik güncelle", value=False)

    with ac2:
        refresh_interval = 300

        if auto_refresh:
            refresh_interval = st.select_slider(
                "Aralık",
                options=[30, 60, 120, 300],
                value=60,
                format_func=lambda x: f"{x}s" if x < 60 else f"{x // 60}dk",
            )

    sc1, sc2, sc3, sc4 = st.columns(4)

    with sc1:
        use_ec_api = st.checkbox("🌐 EC API", value=True)

    with sc2:
        use_euresearch = st.checkbox("🇨🇭 Euresearch", value=True)

    with sc3:
        use_ufukavrupa = st.checkbox("🇹🇷 UfukAvrupa", value=True)

    with sc4:
        max_results = (
        st.number_input(
            "Maks",
            min_value=10,
            max_value=500,
            value=500,
            step=50,
        )
        if use_ec_api
        else len(HORIZON_CALLS_DB)
    )

    if auto_refresh:
        last_refresh = st.session_state.get("last_refresh_time", 0)

        if time.time() - last_refresh > refresh_interval:
            st.session_state["last_refresh_time"] = time.time()
            st.session_state.call_cache.clear()
            st.rerun()

    if refresh_btn:
        st.session_state.call_cache.clear()
        st.rerun()

    cache_key = (
        f"v5_dash_{search}_{status_filter}_{dest_filter}_"
        f"{use_ec_api}_{use_euresearch}_{use_ufukavrupa}_{max_results}"
    )

    cached = st.session_state.call_cache.get(cache_key)

    if cached:
        calls, src_stats = cached

    else:
        with st.spinner("📡 Çağrılar çekiliyor..."):
            calls, total = fetch_horizon_calls(
                search_text=search,
                status=status_filter,
                programme="HORIZON",
                page_size=max_results,
            )

            src_stats = {
                "success": True,
                "total_calls": total,
                "ec_api": len(calls),
                "euresearch": 0,
                "ufukavrupa": 0,
                "local_db": len(HORIZON_CALLS_DB),
            }

            if status_filter:
                calls = [
                    c for c in calls
                    if c.get("status", "").lower() == status_filter.lower()
                ]

            if dest_filter:
                calls = [
                    c for c in calls
                    if dest_filter.lower()
                    in clean_html(c.get("destination", "")).lower()
                ]

            if search:
                keyword = search.lower()

                calls = [
                    c for c in calls
                    if keyword in clean_html(c.get("title", "")).lower()
                    or keyword in clean_html(c.get("call_id", "")).lower()
                    or keyword in " ".join(c.get("keywords", [])).lower()
                    or keyword in clean_html(c.get("scope", "")).lower()
                ]

            st.session_state.call_cache.set(cache_key, (calls, src_stats))
            st.session_state["last_fetch_stats"] = src_stats

    # ─── EC API Debug Bilgisi ───
    ec_debug = src_stats.get("ec_debug", {})

    if ec_debug:
        with st.expander("🔧 EC API Debug"):
            success = ec_debug.get("success", False)
            total = ec_debug.get("total_api", 0)
            pages = ec_debug.get("pages_fetched", 0)
            winner = ec_debug.get("winning_strategy", "—")

            st.markdown(
                f"{'✅' if success else '❌'} **Başarı:** {success} | "
                f"**Toplam:** {total} | **Sayfa:** {pages} | "
                f"**Kazanan:** `{winner}`"
            )

            for att in ec_debug.get("attempts", []):
                name = att.get("strategy", "?")
                count = att.get("count", 0)
                http_status = (
                    att.get("status")
                    or att.get("post_status")
                    or att.get("get_status")
                    or "?"
                )
                total_r = att.get("total_results", "?")
                p1 = att.get("page1_count", "?")
                error = att.get("error", "")

                icon = "✅" if count > 0 else "❌"

                st.markdown(
                    f"{icon} **{name}** — "
                    f"HTTP `{http_status}` — "
                    f"Sonuç: {total_r} — "
                    f"Sayfa1: {p1} — "
                    f"Çekilen: {count}"
                )

                if att.get("url"):
                    st.caption(att["url"][:300])

                if error:
                    st.error(error[:200])

                if att.get("get_fallback"):
                    st.caption(
                        f"↪ GET fallback: HTTP {att.get('get_status', '?')}"
                    )

    if not calls:
        st.info("Çağrı bulunamadı. Filtreleri değiştirin.")
        return None

    total = len(calls)
    open_count = sum(1 for c in calls if c.get("status") == "Open")
    forthcoming_count = sum(1 for c in calls if c.get("status") == "Forthcoming")
    closed_count = sum(1 for c in calls if c.get("status") == "Closed")

    s1, s2, s3, s4, s5 = st.columns(5)

    with s1:
        st.metric("Toplam", total)

    with s2:
        st.metric("🟢 Açık", open_count)

    with s3:
        st.metric("🟡 Yaklaşan", forthcoming_count)

    with s4:
        st.metric("🔴 Kapanmış", closed_count)

    with s5:
        st.metric(
            "Kaynaklar",
            f"EC:{src_stats.get('ec_api', 0)} "
            f"EUR:{src_stats.get('euresearch', 0)} "
            f"UA:{src_stats.get('ufukavrupa', 0)} "
            f"DB:{src_stats.get('local_db', 0)}",
        )

    try:
        excel_bytes = calls_to_excel_bytes(calls)

        st.download_button(
            label=f"📥 Excel İndir ({len(calls)} çağrı)",
            data=excel_bytes,
            file_name="grantmirror_horizon_calls.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    except Exception as e:
        st.warning(f"Excel export hazırlanamadı: {e}")

    # ─── AI CALL MATCHING ───
    st.markdown("### 🤖 AI ile En Uygun Çağrıları Bul")

    proposal_for_ranking = st.text_area(
        "Proje özeti gir",
        placeholder="Projenin amacını, teknolojisini, hedefini yaz...",
        height=120,
    )

    if st.button("🎯 En Uygun Çağrıları Bul", use_container_width=True):
        if not proposal_for_ranking.strip():
            st.warning("Önce proje özeti gir")
        else:
            with st.spinner("AI analiz yapıyor..."):
                ranked_calls = rank_calls_with_ai(
                    proposal_text=proposal_for_ranking,
                    calls=calls,
                    llm_call=llm_call_wrapper(get_llm_client()),
                    top_k=10,
                )

            st.session_state["ranked_calls"] = ranked_calls

    ranked_calls = st.session_state.get("ranked_calls", [])

    if ranked_calls:
        st.success(f"{len(ranked_calls)} en uygun çağrı bulundu")

        for i, call in enumerate(ranked_calls, 1):
            st.markdown(
                f"""
                <div style="
                    border:1px solid #d0d5dd;
                    border-radius:16px;
                    padding:16px;
                    margin-bottom:12px;
                    background:#ffffff;
                ">
                    <div style="font-size:0.85rem;color:#667085;">
                        #{i} · 🎯 {call.get('ai_match_score', 0)}/100 · {call.get('ai_fit_level', '')}
                    </div>
                    <div style="font-size:1.1rem;font-weight:700;color:#101828;">
                        {call.get('call_id', '')}
                    </div>
                    <div>{call.get('title', '')}</div>
                    <div style="font-size:0.85rem;color:#667085;margin-top:6px;">
                        📅 {call.get('deadline', '')} · 🛰️ {call.get('source', '')}
                    </div>
                    <div style="margin-top:8px;">
                        <b>Neden uygun:</b> {call.get('ai_match_reason', '')}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        
        
    selected_call = None

    # Pagination
    items_per_page = 6
    total_pages = max(1, (len(calls) + items_per_page - 1) // items_per_page)

    page = st.number_input(
        "Sayfa",
        min_value=1,
        max_value=total_pages,
        value=1,
        step=1,
    )
    start = (page - 1) * items_per_page
    end = start + items_per_page

    paged_calls = calls[start:end]

    st.caption(f"Sayfa {page}/{total_pages} · Toplam {len(calls)} çağrı")

    for i, call in enumerate(paged_calls, start=start):
        status = call.get("status", "Unknown")

        status_icon = {
            "Open": "🟢",
            "Forthcoming": "🟡",
            "Closed": "🔴",
        }.get(status, "⚪")

        call_id = call.get("call_id", "N/A")
        title = call.get("title", "N/A")
        deadline = call.get("deadline", "N/A")
        action_types = ", ".join(call.get("action_types", [])) or "N/A"
        source = call.get("source", "N/A")
        url = call.get("url", "")

        with st.container():
            st.markdown(
                f"""
                <div style="
                    border:1px solid #e5e7eb;
                    border-radius:16px;
                    padding:18px;
                    margin-bottom:14px;
                    background:#ffffff;
                    box-shadow:0 4px 12px rgba(0,0,0,0.04);
                ">
                    <div style="font-size:0.9rem;color:#667085;">
                        {status_icon} <b>{status}</b> · 🏛️ {call_id} · 🛰️ {source}
                    </div>
                    <div style="font-size:1.15rem;font-weight:700;margin-top:8px;color:#101828;">
                        {title}
                    </div>
                    <div style="font-size:0.9rem;color:#667085;margin-top:8px;">
                        🏷️ {action_types} · 📅 {deadline}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            c1, c2 = st.columns([5, 1])

            with c1:
                if url:
                    st.markdown(f"[🔗 EU Portal Detay]({url})")

            with c2:
                if st.button("Seç →", key=f"select_call_{i}", use_container_width=True):
                    selected_call = call

    return selected_call

def render_call_detail(call_data):
    st.markdown("### 📋 Seçilen Çağrı Detayı")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Çağrı", clean_html(call_data.get("call_id", "N/A")))
    with c2:
        dl = call_data.get("deadline", "N/A")
        st.metric("Son Tarih", dl[:10] if dl and dl != "N/A" else "N/A")
    with c3:
        at = detect_action_type_from_call(call_data)
        st.metric("Aksiyon", at)

    st.markdown(f"**Başlık**: {clean_html(call_data.get('title', 'N/A'))}")
    src = call_data.get("source", "")
    if src:
        st.caption(f"📡 Kaynak: {src}")
    link = call_data.get("link", "")
    if link:
        st.markdown(f"[🔗 Orijinal sayfa]({link})")

    # Scope/description göster
    scope = clean_html(call_data.get("scope", ""))
    if scope:
        with st.expander("📝 Kapsam"):
            st.markdown(scope[:2000])

    topics = call_data.get("topics", [])
    topic_details = None
    if topics:
        tid = topics[0].get("topic_id", "")
        if tid:
            cached_topic = st.session_state.call_cache.get(f"topic_{tid}")
            if cached_topic:
                topic_details = cached_topic
            else:
                with st.spinner(f"📡 Topic: {tid}..."):
                    topic_details = fetch_topic_details(tid)
                    if topic_details:
                        st.session_state.call_cache.set(
                            f"topic_{tid}", topic_details,
                        )
    if topic_details and topic_details.get("description"):
        with st.expander("📝 Topic Açıklaması"):
            st.markdown(clean_html(topic_details["description"][:3000]))

    ctx = build_call_specific_criteria(call_data, topic_details)
    st.success(f"✅ Aksiyon: **{at}** | Bağlam hazır")
    return ctx


# ═══════════════════════════════════════════════════════════
# NEWS PAGE — CANLI RSS + EC API + UFUKAVRUPA + EURESEARCH
# ═══════════════════════════════════════════════════════════
def render_news_page():
    """Horizon Europe canlı haber akışı."""
    st.markdown("## 📰 Horizon Europe Haber Akışı")
    st.caption("Güncel gelişmeler · RSS + EC API + UfukAvrupa + Euresearch · Otomatik güncelleme")

    # ─── Üst kontrol çubuğu ───
    ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([1, 1, 1, 1])
    with ctrl1:
        horizon_only = st.checkbox("🎯 Sadece Horizon Europe", value=True)
    with ctrl2:
        include_calls = st.checkbox("📡 Yeni çağrıları dahil et", value=True)
    with ctrl3:
        include_ua = st.checkbox("🇹🇷 UfukAvrupa", value=True)
    with ctrl4:
        if st.button("🔄 Yenile", use_container_width=True, key="news_refresh"):
            _news_cache.clear()
            st.rerun()

    # ─── Haberleri çek ───
    with st.spinner("📡 Haberler yükleniyor..."):
        news_items = get_news_with_fallback(
            max_per_source=15,
            horizon_only=horizon_only,
            include_recent_calls=include_calls,
            include_ufukavrupa=include_ua,
            include_euresearch=True,
        )

    # ─── Kaynak durumu ───
    with st.expander("📡 Kaynak Durumu"):
        src_statuses = get_news_sources_status()
        n_src_cols = min(len(src_statuses), 4) if src_statuses else 1
        src_cols = st.columns(n_src_cols)
        for i, src in enumerate(src_statuses):
            with src_cols[i % n_src_cols]:
                count_str = (
                    f"{src['count']} haber"
                    if src['count'] >= 0
                    else "scraper"
                )
                st.markdown(
                    f"{src['status']} **{src['icon']} {src['name']}** "
                    f"({count_str}) · {src.get('type', '')}"
                )
        st.caption(
            f"Son güncelleme: {datetime.now().strftime('%H:%M:%S')} | "
            f"Cache: 15 dk"
        )

    st.divider()

    # ─── Filtreler ───
    fc1, fc2, fc3 = st.columns([3, 2, 2])
    with fc1:
        news_search = st.text_input(
            "🔍 Haber ara",
            placeholder="Anahtar kelime...",
            key="news_search",
        )
    with fc2:
        all_tags = sorted(set(n["tag"] for n in news_items))
        tag_options = [""] + all_tags
        tag_filter = st.selectbox(
            "🏷️ Kategori", tag_options,
            format_func=lambda x: x if x else "Tümü",
            key="news_tag_filter",
        )
    with fc3:
        all_sources = sorted(set(n.get("source", "") for n in news_items))
        source_options = [""] + all_sources
        source_filter = st.selectbox(
            "📡 Kaynak", source_options,
            format_func=lambda x: x if x else "Tümü",
            key="news_source_filter",
        )

    # Tarih filtresi
    date_range = st.select_slider(
        "📅 Zaman aralığı",
        options=["1 hafta", "2 hafta", "1 ay", "3 ay", "6 ay", "Tümü"],
        value="3 ay",
        key="news_date_range",
    )
    days_map = {
        "1 hafta": 7, "2 hafta": 14, "1 ay": 30,
        "3 ay": 90, "6 ay": 180, "Tümü": 9999,
    }
    max_days = days_map.get(date_range, 30)

    # ─── Filtreleme ───
    filtered = news_items

    if max_days < 9999:
        cutoff = (datetime.now() - timedelta(days=max_days)).strftime("%Y-%m-%d")
        filtered = [n for n in filtered if n.get("date", "") >= cutoff]

    if news_search:
        kw = news_search.lower()
        filtered = [
            n for n in filtered
            if kw in n["title"].lower() or kw in n["summary"].lower()
        ]

    if tag_filter:
        filtered = [n for n in filtered if n["tag"] == tag_filter]

    if source_filter:
        filtered = [n for n in filtered if n.get("source") == source_filter]

    # ─── İstatistikler ───
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.metric("📰 Toplam", len(news_items))
    with s2:
        st.metric("🔍 Filtreli", len(filtered))
    with s3:
        tag_counts = {}
        for n in filtered:
            tag_counts[n["tag"]] = tag_counts.get(n["tag"], 0) + 1
        top_tag = max(tag_counts, key=tag_counts.get) if tag_counts else "—"
        st.metric("🏷️ En çok", top_tag)
    with s4:
        src_count = len(set(n.get("source", "") for n in filtered))
        st.metric("📡 Kaynak", src_count)

    st.divider()

    # ─── Haber kartları ───
    if not filtered:
        st.info("🔍 Filtrelere uygun haber bulunamadı. Zaman aralığını genişletin veya filtreleri kaldırın.")
        return

    # Sayfalama
    items_per_page = 10
    total_pages = max(1, (len(filtered) + items_per_page - 1) // items_per_page)

    if len(filtered) > items_per_page:
        _, pg_col, _ = st.columns([1, 2, 1])
        with pg_col:
            current_page = st.number_input(
                f"Sayfa (1-{total_pages})",
                min_value=1, max_value=total_pages, value=1, step=1,
                key="news_page",
            )
        start_idx = (current_page - 1) * items_per_page
        page_items = filtered[start_idx:start_idx + items_per_page]
        st.caption(
            f"Gösterilen: {start_idx + 1}-"
            f"{min(start_idx + items_per_page, len(filtered))} / "
            f"{len(filtered)}"
        )
    else:
        page_items = filtered
        current_page = 1

    tag_icons = {
        "🆕 Yeni Çağrı": "📢",
        "📋 Program Güncellemesi": "📋",
        "🎓 MSCA": "🎓",
        "💡 EIC": "💡",
        "⭐ ERC": "⭐",
        "🌍 Missions": "🌍",
        "📊 İstatistik": "📊",
        "🤝 Widening": "🤝",
        "📝 Rehber": "📝",
        "🔬 Cluster 4": "🔬",
        "🌿 Cluster 5": "🌿",
        "🏥 Cluster 1": "🏥",
        "🎭 Cluster 2": "🎭",
        "🛡️ Cluster 3": "🛡️",
        "🌾 Cluster 6": "🌾",
        "🔬 Araştırma": "🔬",
        "🔬 Araştırma Sonuçları": "🔬",
        "🏗️ Altyapı": "🏗️",
        "⚠️ Hata": "⚠️",
    }

    for n in page_items:
        with st.container(border=True):
            tc1, tc2 = st.columns([4, 1])
            with tc1:
                source_badge = (
                    f"{n.get('source_icon', '📰')} {n.get('source', '')}"
                )
                st.markdown(
                    f"**{n['tag']}** · 📅 {n['date']} · {source_badge}"
                )

                st.markdown(f"### {n['title']}")

                if n.get("summary"):
                    st.markdown(n["summary"])

                # Gün hesabı
                try:
                    news_date = datetime.strptime(n["date"], "%Y-%m-%d")
                    age = (datetime.now() - news_date).days
                    if age == 0:
                        age_text = "🔥 Bugün"
                    elif age == 1:
                        age_text = "📅 Dün"
                    elif age <= 7:
                        age_text = f"📅 {age} gün önce"
                    else:
                        age_text = f"📅 {age} gün önce"
                    st.caption(age_text)
                except Exception:
                    pass

                if n.get("link"):
                    st.markdown(f"[🔗 Devamını oku →]({n['link']})")

            with tc2:
                big_icon = tag_icons.get(n["tag"], "📰")
                st.markdown(
                    f"<div style='text-align:center;font-size:3rem;"
                    f"padding-top:1rem'>{big_icon}</div>",
                    unsafe_allow_html=True,
                )

    if len(filtered) > items_per_page:
        st.caption(
            f"Sayfa {current_page}/{total_pages} · "
            f"Toplam {len(filtered)} haber"
        )

    st.divider()
    st.caption(
        "📡 Kaynaklar: EC R&I RSS, CORDIS, ERC, EIC, MSCA, "
        "UfukAvrupa, Euresearch, EC F&T API"
    )
    st.caption(
        "🔄 Otomatik güncelleme: 15 dakikada bir | "
        "Yenile butonu ile anında güncelleyebilirsiniz"
    )
    st.caption(
        "⚠️ Kaynaklar erişilemezse son başarılı veri veya "
        "statik haberler gösterilir"
    )


# ═══════════════════════════════════════════════════════════
# PAGES
# ═══════════════════════════════════════════════════════════
def render_feature_dashboard():
    st.markdown("## 🎯 GrantMirror-AI Ne Yapar?")
    st.caption(
        "Horizon Europe tekliflerini çağrı uyumu, hakem değerlendirmesi ve fonlanma olasılığı açısından analiz eder."
    )

    features = [
        ("📡", "Canlı Çağrı", "EC API üzerinden güncel Horizon çağrılarını çeker."),
        ("🎯", "AI Eşleştirme", "Proje fikrini en uygun çağrılarla eşleştirir."),
        ("🧠", "RAG Motor", "Kriter ve rehber bilgisini birlikte yorumlar."),
        ("📋", "ESR Simülasyon", "Hakem formatına yakın değerlendirme üretir."),
        ("🛠️", "Koçluk", "Zayıf noktalar için düzeltme önerileri verir."),
        ("📊", "Güven Aralığı", "Puan ve fonlanma olasılığı tahmini üretir."),
        ("🔒", "Kimlik Taraması", "Kör değerlendirme risklerini kontrol eder."),
        ("📰", "Canlı Haberler", "EU ve UfukAvrupa haberlerini izler."),
    ]

    rows = [features[:4], features[4:]]

    for row in rows:
        cols = st.columns(4)
        for col, (icon, title, desc) in zip(cols, row):
            with col:
                with st.container(border=True):
                    st.markdown(f"### {icon} {title}")
                    st.write(desc)

    st.divider()

    c1, c2 = st.columns(2)

    with c1:
        if st.button("📡 Canlı Çağrılara Git", use_container_width=True):
            st.session_state["nav"] = "📡 Canlı Çağrılar"
            st.rerun()

    with c2:
        if st.button("📰 Haberleri Aç", use_container_width=True):
            st.session_state["nav"] = "📰 Haberler"
            st.rerun()
    
def render_evaluation_page():
    # ─────────────────────────────
    # SIDEBAR SETTINGS
    # ─────────────────────────────
    with st.sidebar:
        st.markdown("## ⚙️ Ayarlar")

        has_call = "selected_call" in st.session_state

        if has_call:
            cd = st.session_state["selected_call"]
            dat = detect_action_type_from_call(cd)
            st.success(f"📡 {clean_html(cd.get('call_id', '?'))}")

            action = get_action_type_from_string(dat)
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

        aa = st.session_state.get("auto_action_type")

        if aa and not has_call:
            action = aa
            st.info(f"🎯 AI: {action.value}")

        cfg = ACTION_TYPE_CONFIGS[action]

        with st.expander("ℹ️ Kriterler"):
            for cr in cfg.criteria:
                st.markdown(
                    f"**{cr.name}** "
                    f"(w:{cr.weight}, t:{cr.threshold}/{cr.max_score})"
                )

        st.divider()

        mode = st.radio(
            "Çıktı",
            ["both", "esr_only", "coaching_only"],
            format_func=lambda x: {
                "both": "📋+🎯 Tam",
                "esr_only": "📋 ESR",
                "coaching_only": "🎯 Koçluk",
            }[x],
        )

        st.divider()

        manual_ctx = st.text_area(
            "Ek Bağlam",
            height=80,
            placeholder="Work Programme scope...",
        )

        blind = st.checkbox(
            "🔒 Kimlik taraması",
            value=cfg.blind_evaluation,
        )

        st.divider()

        st.markdown("### 🧠 AI Ayarları")

        use_ai_rag = st.checkbox(
            "RAG zenginleştirme",
            value=True,
        )

        st.caption("⚠️ Resmî EC değerlendirmesinin yerini almaz.")

    # ─────────────────────────────
    # MAIN UPLOAD AREA
    # ─────────────────────────────
    st.markdown(
"""<div class="gm-onboarding">
<div class="gm-onboarding-left">
<div class="gm-eyebrow">AI Proposal Pre-Screening</div>

<h2>📤 Teklifinizi yükleyin, hakem gibi analiz edelim</h2>

<p>
Horizon Europe Part B dokümanınızı yükleyin. Sistem;
çağrı uyumu, ESR değerlendirmesi ve fonlanma analizi üretir.
</p>

<div class="gm-onboarding-badges">
<span>PDF</span>
<span>DOCX</span>
<span>ESR Simulation</span>
<span>AI Matching</span>
</div>
</div>

<div class="gm-onboarding-steps">
<div class="gm-step"><b>1</b><span>Proposal yükle</span></div>
<div class="gm-step"><b>2</b><span>AI analiz etsin</span></div>
<div class="gm-step"><b>3</b><span>Raporu al</span></div>
</div>
</div>""",
unsafe_allow_html=True,
)
    uploaded = st.file_uploader(
        "📄 Dosyanızı buraya bırakın",
        type=["pdf", "docx", "doc"],
    )

    if not uploaded:
        render_feature_dashboard()
        return

    fb = uploaded.read()
    fn = uploaded.name

    # ─────────────────────────────
    # DOCUMENT PARSING
    # ─────────────────────────────
    with st.spinner("📄 Belge okunuyor..."):
        try:
            proposal = parse_proposal(fb, fn)
        except Exception as e:
            st.error(f"❌ Belge hatası: {e}")
            return

    st.success(f"✅ Belge yüklendi: {fn}")

    with st.expander("📄 Belge Özeti", expanded=True):
        d1, d2, d3, d4 = st.columns(4)

        with d1:
            st.metric("Sayfa", proposal.total_pages)

        with d2:
            st.metric("Kelime", f"{proposal.total_words:,}")

        with d3:
            st.metric("Bölüm", len(proposal.sections))

        with d4:
            st.metric("TRL", len(proposal.trl_mentions))

        for warning in proposal.warnings:
            st.warning(warning)
            
st.divider()
st.markdown("## 🚀 Değerlendirme")

go = st.button(
    "🔬 Analizi Başlat",
    type="primary",
    use_container_width=True,
)

if not go:
    st.info("Belge hazır. Analizi başlatmak için butona basın.")
    return


    # AI CALL MATCHING
    st.markdown("### 🎯 Otomatik Çağrı Eşleştirme")
    mc1, mc2 = st.columns([1, 1])
    with mc1:
        use_ai_match = st.checkbox("🧠 AI eşleştir", value=True)
    with mc2:
        match_btn = st.button("🔍 Eşleştir", use_container_width=True)

    if match_btn or "matched_calls" not in st.session_state:
        with st.spinner("🔍 Eşleştiriliyor..."):
            if use_ai_match:
                try:
                    cl = get_llm_client()
                    matches = ai_match_calls(
                        proposal.full_text, llm_call_wrapper(cl), top_k=5,
                    )
                except Exception:
                    matches = [
                        {
                            **c,
                            "ai_match_score": round(s * 100, 1),
                            "ai_match_reason": "Keyword",
                            "suggested_action_type": c["action_types"][0],
                        }
                        for c, s in keyword_match_calls(
                            proposal.full_text, top_k=5,
                        )
                    ]
            else:
                matches = [
                    {
                        **c,
                        "ai_match_score": round(s * 100, 1),
                        "ai_match_reason": "Keyword",
                        "suggested_action_type": c["action_types"][0],
                    }
                    for c, s in keyword_match_calls(
                        proposal.full_text, top_k=5,
                    )
                ]
            st.session_state["matched_calls"] = matches

    matches = st.session_state.get("matched_calls", [])
    if matches:
        for i, m in enumerate(matches):
            sc = m.get("ai_match_score", 0)
            si2 = "🟢" if sc >= 70 else "🟡" if sc >= 40 else "🔴"
            with st.expander(
                f"{si2} {clean_html(m['call_id'])} — {sc}/100 | "
                f"{', '.join(m.get('action_types', []))}",
                expanded=(i == 0),
            ):
                st.markdown(
                    f"**{clean_html(m.get('destination', m.get('call_id', '')))}**"
                )
                st.markdown(f"📝 {m.get('ai_match_reason', '')}")
                mc1b, mc2b = st.columns(2)
                with mc1b:
                    st.markdown(
                        f"🏷️ **Aksiyon:** {m.get('suggested_action_type', '?')}"
                    )
                    st.markdown(
                        f"📅 **Son Tarih:** {m.get('deadline', 'N/A')}"
                    )
                with mc2b:
                    st.markdown(
                        f"💰 **Bütçe:** {m.get('budget_per_project', 'N/A')}"
                    )
                    st.markdown(
                        f"📊 **Durum:** {m.get('status', 'N/A')}"
                    )
                with st.expander("📋 Detay"):
                    st.markdown(
                        f"**Çıktılar:** {clean_html(m.get('expected_outcomes', 'N/A'))}"
                    )
                    st.markdown(
                        f"**Kapsam:** {clean_html(m.get('scope', 'N/A'))}"
                    )
                if st.button("✅ Kullan", key=f"use_match_{i}"):
                    st.session_state["auto_call_ctx"] = build_call_eval_context(m)
                    sug = m.get("suggested_action_type", "")
                    if sug:
                        try:
                            st.session_state["auto_action_type"] = (
                                get_action_type_from_string(sug)
                            )
                        except Exception:
                            pass
                    st.success(f"✅ {clean_html(m['call_id'])} eklendi!")
                    st.rerun()
    else:
        st.info("Eşleşme bulunamadı.")

    # ELIGIBILITY
    with st.spinner("✅ Uygunluk kontrolleri..."):
        elig = run_eligibility_checks(proposal, action)
    render_eligibility(elig)

    # BLIND
    if blind:
        sigs = scan_for_identity_signals(
            proposal.full_text, proposal.partner_names, proposal.person_names,
        )
        rpt = generate_deidentification_report(sigs)
        with st.expander(
            f"🔒 Kimlik ({len(sigs)} sinyal)", expanded=len(sigs) > 0,
        ):
            st.markdown(rpt)

    # CALL CONTEXT
    call_ctx_text = ""
    ac = st.session_state.get("auto_call_ctx", "")
    if ac:
        call_ctx_text = ac
    if has_call and use_call and not call_ctx_text:
        cc2 = st.session_state.get("call_context", {})
        call_ctx_text = cc2.get("evaluation_context", "")
    if manual_ctx:
        call_ctx_text = (
            (call_ctx_text + "\n\n" + manual_ctx) if call_ctx_text else manual_ctx
        )

    # EVALUATE
    st.divider()
    st.markdown("## 🚀 Değerlendirme")
    n = len(cfg.criteria)
    cb, ci = st.columns([1, 2])
    with cb:
        go = st.button("🔬 Başlat", type="primary", use_container_width=True)
    with ci:
        cn = " + 📡 Çağrı" if call_ctx_text else ""
        rn = " + 🧠 RAG" if use_ai_rag else ""
        st.info(f"**{action.value}**: {n} kriter{cn}{rn} · ~{n * 30}-{n * 60}s")

    if not go:
        return

    client = get_llm_client()
    kb = HorizonKnowledgeBase()
    ev = Evaluator(client, kb)
    pbar = st.progress(0.0)
    stat_el = st.empty()
    step = [0]
    ts = n * 3

    def on_p(msg):
        stat_el.markdown(f"⏳ {msg}")
        step[0] += 1
        pbar.progress(min(step[0] / ts, 1.0))

    results = ev.run(
        proposal, action, call_ctx_text, on_p, use_ai_rag=use_ai_rag,
    )
    pbar.progress(1.0)
    stat_el.markdown("✅ Tamamlandı!")
    time.sleep(0.5)
    stat_el.empty()
    pbar.empty()

    st.divider()
    render_overall(results)

    st.markdown("## 📝 Kriter Detayları")
    show_coach = mode in ("both", "coaching_only")
    tab_names = [
        c.get("criterion", f"K{i + 1}")
        for i, c in enumerate(results["criteria"])
    ]
    tabs = st.tabs(tab_names)
    for i, tab in enumerate(tabs):
        with tab:
            render_criterion(
                results["criteria"][i],
                results["coaching"][i]
                if i < len(results["coaching"])
                else {},
                show_coach,
            )

    elig = run_eligibility_checks(proposal, action)

    st.markdown("## 📥 Raporları İndir")

    d1, d2, d3, d4 = st.columns(4)

    ed = [
        {
            "check_name": ch.check_name,
            "status": ch.status.value,
            "message": ch.message,
        }
        for ch in elig.results
    ]

    esr_md = generate_esr_report(results, ed)
    coach_md = generate_coaching_report(results)
    esr_pdf = markdown_to_pdf_bytes(esr_md)

    with d1:
        st.download_button(
            label="📊 JSON",
            data=json.dumps(results, indent=2, ensure_ascii=False),
            file_name=f"gm_{fn}.json",
            mime="application/json",
            use_container_width=True,
        )

    with d2:
        st.download_button(
            label="📄 ESR PDF",
            data=esr_pdf,
            file_name=f"gm_{fn}_esr.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

    with d3:
        st.download_button(
            label="📋 ESR MD",
            data=esr_md,
            file_name=f"gm_{fn}_esr.md",
            mime="text/markdown",
            use_container_width=True,
        )

    with d4:
        st.download_button(
            label="🎯 Koçluk",
            data=coach_md,
            file_name=f"gm_{fn}_coach.md",
            mime="text/markdown",
            use_container_width=True,
        )

    with st.expander("🔧 DEBUG"):
        dc1, dc2, dc3 = st.columns(3)

        with dc1:
            st.metric("Kelime", f"{proposal.total_words:,}")
            st.metric("Sayfa", proposal.total_pages)

        with dc2:
            st.metric("Bölüm", len(proposal.sections))
            st.metric("TRL", len(proposal.trl_mentions))

        with dc3:
            st.metric("KPI", len(proposal.kpi_mentions))
            st.metric("Partner", len(proposal.partner_names))

        if matches:
            st.json(
                {
                    "top": clean_html(matches[0].get("call_id", "?")),
                    "score": matches[0].get("ai_match_score", 0),
                }
            )

        if call_ctx_text:
            st.text_area(
                "Bağlam",
                call_ctx_text[:1000],
                height=100,
                disabled=True,
            )

        fp2 = results.get("funding_probability_pct", 0)
        tw2 = results.get("total_weighted", 0)
        tm2 = results.get("total_max", 0)

        st.write(
            f"Ratio: {tw2}/{tm2} = {tw2 / tm2 * 100:.1f}%"
            if tm2 > 0
            else "N/A"
        )

        st.progress(fp2 / 100)

        st.write(
            f"RAG: {use_ai_rag} | Match: {use_ai_match} | "
            f"Model: {MODEL_NAME} | DB: {len(HORIZON_CALLS_DB)}"
        )

        st.json(results)
        
def render_calls_page():
    st.title("📡 Canlı Çağrılar")

    sel = render_call_dashboard()

    if sel:
        st.divider()
        ctx = render_call_detail(sel)
        st.session_state["selected_call"] = sel
        st.session_state["call_context"] = ctx

        st.info("💡 Seçilen çağrı Değerlendirme sayfasına aktarıldı.")

        if st.button("🔬 Değerlendirmeye Git", type="primary", use_container_width=True):
            st.session_state["nav"] = "🔬 Değerlendirme"
            st.rerun()


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
def main():
    render_polished_header()
    inject_modern_css()

    pages = ["🔬 Değerlendirme", "📡 Canlı Çağrılar", "📰 Haberler"]
    default_page = st.session_state.get("nav", "🔬 Değerlendirme")

    page = st.sidebar.radio(
        "📌",
        pages,
        index=pages.index(default_page) if default_page in pages else 0,
        label_visibility="collapsed",
    )

    st.session_state["nav"] = page

    with st.sidebar:
        st.divider()

        cached_stats = st.session_state.get("last_fetch_stats", None)

        if cached_stats:
            t = cached_stats.get("total", 0)
            ec = cached_stats.get("ec_api", 0)
            eur = cached_stats.get("euresearch", 0)
            ua = cached_stats.get("ufukavrupa", 0)
            db = cached_stats.get("local_db", 0)

            st.caption(
                f"📊 Toplam: {t} | EC:{ec} EUR:{eur} UA:{ua} DB:{db}"
            )
        else:
            stats = get_call_stats()
            st.caption(
                f"📊 DB: {stats['total']} | "
                f"🟢 {stats['open']} | 🟡 {stats['forthcoming']}"
            )

    if page == "📡 Canlı Çağrılar":
        try:
            render_calls_page()
        except Exception as e:
            st.error("Canlı Çağrılar sayfasında hata var.")
            st.exception(e)

    elif page == "📰 Haberler":
        render_news_page()

    else:
        render_evaluation_page()


if __name__ == "__main__":
    main()
