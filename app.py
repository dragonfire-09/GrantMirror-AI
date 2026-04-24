"""
GrantMirror-AI: Horizon Europe Proposal Pre-Screening & ESR Simulator
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
    fetch_all_calls,
)
from call_db import (
    keyword_match_calls, ai_match_calls, build_call_eval_context,
    HORIZON_CALLS_DB, get_call_stats,
)
from rag_engine import get_criterion_context as rag_get_context, ai_enhanced_retrieval

# ═══════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════
st.set_page_config(page_title="GrantMirror-AI", page_icon="🔬", layout="wide", initial_sidebar_state="expanded")

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
    kw = dict(model=MODEL_NAME, messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}], temperature=temp, max_tokens=max_tok)
    if js:
        kw["response_format"] = {"type": "json_object"}
    for attempt in range(3):
        try:
            return client.chat.completions.create(**kw).choices[0].message.content
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                return json.dumps({"error": str(e), "score": 0, "strengths": [], "weaknesses": [f"LLM hatası: {e}"], "esr_comment": "Teknik hata.", "confidence_low": 0, "confidence_high": 0, "consensus_risk": "high", "weakness_categories": [], "sub_signal_assessments": [], "alternative_reading": ""})


def llm_call_wrapper(client):
    def _call(s, u):
        return call_llm(client, s, u, temp=0.3, max_tok=3000, js=True)
    return _call


# ═══════════════════════════════════════════════════════════
# PROMPTS
# ═══════════════════════════════════════════════════════════
SYS_ESR = """You are an experienced Horizon Europe evaluator (10+ years). RULES: 1.Evaluate 'as is' 2.Every criticism MUST point to specific content 3.Score MUST match comment balance 4.Do NOT penalize same weakness twice 5.Scale 0-5 half-points 6.Third person 7.Missing info=weakness 8.Concise like real ESR. KNOWLEDGE: Check OBJECTIVES-KPIs-METHODOLOGY-OUTCOMES chain. Six weakness families: LACK_OF_DETAIL, LACK_OF_QUANTIFICATION, UNCLEAR_TARGET_GROUPS, RESOURCE_IMBALANCE, INTERNAL_INCOHERENCE, WEAK_RISK_MITIGATION. Gray zone 3.0 plus-minus 0.5 needs alternative_reading."""

SYS_COACH = """Expert Horizon Europe consultant. Identify weaknesses, explain WHY they reduce score, give CONCRETE ACTIONABLE fixes ranked by score impact."""


def build_eval_prompt(crit, sec_text, cross_ctx, kb_ctx, action_type, call_ctx=""):
    qs = "\n".join(f"  - {q}" for q in crit.official_questions)
    checks = "\n".join(f"  - {c}" for c in crit.practical_checklist)
    sigs = ", ".join(crit.sub_signals)
    p = f"## EVALUATE: {crit.name} ({action_type})\n\nQUESTIONS:\n{qs}\n\nSIGNALS:\n{checks}\n\nSUB-SIGNALS: {sigs}\n\nSCORING: 0-5 half-points. Threshold: {crit.threshold}/{crit.max_score}\n"
    if call_ctx:
        p += f"\nCALL CONTEXT:\n{call_ctx}\n"
    p += f"\nKNOWLEDGE:\n{kb_ctx}\n\nPROPOSAL SECTION:\n\"\"\"\n{sec_text[:15000]}\n\"\"\"\n\nCROSS-REF:\n\"\"\"\n{cross_ctx[:5000]}\n\"\"\"\n\n"
    p += 'RESPOND JSON: {"criterion":"' + crit.name + '","score":<0-5>,"confidence_low":<f>,"confidence_high":<f>,"consensus_risk":"<low|medium|high>","strengths":["..."],"weaknesses":["..."],"weakness_categories":["..."],"sub_signal_assessments":[{"signal":"...","rating":"<strong|adequate|weak|missing>","evidence":"...","comment":"..."}],"esr_comment":"<2-3 paragraphs>","topic_alignment":"...","alternative_reading":"..."}'
    return p


def build_coach_prompt(name, score, weaknesses, cats, sec_text, checklist):
    return f'## COACH: {name} (score: {score}/5)\n\nWEAKNESSES: {json.dumps(weaknesses)}\nCATEGORIES: {json.dumps(cats)}\nTEXT:\n"""\n{sec_text[:8000]}\n"""\nCHECKLIST: {json.dumps(checklist[:8])}\n\nProvide 3-7 improvements. JSON: {{"improvements":[{{"priority":1,"title":"...","problem":"...","impact":"...","solution":"...","expected_score_gain":"+0.5"}}],"summary":"..."}}'


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════
def _calc_funding_probability(total, mx, thr, all_met):
    if not all_met or total < thr:
        return "very_low"
    r = total / mx if mx > 0 else 0
    return "high" if r >= .9 else "medium" if r >= .8 else "low" if r >= .7 else "very_low"


def _calc_funding_pct(total, mx, thr, all_met):
    if not all_met or total < thr or mx <= 0:
        return 5
    r = total / mx
    base = 85 if r >= .95 else 70 if r >= .9 else 50 if r >= .85 else 30 if r >= .8 else 15 if r >= .75 else 10 if r >= .67 else 5
    if total - thr < 1.0:
        base = int(base * .7)
    return min(base, 95)


def _check_double_penalization(criteria):
    warnings = []
    ws = [(c.get("criterion", "?"), set(w.lower().split())) for c in criteria for w in c.get("weaknesses", [])]
    for i, (c1, w1) in enumerate(ws):
        for j, (c2, w2) in enumerate(ws):
            if i >= j or c1 == c2:
                continue
            if len(w1 & w2) / max(len(w1 | w2), 1) > .5:
                warnings.append(f"Benzer zayıflık {c1} ve {c2} — çift cezalandırma riski")
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
        m = {"Excellence": [SectionType.EXCELLENCE, SectionType.OPEN_SCIENCE, SectionType.GENDER_DIMENSION], "Impact": [SectionType.IMPACT, SectionType.DISSEMINATION, SectionType.EXPLOITATION], "Implementation": [SectionType.IMPLEMENTATION, SectionType.WORK_PACKAGES, SectionType.RISK_TABLE]}
        texts = [p.sections[s].content for s in m.get(c, []) if s in p.sections]
        if texts:
            return "\n\n".join(texts)
        t, n = p.full_text, len(p.full_text)
        return t[:n // 3] if c == "Excellence" else t[n // 3:2 * n // 3] if c == "Impact" else t[2 * n // 3:]

    def _cross(self, p):
        return "\n".join(f"[{s.value}]: {d.content[:400]}" for s, d in p.sections.items() if d.word_count > 50)

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
            raw = call_llm(self.client, SYS_ESR, build_eval_prompt(cc, sec, cross, kb, action_type.value, call_ctx))
            try:
                r = json.loads(raw)
            except json.JSONDecodeError:
                r = {"criterion": cc.name, "score": 0, "confidence_low": 0, "confidence_high": 0, "consensus_risk": "high", "strengths": [], "weaknesses": ["JSON parse hatası"], "weakness_categories": [], "sub_signal_assessments": [], "esr_comment": "Parse hatası.", "alternative_reading": "", "topic_alignment": ""}
            s = max(0.0, min(5.0, round(float(r.get("score", 0)) * 2) / 2))
            r.update({"score": s, "confidence_low": max(0.0, float(r.get("confidence_low", s - .5))), "confidence_high": min(5.0, float(r.get("confidence_high", s + .5))), "weight": cc.weight, "threshold": cc.threshold, "max_score": cc.max_score, "threshold_met": s >= cc.threshold, "weighted_score": s * cc.weight})
            tw += r["weighted_score"]
            if not r["threshold_met"]:
                am = False
            results["criteria"].append(r)

            if on_progress:
                on_progress(f"💡 {cc.name} koçluk...")
            raw2 = call_llm(self.client, SYS_COACH, build_coach_prompt(cc.name, s, r.get("weaknesses", []), r.get("weakness_categories", []), sec, cc.practical_checklist), temp=0.4)
            try:
                co = json.loads(raw2)
            except json.JSONDecodeError:
                co = {"improvements": [], "summary": "Koçluk üretilemedi."}
            co["criterion"] = cc.name
            results["coaching"].append(co)

        results.update({"total_weighted": round(tw, 1), "total_max": cfg.total_max, "total_threshold": cfg.total_threshold, "total_threshold_met": am and tw >= cfg.total_threshold, "all_criteria_met": am, "funding_probability": _calc_funding_probability(tw, cfg.total_max, cfg.total_threshold, am), "funding_probability_pct": _calc_funding_pct(tw, cfg.total_max, cfg.total_threshold, am)})
        cats = [c2 for c in results["criteria"] for c2 in c.get("weakness_categories", [])]
        cc2 = Counter(cats)
        results["cross_cutting_issues"] = [f"'{WEAKNESS_TAXONOMY[k]['label']}' — {v} kriterde: {WEAKNESS_TAXONOMY[k]['description']}" for k, v in cc2.items() if v > 1 and k in WEAKNESS_TAXONOMY]
        results["double_penalization_warnings"] = _check_double_penalization(results["criteria"])
        return results


# ═══════════════════════════════════════════════════════════
# UI COMPONENTS — PURE STREAMLIT (NO raw HTML)
# ═══════════════════════════════════════════════════════════
def render_header():
    st.markdown("# 🔬 GrantMirror-AI")
    st.caption("Horizon Europe Proposal Pre-Screening & ESR Simulator")
    st.caption("📡 Canlı Çağrı · 🎯 AI Eşleştirme · 🧠 RAG · 📋 ESR · 🎯 Koçluk · 📊 Güven Aralığı")
    st.divider()


def render_call_card(call, index):
    """Bir çağrı kartı — tamamen native Streamlit."""
    status = call.get("status", "?")
    icons = {"Open": "🟢", "Forthcoming": "🟡", "Closed": "🔴"}
    si = icons.get(status, "⚪")

    at = ", ".join(call.get("action_types", ["?"]))
    dl = call.get("deadline", "N/A")
    if dl and len(dl) > 10:
        dl = dl[:10]

    dest = call.get("destination", "")
    ds = dest.split("–")[-1].strip() if "–" in dest else dest
    budget = call.get("budget_per_project", call.get("budget_total", ""))
    source = call.get("source", "")
    link = call.get("link", "")

    # Kalan gün
    days_text = ""
    if dl and dl != "N/A":
        try:
            dt = datetime.strptime(dl[:10], "%Y-%m-%d")
            days = (dt - datetime.now()).days
            if days == 0:
                days_text = "🔥 Bugün son gün!"
            elif 0 < days <= 7:
                days_text = f"⏰ {days} gün kaldı!"
            elif days <= 30:
                days_text = f"📅 {days} gün kaldı"
            elif days > 30:
                days_text = f"📅 {days} gün"
        except Exception:
            pass

    with st.container(border=True):
        # Üst satır: durum + küme + kaynak + gün
        tag_line = f"{si} **{status}**"
        if ds:
            tag_line += f" · 🏛️ {ds}"
        if source:
            tag_line += f" · 📡 {source}"
        if days_text:
            tag_line += f" · {days_text}"
        st.markdown(tag_line)

        # Başlık
        st.markdown(f"**{call.get('title', 'N/A')[:150]}**")

        # Bilgi satırı
        info = f"🆔 `{call.get('call_id', 'N/A')}` · 🏷️ {at} · 📅 {dl}"
        if budget:
            info += f" · 💰 {budget}"
        if link:
            info += f" · [🔗 Detay]({link})"
        st.caption(info)

        return st.button("Seç →", key=f"call_{index}", use_container_width=True)


def render_score_bar(score, mx, thr, label):
    """Skor çubuğu — native progress bar."""
    pct = score / mx if mx > 0 else 0
    met = score >= thr
    color_icon = "✅" if met else "❌"
    st.markdown(f"**{label}** — {score}/{mx} {color_icon}")
    st.progress(min(pct, 1.0))
    st.caption(f"Eşik: {thr} | {'Geçti' if met else 'Geçemedi'}")


def render_eligibility(elig):
    icons = {"pass": "✅", "fail": "❌", "warning": "⚠️", "info": "ℹ️", "unable": "❓"}
    with st.expander(f"{'✅' if elig.is_eligible else '❌'} Uygunluk Kontrolü", expanded=not elig.is_eligible):
        for ch in elig.results:
            st.markdown(f"{icons.get(ch.status.value, '')} **{ch.check_name}**: {ch.message}")
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
        st.metric("Güven Aralığı", f'{crit.get("confidence_low", "?")} – {crit.get("confidence_high", "?")}')
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
        st.markdown("**🏷️ Kategoriler:** " + " · ".join(f"`{l}`" for l in labels))

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
        st.divider()
        st.markdown("#### 🎯 Koçluk Önerileri")
        for imp in coach.get("improvements", []):
            with st.expander(f"🔧 P{imp.get('priority', '?')}: {imp.get('title', '?')} ({imp.get('expected_score_gain', '?')})"):
                st.markdown(f"**Problem:** {imp.get('problem', '')}")
                st.markdown(f"**Etki:** {imp.get('impact', '')}")
                st.markdown(f"**Çözüm:** {imp.get('solution', '')}")
        if coach.get("summary"):
            st.markdown(f"**📝 Özet:** {coach['summary']}")


def render_overall(results):
    st.markdown("## 📊 Genel Değerlendirme Özeti")
    tw, tm = results["total_weighted"], results["total_max"]
    thr, met = results["total_threshold"], results["total_threshold_met"]
    fp = results.get("funding_probability", "very_low")
    fp_pct = results.get("funding_probability_pct", 0)
    pl = {"high": "🟢 Yüksek", "medium": "🟡 Orta", "low": "🟠 Düşük", "very_low": "🔴 Çok Düşük"}
    ok = sum(1 for c in results["criteria"] if c.get("threshold_met"))
    tc = len(results["criteria"])
    si = len(results.get("cross_cutting_issues", []))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        dv = tw - thr
        st.metric("Toplam Puan", f"{tw}/{tm}", delta=f"{dv:+.1f}", delta_color="normal" if met else "inverse")
    with c2:
        st.metric("Fonlanma", pl.get(fp, "?"), delta=f"~%{fp_pct}")
    with c3:
        st.metric("Kriter Eşik", f"{ok}/{tc}", delta="✅" if ok == tc else "⚠️", delta_color="normal" if ok == tc else "inverse")
    with c4:
        st.metric("Sistemik Sorun", si, delta="✅" if si == 0 else "⚠️", delta_color="normal" if si == 0 else "inverse")

    st.divider()
    cols = st.columns(len(results["criteria"]))
    for i, cr in enumerate(results["criteria"]):
        with cols[i]:
            render_score_bar(cr["score"], cr["max_score"], cr["threshold"], cr.get("criterion", f"K{i + 1}"))

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
        status_filter = st.selectbox("📋 Durum", ["", "Open", "Forthcoming", "Closed"], format_func=lambda x: x if x else "Tümü")
    with col3:
        dest_options = [""] + sorted(set(c.get("destination", "") for c in HORIZON_CALLS_DB if c.get("destination")))
        dest_filter = st.selectbox("🏛️ Küme", dest_options, format_func=lambda x: x.split("–")[-1].strip() if "–" in x else (x if x else "Tümü"))
    with col4:
        st.markdown("")
        refresh_btn = st.button("🔄", help="Yenile", use_container_width=True)

    ac1, ac2 = st.columns([1, 3])
    with ac1:
        auto_refresh = st.checkbox("⏰ Otomatik güncelle", value=False)
    with ac2:
        refresh_interval = 300
        if auto_refresh:
            refresh_interval = st.select_slider("Aralık", options=[30, 60, 120, 300], value=60, format_func=lambda x: f"{x}s" if x < 60 else f"{x // 60}dk")

    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        use_ec_api = st.checkbox("🌐 EC API", value=True)
    with sc2:
        use_euresearch = st.checkbox("🇨🇭 Euresearch", value=True)
    with sc3:
        max_results = st.number_input("Maks", min_value=10, max_value=500, value=100, step=50) if use_ec_api else len(HORIZON_CALLS_DB)

    if auto_refresh:
        lr = st.session_state.get("last_refresh_time", 0)
        if time.time() - lr > refresh_interval:
            st.session_state["last_refresh_time"] = time.time()
            st.session_state.call_cache.clear()
            st.rerun()

    if refresh_btn:
        st.session_state.call_cache.clear()
        st.rerun()

    cache_key = f"dash_{search}_{status_filter}_{dest_filter}_{use_ec_api}_{use_euresearch}_{max_results}"
    cached = st.session_state.call_cache.get(cache_key)

    if cached:
        calls, src_stats = cached
    else:
        with st.spinner("📡 Çağrılar çekiliyor (EC API + Euresearch + Yerel DB)..."):
            calls, src_stats = fetch_all_calls(search_text=search, status_filter=status_filter, use_ec_api=use_ec_api, use_euresearch=use_euresearch, max_api_results=max_results)
        if status_filter:
            calls = [c for c in calls if c.get("status", "").lower() == status_filter.lower()]
        if dest_filter:
            calls = [c for c in calls if dest_filter.lower() in c.get("destination", "").lower()]
        if search:
            kw = search.lower()
            calls = [c for c in calls if kw in c.get("title", "").lower() or kw in c.get("call_id", "").lower() or kw in " ".join(c.get("keywords", [])).lower() or kw in c.get("scope", "").lower()]
        st.session_state.call_cache.set(cache_key, (calls, src_stats))

    if not calls:
        st.info("Çağrı bulunamadı. Filtreleri değiştirin.")
        return None

    total = len(calls)
    op = sum(1 for c in calls if c.get("status") == "Open")
    fc = sum(1 for c in calls if c.get("status") == "Forthcoming")
    cl = sum(1 for c in calls if c.get("status") == "Closed")

    s1, s2, s3, s4, s5 = st.columns(5)
    with s1:
        st.metric("Toplam", total)
    with s2:
        st.metric("🟢 Açık", op)
    with s3:
        st.metric("🟡 Yaklaşan", fc)
    with s4:
        st.metric("🔴 Kapanmış", cl)
    with s5:
        st.metric("Kaynaklar", f"EC:{src_stats.get('ec_api', 0)} EUR:{src_stats.get('euresearch', 0)} DB:{src_stats.get('local_db', 0)}")

    excel_bytes = calls_to_excel_bytes(calls)
    st.download_button(f"📥 Excel İndir ({total} çağrı)", excel_bytes, "horizon_calls.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

    sort_by = st.selectbox("Sırala", ["deadline", "title", "status"], format_func=lambda x: {"deadline": "📅 Son Tarih", "title": "🔤 Başlık", "status": "📋 Durum"}[x], label_visibility="collapsed")
    if sort_by == "deadline":
        calls = sorted(calls, key=lambda c: c.get("deadline", "9999"))
    elif sort_by == "title":
        calls = sorted(calls, key=lambda c: c.get("title", "").lower())
    else:
        calls = sorted(calls, key=lambda c: {"Open": 0, "Forthcoming": 1, "Closed": 2}.get(c.get("status", ""), 9))

    ipp = 20
    tp = max(1, (total + ipp - 1) // ipp)
    if total > ipp:
        _, pc, _ = st.columns([1, 2, 1])
        with pc:
            cp = st.number_input(f"Sayfa (1-{tp})", 1, tp, 1, 1)
        si_idx = (cp - 1) * ipp
        page_calls = calls[si_idx:si_idx + ipp]
        st.caption(f"Gösterilen: {si_idx + 1}-{min(si_idx + ipp, total)} / {total}")
    else:
        page_calls, cp = calls, 1

    selected_call = None
    for i, call in enumerate(page_calls):
        gi = (cp - 1) * ipp + i
        if render_call_card(call, gi):
            selected_call = call

    if total > ipp:
        st.caption(f"Sayfa {cp}/{tp} · Toplam {total} çağrı")

    return selected_call


def render_call_detail(call_data):
    st.markdown("### 📋 Seçilen Çağrı Detayı")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Çağrı", call_data.get("call_id", "N/A"))
    with c2:
        st.metric("Son Tarih", call_data.get("deadline", "N/A")[:10] if call_data.get("deadline") else "N/A")
    with c3:
        at = detect_action_type_from_call(call_data)
        st.metric("Aksiyon", at)

    st.markdown(f"**Başlık**: {call_data.get('title', 'N/A')}")
    src = call_data.get("source", "")
    if src:
        st.caption(f"📡 Kaynak: {src}")
    link = call_data.get("link", "")
    if link:
        st.markdown(f"[🔗 Orijinal sayfa]({link})")

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
                        st.session_state.call_cache.set(f"topic_{tid}", topic_details)
    if topic_details and topic_details.get("description"):
        with st.expander("📝 Topic Açıklaması"):
            st.markdown(topic_details["description"][:3000])

    ctx = build_call_specific_criteria(call_data, topic_details)
    st.success(f"✅ Aksiyon: **{at}** | Bağlam hazır")
    return ctx


# ═══════════════════════════════════════════════════════════
# PAGES
# ═══════════════════════════════════════════════════════════
def render_calls_page():
    sel = render_call_dashboard()
    if sel:
        st.divider()
        ctx = render_call_detail(sel)
        st.session_state["selected_call"] = sel
        st.session_state["call_context"] = ctx
        c1, c2 = st.columns(2)
        with c1:
            st.info("💡 Değerlendirme için **Değerlendirme** sayfasına geçin.")
        with c2:
            if st.button("🔬 Değerlendirmeye Git", type="primary", use_container_width=True):
                st.rerun()


def render_evaluation_page():
    with st.sidebar:
        st.markdown("## ⚙️ Ayarlar")
        has_call = "selected_call" in st.session_state
        if has_call:
            cd = st.session_state["selected_call"]
            dat = detect_action_type_from_call(cd)
            st.success(f"📡 {cd.get('call_id', '?')}")
            action = get_action_type_from_string(dat)
            use_call = st.checkbox("Çağrı bağlamını kullan", value=True)
        else:
            labels = {ActionType.RIA: "🔬 RIA", ActionType.IA: "🚀 IA", ActionType.CSA: "🤝 CSA", ActionType.MSCA_DN: "🎓 MSCA-DN", ActionType.EIC_PATHFINDER_OPEN: "💡 EIC Pathfinder", ActionType.EIC_ACCELERATOR: "📈 EIC Accelerator", ActionType.ERC_STG: "⭐ ERC StG"}
            action = st.selectbox("Aksiyon Türü", list(labels.keys()), format_func=lambda x: labels[x])
            use_call = False

        aa = st.session_state.get("auto_action_type")
        if aa and not has_call:
            action = aa
            st.info(f"🎯 AI: {action.value}")

        cfg = ACTION_TYPE_CONFIGS[action]
        with st.expander("ℹ️ Kriterler"):
            for cr in cfg.criteria:
                st.markdown(f"**{cr.name}** (w:{cr.weight}, t:{cr.threshold}/{cr.max_score})")

        st.divider()
        mode = st.radio("Çıktı", ["both", "esr_only", "coaching_only"], format_func=lambda x: {"both": "📋+🎯 Tam", "esr_only": "📋 ESR", "coaching_only": "🎯 Koçluk"}[x])
        st.divider()
        manual_ctx = st.text_area("Ek Bağlam", height=80, placeholder="Work Programme scope...")
        blind = st.checkbox("🔒 Kimlik taraması", value=cfg.blind_evaluation)
        st.divider()
        st.markdown("### 🧠 AI Ayarları")
        use_ai_rag = st.checkbox("RAG zenginleştirme", value=True)
        st.caption("⚠️ Resmî EC değerlendirmesinin yerini almaz.")

    # MAIN
    st.markdown("## 📤 Teklif Yükleme")
    uploaded = st.file_uploader("Horizon Europe Part B (PDF / DOCX)", type=["pdf", "docx", "doc"])

    if not uploaded:
        st.markdown("## 🎯 GrantMirror-AI Ne Yapar?")
        fc1, fc2 = st.columns(2)
        with fc1:
            st.markdown("""
- 📡 **Canlı Çağrı** — EC API + Euresearch'den çeker
- 🎯 **AI Eşleştirme** — En uygun çağrılarla eşleştirir
- 🧠 **RAG Motor** — Kriter bazlı AI bilgi sentezi
- 📋 **ESR Simülasyon** — Gerçek hakem formatı
""")
        with fc2:
            st.markdown("""
- 🎯 **Koçluk** — Somut düzeltme önerileri
- 📊 **Güven Aralığı** — Puan + fonlanma olasılığı
- 🔒 **Kimlik Taraması** — Kör değerlendirme kontrolü
- 🏷️ **Taksonomi** — 12 kategori + çift ceza kontrolü
""")
        return

    fb, fn = uploaded.read(), uploaded.name
    with st.spinner("📄 Belge okunuyor..."):
        try:
            proposal = parse_proposal(fb, fn)
        except Exception as e:
            st.error(f"❌ Belge hatası: {e}")
            return

    with st.expander("📄 Belge Özeti", expanded=False):
        d1, d2, d3, d4 = st.columns(4)
        with d1:
            st.metric("Sayfa", proposal.total_pages)
        with d2:
            st.metric("Kelime", f"{proposal.total_words:,}")
        with d3:
            st.metric("Bölüm", len(proposal.sections))
        with d4:
            st.metric("TRL", len(proposal.trl_mentions))
        for s, d in proposal.sections.items():
            st.write(f"- **{s.value}**: {d.word_count} kelime")
        for w in proposal.warnings:
            st.warning(w)

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
                    matches = ai_match_calls(proposal.full_text, llm_call_wrapper(cl), top_k=5)
                except Exception:
                    matches = [{**c, "ai_match_score": round(s * 100, 1), "ai_match_reason": "Keyword", "suggested_action_type": c["action_types"][0]} for c, s in keyword_match_calls(proposal.full_text, top_k=5)]
            else:
                matches = [{**c, "ai_match_score": round(s * 100, 1), "ai_match_reason": "Keyword", "suggested_action_type": c["action_types"][0]} for c, s in keyword_match_calls(proposal.full_text, top_k=5)]
            st.session_state["matched_calls"] = matches

    matches = st.session_state.get("matched_calls", [])
    if matches:
        for i, m in enumerate(matches):
            sc = m.get("ai_match_score", 0)
            si2 = "🟢" if sc >= 70 else "🟡" if sc >= 40 else "🔴"
            with st.expander(f"{si2} {m['call_id']} — {sc}/100 | {', '.join(m.get('action_types', []))}", expanded=(i == 0)):
                st.markdown(f"**{m.get('destination', m.get('call_id', ''))}**")
                st.markdown(f"📝 {m.get('ai_match_reason', '')}")
                mc1b, mc2b = st.columns(2)
                with mc1b:
                    st.markdown(f"🏷️ **Aksiyon:** {m.get('suggested_action_type', '?')}")
                    st.markdown(f"📅 **Son Tarih:** {m.get('deadline', 'N/A')}")
                with mc2b:
                    st.markdown(f"💰 **Bütçe:** {m.get('budget_per_project', 'N/A')}")
                    st.markdown(f"📊 **Durum:** {m.get('status', 'N/A')}")
                with st.expander("📋 Detay"):
                    st.markdown(f"**Çıktılar:** {m.get('expected_outcomes', 'N/A')}")
                    st.markdown(f"**Kapsam:** {m.get('scope', 'N/A')}")
                if st.button("✅ Kullan", key=f"use_match_{i}"):
                    st.session_state["auto_call_ctx"] = build_call_eval_context(m)
                    sug = m.get("suggested_action_type", "")
                    if sug:
                        try:
                            st.session_state["auto_action_type"] = get_action_type_from_string(sug)
                        except Exception:
                            pass
                    st.success(f"✅ {m['call_id']} eklendi!")
                    st.rerun()
    else:
        st.info("Eşleşme bulunamadı.")

    # ELIGIBILITY
    with st.spinner("✅ Uygunluk kontrolleri..."):
        elig = run_eligibility_checks(proposal, action)
    render_eligibility(elig)

    # BLIND
    if blind:
        sigs = scan_for_identity_signals(proposal.full_text, proposal.partner_names, proposal.person_names)
        rpt = generate_deidentification_report(sigs)
        with st.expander(f"🔒 Kimlik ({len(sigs)} sinyal)", expanded=len(sigs) > 0):
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
        call_ctx_text = (call_ctx_text + "\n\n" + manual_ctx) if call_ctx_text else manual_ctx

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

    results = ev.run(proposal, action, call_ctx_text, on_p, use_ai_rag=use_ai_rag)
    pbar.progress(1.0)
    stat_el.markdown("✅ Tamamlandı!")
    time.sleep(0.5)
    stat_el.empty()
    pbar.empty()

    st.divider()
    render_overall(results)

    st.markdown("## 📝 Kriter Detayları")
    show_coach = mode in ("both", "coaching_only")
    tab_names = [c.get("criterion", f"K{i + 1}") for i, c in enumerate(results["criteria"])]
    tabs = st.tabs(tab_names)
    for i, tab in enumerate(tabs):
        with tab:
            render_criterion(results["criteria"][i], results["coaching"][i] if i < len(results["coaching"]) else {}, show_coach)

    st.markdown("## 📥 Raporları İndir")
    d1, d2, d3 = st.columns(3)
    ed = [{"check_name": ch.check_name, "status": ch.status.value, "message": ch.message} for ch in elig.results]
    with d1:
        st.download_button("📊 JSON", json.dumps(results, indent=2, ensure_ascii=False), f"gm_{fn}.json", "application/json", use_container_width=True)
    with d2:
        st.download_button("📋 ESR", generate_esr_report(results, ed), f"gm_{fn}_esr.md", "text/markdown", use_container_width=True)
    with d3:
        st.download_button("🎯 Koçluk", generate_coaching_report(results), f"gm_{fn}_coach.md", "text/markdown", use_container_width=True)

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
            st.json({"top": matches[0].get("call_id", "?"), "score": matches[0].get("ai_match_score", 0)})
        if call_ctx_text:
            st.text_area("Bağlam", call_ctx_text[:1000], height=100, disabled=True)
        fp2 = results.get("funding_probability_pct", 0)
        tw2, tm2 = results.get("total_weighted", 0), results.get("total_max", 0)
        st.write(f"Ratio: {tw2}/{tm2} = {tw2 / tm2 * 100:.1f}%" if tm2 > 0 else "N/A")
        st.progress(fp2 / 100)
        st.write(f"RAG: {use_ai_rag} | Match: {use_ai_match} | Model: {MODEL_NAME} | DB: {len(HORIZON_CALLS_DB)}")
        st.json(results)


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
def main():
    render_header()
    page = st.sidebar.radio("📌", ["🔬 Değerlendirme", "📡 Canlı Çağrılar"], label_visibility="collapsed")
    with st.sidebar:
        st.divider()
        # Dinamik stats — cache'den veya DB'den
        cached_stats = st.session_state.get("last_fetch_stats", None)
        if cached_stats:
            t = cached_stats.get("total", 0)
            ec = cached_stats.get("ec_api", 0)
            eur = cached_stats.get("euresearch", 0)
            db = cached_stats.get("local_db", 0)
            st.caption(f"📊 Toplam: {t} | EC:{ec} EUR:{eur} DB:{db}")
        else:
            stats = get_call_stats()
            st.caption(f"📊 DB: {stats['total']} | 🟢 {stats['open']} | 🟡 {stats['forthcoming']}")
    if page == "📡 Canlı Çağrılar":
        render_calls_page()
    else:
        render_evaluation_page()


if __name__ == "__main__":
    main()
