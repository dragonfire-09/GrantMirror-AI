"""
GrantMirror-AI: Horizon Europe Proposal Pre-Screening & ESR Simulator
"""
import streamlit as st
import json
import time
import os
from typing import Dict, List, Optional
from collections import Counter
from openai import OpenAI

from config import (
    ActionType, ACTION_TYPE_CONFIGS, SCORE_DESCRIPTORS_0_5, WEAKNESS_TAXONOMY, CriterionConfig,
)
from document_parser import parse_proposal, ParsedProposal, SectionType
from eligibility_checker import run_eligibility_checks, CheckStatus, EligibilityReport
from knowledge_base import HorizonKnowledgeBase
from deidentifier import scan_for_identity_signals, generate_deidentification_report
from report_generator import generate_esr_report, generate_coaching_report
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
# LLM — OpenRouter
# ═══════════════════════════════════════════════════════════
MODEL_NAME = "openai/gpt-4o-mini"


def get_llm_client() -> OpenAI:
    api_key = st.secrets.get("OPENROUTER_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))
    if not api_key:
        st.error("🔑 OPENROUTER_API_KEY bulunamadı. `.streamlit/secrets.toml` dosyasına ekleyin.")
        st.stop()
    return OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")


def call_llm(
    client: OpenAI,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 4000,
    json_mode: bool = True,
) -> str:
    kwargs = dict(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            return json.dumps({
                "error": str(e), "score": 0, "strengths": [],
                "weaknesses": [f"LLM hatası: {e}"],
                "esr_comment": "Değerlendirme teknik hata nedeniyle tamamlanamadı.",
                "confidence_low": 0, "confidence_high": 0,
                "consensus_risk": "high", "weakness_categories": [],
                "sub_signal_assessments": [], "alternative_reading": "",
            })


# ═══════════════════════════════════════════════════════════
# PROMPT TEMPLATES
# ═══════════════════════════════════════════════════════════
SYSTEM_ESR = """You are an experienced Horizon Europe evaluator (10+ years, multiple FPs).
ABSOLUTE RULES:
1. Evaluate 'as is' — NEVER suggest improvements
2. Every claim MUST reference specific proposal content
3. Score MUST match comment balance
4. Do NOT penalize same weakness under multiple criteria
5. Scale 0-5 half-points: 0=fails, 1=poor, 2=fair, 3=good(threshold), 4=very good, 5=excellent
6. Third person: "The proposal..."
7. If information MISSING, state explicitly as weakness
8. Be concise but substantive like a real ESR"""

SYSTEM_COACH = """You are an expert Horizon Europe proposal consultant.
You identify weaknesses, explain WHY they reduce score, and give CONCRETE ACTIONABLE fixes.
Prioritize by score impact. Be constructive but brutally honest. Give example text where possible."""


def build_eval_prompt(
    crit: CriterionConfig, section_text: str, full_ctx: str,
    kb_ctx: str, action_type: str, call_ctx: str = "",
) -> str:
    qs = "\n".join(f"  • {q}" for q in crit.official_questions)
    checks = "\n".join(f"  • {c}" for c in crit.practical_checklist)
    sigs = ", ".join(crit.sub_signals)

    p = f"""## EVALUATE: {crit.name} ({action_type})

### OFFICIAL QUESTIONS:
{qs}

### QUALITY SIGNALS:
{checks}

### SUB-SIGNALS: {sigs}

### SCALE: 0-5 half-points. Threshold: {crit.threshold}/{crit.max_score}

### KNOWLEDGE:
{kb_ctx}
"""
    if call_ctx:
        p += f"\n### CALL CONTEXT:\n{call_ctx}\n"

    p += f"""
### PROPOSAL SECTION:
\"\"\"
{section_text[:15000]}
\"\"\"

### CROSS-REFERENCE:
\"\"\"
{full_ctx[:5000]}
\"\"\"

### RESPOND JSON:
{{
  "criterion": "{crit.name}",
  "score": <0.0-5.0 half-point>,
  "confidence_low": <float>,
  "confidence_high": <float>,
  "consensus_risk": "<low|medium|high>",
  "strengths": ["<with evidence>"],
  "weaknesses": ["<with evidence>"],
  "weakness_categories": ["<LACK_OF_DETAIL|LACK_OF_QUANTIFICATION|UNCLEAR_TARGET_GROUPS|RESOURCE_IMBALANCE|INTERNAL_INCOHERENCE|WEAK_RISK_MITIGATION|GENERIC_OPEN_SCIENCE|SOTA_GAP|GENERIC_DISSEMINATION|PATHWAY_VAGUE|TRL_INCONSISTENCY|PARTNER_ROLE_UNCLEAR>"],
  "sub_signal_assessments": [{{"signal":"...","rating":"<strong|adequate|weak|missing>","evidence":"...","comment":"..."}}],
  "esr_comment": "<2-3 paragraph ESR: strengths then weaknesses, NO suggestions>",
  "alternative_reading": "<if score 2.5-3.5: how another evaluator might differ; else empty>"
}}"""
    return p


def build_coach_prompt(
    name: str, score: float, weaknesses: List[str],
    categories: List[str], section: str, checklist: List[str],
) -> str:
    return f"""## COACH: {name} (score {score}/5)
WEAKNESSES: {json.dumps(weaknesses)}
CATEGORIES: {json.dumps(categories)}
SECTION: \"\"\"{section[:8000]}\"\"\"
CHECKLIST: {json.dumps(checklist[:8])}

Give 3-7 ranked improvements as JSON:
{{
  "improvements": [{{"priority":1,"title":"...","problem":"...","impact":"...","solution":"...","expected_score_gain":"..."}}],
  "summary": "..."
}}"""


# ═══════════════════════════════════════════════════════════
# EVALUATOR ENGINE
# ═══════════════════════════════════════════════════════════
class Evaluator:
    def __init__(self, client: OpenAI, kb: HorizonKnowledgeBase):
        self.client = client
        self.kb = kb

    def _section_text(self, proposal: ParsedProposal, criterion: str) -> str:
        mapping = {
            "Excellence": [SectionType.EXCELLENCE, SectionType.OPEN_SCIENCE, SectionType.GENDER_DIMENSION],
            "Impact": [SectionType.IMPACT, SectionType.DISSEMINATION, SectionType.EXPLOITATION],
            "Implementation": [SectionType.IMPLEMENTATION, SectionType.WORK_PACKAGES, SectionType.RISK_TABLE],
        }
        texts = []
        for st in mapping.get(criterion, []):
            if st in proposal.sections:
                texts.append(proposal.sections[st].content)
        if texts:
            return "\n\n".join(texts)
        t = proposal.full_text
        n = len(t)
        if criterion == "Excellence":
            return t[:n // 3]
        elif criterion == "Impact":
            return t[n // 3:2 * n // 3]
        return t[2 * n // 3:]

    def _cross_ctx(self, proposal: ParsedProposal) -> str:
        parts = []
        for st, sd in proposal.sections.items():
            if sd.word_count > 50:
                parts.append(f"[{st.value}]: {sd.content[:400]}")
        return "\n".join(parts)

    def eval_criterion(self, proposal, crit_cfg, action_type, call_ctx=""):
        sec = self._section_text(proposal, crit_cfg.name)
        kb_ctx = self.kb.get_criterion_context(crit_cfg.name, action_type.value)
        cross = self._cross_ctx(proposal)
        prompt = build_eval_prompt(crit_cfg, sec, cross, kb_ctx, action_type.value, call_ctx)
        raw = call_llm(self.client, SYSTEM_ESR, prompt)
        try:
            r = json.loads(raw)
        except json.JSONDecodeError:
            r = {"criterion": crit_cfg.name, "score": 0, "confidence_low": 0,
                 "confidence_high": 0, "consensus_risk": "high",
                 "strengths": [], "weaknesses": ["JSON parse hatası"],
                 "weakness_categories": [], "sub_signal_assessments": [],
                 "esr_comment": "Parse hatası.", "alternative_reading": ""}
        s = max(0.0, min(5.0, round(float(r.get("score", 0)) * 2) / 2))
        r["score"] = s
        r["confidence_low"] = max(0.0, float(r.get("confidence_low", s - 0.5)))
        r["confidence_high"] = min(5.0, float(r.get("confidence_high", s + 0.5)))
        return r

    def coach_criterion(self, crit_cfg, eval_r, proposal):
        sec = self._section_text(proposal, crit_cfg.name)
        prompt = build_coach_prompt(
            crit_cfg.name, eval_r.get("score", 0),
            eval_r.get("weaknesses", []), eval_r.get("weakness_categories", []),
            sec, crit_cfg.practical_checklist,
        )
        raw = call_llm(self.client, SYSTEM_COACH, prompt, temperature=0.4)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"improvements": [], "summary": "Koçluk üretilemedi."}

    def run(self, proposal, action_type, call_ctx="", on_progress=None):
        cfg = ACTION_TYPE_CONFIGS[action_type]
        results = {"action_type": action_type.value, "criteria": [], "coaching": []}
        total_w = 0.0
        all_met = True

        for i, cc in enumerate(cfg.criteria):
            if on_progress:
                on_progress(f"📝 {i+1}/{len(cfg.criteria)}: {cc.name}...")

            ev = self.eval_criterion(proposal, cc, action_type, call_ctx)
            ev["weight"] = cc.weight
            ev["threshold"] = cc.threshold
            ev["max_score"] = cc.max_score
            ev["threshold_met"] = ev["score"] >= cc.threshold
            ev["weighted_score"] = ev["score"] * cc.weight
            total_w += ev["weighted_score"]
            if not ev["threshold_met"]:
                all_met = False
            results["criteria"].append(ev)

            if on_progress:
                on_progress(f"💡 {cc.name} koçluk...")
            co = self.coach_criterion(cc, ev, proposal)
            co["criterion"] = cc.name
            results["coaching"].append(co)

        results["total_weighted"] = round(total_w, 1)
        results["total_max"] = cfg.total_max
        results["total_threshold"] = cfg.total_threshold
        results["total_threshold_met"] = all_met and total_w >= cfg.total_threshold
        results["all_criteria_met"] = all_met

        if not results["total_threshold_met"]:
            results["funding_probability"] = "very_low"
        elif total_w >= cfg.total_max * 0.85:
            results["funding_probability"] = "high"
        elif total_w >= cfg.total_max * 0.75:
            results["funding_probability"] = "medium"
        elif total_w >= cfg.total_threshold:
            results["funding_probability"] = "low"
        else:
            results["funding_probability"] = "very_low"

        cats = []
        for c in results["criteria"]:
            cats.extend(c.get("weakness_categories", []))
        cc2 = Counter(cats)
        results["cross_cutting_issues"] = [
            f"'{WEAKNESS_TAXONOMY[k]['label']}' — {v} kriterde: {WEAKNESS_TAXONOMY[k]['description']}"
            for k, v in cc2.items() if v > 1 and k in WEAKNESS_TAXONOMY
        ]
        return results


# ═══════════════════════════════════════════════════════════
# UI COMPONENTS
# ═══════════════════════════════════════════════════════════
def render_header():
    st.markdown("""
    <div style="text-align:center;padding:1rem 0;">
        <h1 style="font-size:2.4rem;font-weight:800;color:#1a1a2e;margin-bottom:0.2rem;">🔬 GrantMirror-AI</h1>
        <p style="font-size:1.1rem;color:#555;">Horizon Europe Proposal Pre-Screening & ESR Simulator</p>
        <p style="font-size:0.85rem;color:#888;">Teklifinizi hakem gözüyle okur · ESR eleştirilerini simüle eder · Düzeltme planı çıkarır</p>
    </div><hr>""", unsafe_allow_html=True)


def render_sidebar() -> Dict:
    with st.sidebar:
        st.markdown("## ⚙️ Ayarlar")
        labels = {
            ActionType.RIA: "🔬 RIA", ActionType.IA: "🚀 IA", ActionType.CSA: "🤝 CSA",
            ActionType.MSCA_DN: "🎓 MSCA-DN", ActionType.EIC_PATHFINDER_OPEN: "💡 EIC Pathfinder",
            ActionType.EIC_ACCELERATOR: "📈 EIC Accelerator", ActionType.ERC_STG: "⭐ ERC StG",
        }
        action = st.selectbox("Aksiyon Türü", list(labels.keys()), format_func=lambda x: labels[x])
        cfg = ACTION_TYPE_CONFIGS[action]

        with st.expander("ℹ️ Detaylar"):
            st.markdown(f"Puanlama: {cfg.scoring_scale}")
            st.markdown(f"Eşik: {cfg.total_threshold}/{cfg.total_max}")
            st.markdown(f"Kör: {'Evet' if cfg.blind_evaluation else 'Hayır'}")
            st.markdown(f"Min konsorsiyum: {cfg.min_consortium_size}")
            if cfg.page_limit_full:
                st.markdown(f"Sayfa: {cfg.page_limit_full}")
            for r in cfg.special_rules:
                st.markdown(f"- _{r}_")

        st.markdown("---")
        mode = st.radio("Çıktı", ["both", "esr_only", "coaching_only"],
                        format_func=lambda x: {"both": "📋+🎯 Tam", "esr_only": "📋 ESR", "coaching_only": "🎯 Koçluk"}[x])

        st.markdown("---")
        call_ctx = st.text_area("Çağrı Bağlamı (opsiyonel)", height=100,
                                placeholder="Work Programme scope / expected outcomes...")

        st.markdown("---")
        blind = st.checkbox("🔒 Kimlik taraması", value=cfg.blind_evaluation)

        st.markdown("---")
        st.caption("⚠️ Bu araç resmî EC değerlendirmesinin yerini almaz.")

        return {"action_type": action, "mode": mode, "call_ctx": call_ctx, "blind": blind}


def render_score_bar(score: float, mx: float, thr: float, label: str):
    pct = score / mx * 100 if mx > 0 else 0
    thr_pct = thr / mx * 100 if mx > 0 else 0
    color = "#2ecc71" if score >= thr + 1 else "#f39c12" if score >= thr else "#e74c3c"
    st.markdown(f"""
    <div style="margin-bottom:1rem;">
        <div style="display:flex;justify-content:space-between;margin-bottom:0.3rem;">
            <span style="font-weight:600;">{label}</span>
            <span style="font-weight:700;color:{color};">{score}/{mx}</span>
        </div>
        <div style="background:#e8e8e8;border-radius:10px;height:22px;position:relative;overflow:hidden;">
            <div style="background:{color};width:{pct}%;height:100%;border-radius:10px;"></div>
            <div style="position:absolute;left:{thr_pct}%;top:0;height:100%;width:2px;background:#333;"></div>
        </div>
        <div style="font-size:0.75rem;color:#888;margin-top:0.15rem;">Eşik: {thr} | {'✅' if score>=thr else '❌'}</div>
    </div>""", unsafe_allow_html=True)


def render_eligibility(elig: EligibilityReport):
    icon_map = {"pass": "✅", "fail": "❌", "warning": "⚠️", "info": "ℹ️", "unable": "❓"}
    title = f"{'✅' if elig.is_eligible else '❌'} Uygunluk Kontrolü"
    with st.expander(title, expanded=not elig.is_eligible):
        for ch in elig.results:
            st.markdown(f"{icon_map.get(ch.status.value, '')} **{ch.check_name}**: {ch.message}")
            if ch.details:
                st.caption(ch.details)


def render_criterion(crit: Dict, coach: Dict, show_coach: bool):
    name = crit.get("criterion", "?")
    score = crit.get("score", 0)
    mx = crit.get("max_score", 5)
    thr = crit.get("threshold", 3)

    render_score_bar(score, mx, thr, name)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Güven Aralığı", f"{crit.get('confidence_low', '?')} – {crit.get('confidence_high', '?')}")
    with c2:
        risk = crit.get("consensus_risk", "?")
        ri = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(risk, "⚪")
        st.metric("Uzlaşma Riski", f"{ri} {risk}")
    with c3:
        st.metric("Ağırlıklı Puan", f"{crit.get('weighted_score', 0):.1f}")

    # ESR
    st.markdown("#### 📋 ESR Yorumu")
    st.info(crit.get("esr_comment", "N/A"))

    # Strengths / Weaknesses
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

    # Categories
    cats = crit.get("weakness_categories", [])
    if cats:
        labels = [f"`{WEAKNESS_TAXONOMY.get(c, {}).get('label', c)}`" for c in cats]
        st.markdown("**🏷️ Kategoriler:** " + " · ".join(labels))

    # Sub-signals
    subs = crit.get("sub_signal_assessments", [])
    if subs:
        with st.expander("📊 Alt Sinyaller"):
            for sa in subs:
                r = sa.get("rating", "?")
                ic = {"strong": "🟢", "adequate": "🟡", "weak": "🟠", "missing": "🔴"}.get(r, "⚪")
                st.markdown(f"{ic} **{sa.get('signal', '?')}** — {r}")
                if sa.get("comment"):
                    st.caption(sa["comment"])

    # Alt reading
    alt = crit.get("alternative_reading", "")
    if alt:
        with st.expander("🔄 Alternatif Okuma"):
            st.markdown(alt)

    # Coaching
    if show_coach and coach:
        st.markdown("---")
        st.markdown("#### 🎯 Koçluk")
        for imp in coach.get("improvements", []):
            with st.expander(f"🔧 P{imp.get('priority', '?')}: {imp.get('title', '?')} ({imp.get('expected_score_gain', '?')})"):
                st.markdown(f"**Problem:** {imp.get('problem', '')}")
                st.markdown(f"**Etki:** {imp.get('impact', '')}")
                st.markdown(f"**Çözüm:** {imp.get('solution', '')}")
        if coach.get("summary"):
            st.markdown(f"**Özet:** {coach['summary']}")


def render_overall(results: Dict):
    st.markdown("## 📊 Genel Özet")
    cfg = ACTION_TYPE_CONFIGS[ActionType(results["action_type"])]

    c1, c2, c3, c4 = st.columns(4)
    tw = results["total_weighted"]
    thr = results["total_threshold"]
    met = results["total_threshold_met"]

    with c1:
        st.metric("Toplam", f"{tw}/{results['total_max']}",
                   delta=f"{tw - thr:+.1f}" if met else f"{tw - thr:.1f}",
                   delta_color="normal" if met else "inverse")
    with c2:
        pl = {"high": "🟢 Yüksek", "medium": "🟡 Orta", "low": "🟠 Düşük", "very_low": "🔴 Çok Düşük"}
        st.metric("Fonlanma", pl.get(results.get("funding_probability", ""), "?"))
    with c3:
        ok = sum(1 for c in results["criteria"] if c.get("threshold_met"))
        st.metric("Kriter Eşik", f"{ok}/{len(results['criteria'])}")
    with c4:
        st.metric("Sistemik Sorun", len(results.get("cross_cutting_issues", [])))

    st.markdown("---")
    cols = st.columns(len(results["criteria"]))
    for i, cr in enumerate(results["criteria"]):
        with cols[i]:
            render_score_bar(cr["score"], cr["max_score"], cr["threshold"], cr.get("criterion", f"K{i+1}"))

    cross = results.get("cross_cutting_issues", [])
    if cross:
        st.markdown("### ⚠️ Kriterler Arası Sorunlar")
        for iss in cross:
            st.warning(iss)


def render_doc_overview(proposal: ParsedProposal):
    with st.expander("📄 Belge Özeti"):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Sayfa", proposal.total_pages)
        with c2:
            st.metric("Kelime", f"{proposal.total_words:,}")
        with c3:
            st.metric("Bölüm", len(proposal.sections))
        if proposal.acronym:
            st.markdown(f"**Kısaltma**: {proposal.acronym}")
        for st2, sd in proposal.sections.items():
            st.markdown(f"- **{st2.value}**: {sd.word_count} kelime")
        if proposal.warnings:
            for w in proposal.warnings:
                st.warning(w)


def render_blind_scan(proposal: ParsedProposal):
    sigs = scan_for_identity_signals(proposal.full_text, proposal.partner_names, proposal.person_names)
    rpt = generate_deidentification_report(sigs)
    with st.expander(f"🔒 Kimlik Taraması ({len(sigs)} sinyal)", expanded=len(sigs) > 0):
        st.markdown(rpt)


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
def main():
    render_header()
    settings = render_sidebar()

    st.markdown("## 📤 Teklif Yükleme")
    uploaded = st.file_uploader("Horizon Europe Part B (PDF / DOCX)", type=["pdf", "docx", "doc"])

    if uploaded is None:
        st.markdown("""---
### 🎯 GrantMirror-AI Ne Yapar?
| Özellik | Açıklama |
|---------|----------|
| 📋 ESR Simülasyonu | Hakem formatında kriter bazlı değerlendirme |
| 🔍 Uygunluk Kontrolü | Sayfa, konsorsiyum, bölüm, kör değerlendirme |
| 🎯 Koçluk | Somut, öncelikli düzeltme önerileri |
| 📊 Güven Aralığı | Puan aralığı + uzlaşma riski |
| 🔒 Kimlik Taraması | Kör çağrılar için kimlik ifşa tespiti |
| 🏷️ Taksonomi | 12 zayıflık kategorisi otomatik sınıflama |

### Desteklenen: RIA · IA · CSA · MSCA-DN · EIC Pathfinder · EIC Accelerator · ERC StG

⚠️ *Bu araç resmî EC değerlendirmesinin yerini almaz.*""")
        return

    file_bytes = uploaded.read()
    filename = uploaded.name

    # 1 Parse
    with st.spinner("📄 Belge okunuyor..."):
        try:
            proposal = parse_proposal(file_bytes, filename)
        except Exception as e:
            st.error(f"❌ Belge hatası: {e}")
            return

    render_doc_overview(proposal)

    # 2 Eligibility
    with st.spinner("✅ Uygunluk kontrolleri..."):
        elig = run_eligibility_checks(proposal, settings["action_type"])
    render_eligibility(elig)

    # 3 Blind scan
    if settings["blind"]:
        render_blind_scan(proposal)

    # 4 Evaluation
    st.markdown("---")
    st.markdown("## 🚀 Değerlendirme")

    cfg = ACTION_TYPE_CONFIGS[settings["action_type"]]
    n = len(cfg.criteria)

    c_btn, c_info = st.columns([1, 2])
    with c_btn:
        go = st.button("🔬 Değerlendirmeyi Başlat", type="primary", use_container_width=True)
    with c_info:
        st.info(f"{settings['action_type'].value}: {n} kriter · ~{n*30}-{n*60}s")

    if not go:
        return

    client = get_llm_client()
    kb = HorizonKnowledgeBase()
    ev = Evaluator(client, kb)

    pbar = st.progress(0.0)
    status = st.empty()
    step = [0]
    total_steps = n * 2

    def on_prog(msg):
        status.markdown(f"⏳ {msg}")
        step[0] += 1
        pbar.progress(min(step[0] / total_steps, 1.0))

    with st.spinner("🔬 Değerlendirme yapılıyor..."):
        results = ev.run(proposal, settings["action_type"], settings["call_ctx"], on_prog)

    pbar.progress(1.0)
    status.markdown("✅ Tamamlandı!")
    time.sleep(0.5)
    status.empty()
    pbar.empty()

    # Display
    st.markdown("---")
    render_overall(results)
    st.markdown("---")
    st.markdown("## 📝 Kriter Detayları")

    show_coach = settings["mode"] in ("both", "coaching_only")
    tab_names = [c.get("criterion", f"K{i+1}") for i, c in enumerate(results["criteria"])]
    tabs = st.tabs(tab_names)

    for i, tab in enumerate(tabs):
        with tab:
            cd = results["criteria"][i]
            co = results["coaching"][i] if i < len(results["coaching"]) else {}
            render_criterion(cd, co, show_coach)

        # Downloads
    st.markdown("---")
    st.markdown("## 📥 İndir")
    d1, d2, d3 = st.columns(3)

    # Eligibility results'ı dict listesine çevir (report_generator dış bağımlılık almıyor)
    elig_dicts = [
        {"check_name": ch.check_name, "status": ch.status.value, "message": ch.message}
        for ch in elig.results
    ]

    with d1:
        st.download_button(
            "📊 JSON",
            json.dumps(results, indent=2, ensure_ascii=False),
            f"grantmirror_{filename}.json",
            "application/json",
            use_container_width=True,
        )
    with d2:
        st.download_button(
            "📋 ESR (MD)",
            generate_esr_report(results, elig_dicts),
            f"grantmirror_{filename}_esr.md",
            "text/markdown",
            use_container_width=True,
        )
    with d3:
        st.download_button(
            "🎯 Koçluk (MD)",
            generate_coaching_report(results),
            f"grantmirror_{filename}_coach.md",
            "text/markdown",
            use_container_width=True,
        )

if __name__ == "__main__":
    main()
