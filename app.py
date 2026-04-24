"""
GrantMirror-AI: Horizon Europe Proposal Pre-Screening & ESR Simulator
Main Streamlit Application — OpenRouter + gpt-4o-mini backend
"""
import streamlit as st
import json
import os
import time
from typing import Optional, Dict, List
from openai import OpenAI

from config import (
    ActionType,
    ACTION_TYPE_CONFIGS,
    OutputMode,
    SCORE_DESCRIPTORS_0_5,
    WEAKNESS_TAXONOMY,
    CriterionConfig,
)
from document_parser import parse_proposal, ParsedProposal, SectionType
from eligibility_checker import run_eligibility_checks, CheckStatus, EligibilityReport
from knowledge_base import HorizonKnowledgeBase
from deidentifier import scan_for_identity_signals, generate_deidentification_report
from report_generator import (
    generate_esr_report,
    generate_coaching_report,
    generate_quick_summary,
)

# ═══════════════════════════════════════════════════════════
# LLM CLIENT SETUP — OpenRouter
# ═══════════════════════════════════════════════════════════
def get_llm_client() -> OpenAI:
    """Get OpenRouter-backed OpenAI-compatible client."""
    api_key = st.secrets.get("OPENROUTER_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))
    if not api_key:
        st.error("🔑 OPENROUTER_API_KEY bulunamadı. Lütfen `.streamlit/secrets.toml` veya environment variable olarak ayarlayın.")
        st.stop()
    return OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )


MODEL_NAME = "openai/gpt-4o-mini"


def call_llm(
    client: OpenAI,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 4000,
    json_mode: bool = True,
) -> str:
    """Call LLM via OpenRouter with error handling and retry."""
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
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            return json.dumps({
                "error": str(e),
                "score": 0,
                "strengths": [],
                "weaknesses": [f"LLM çağrısı başarısız: {str(e)}"],
                "esr_comment": "Değerlendirme teknik hata nedeniyle tamamlanamadı.",
            })


# ═══════════════════════════════════════════════════════════
# PROMPT TEMPLATES
# ═══════════════════════════════════════════════════════════
SYSTEM_PROMPT_ESR = """You are an experienced Horizon Europe evaluator with 10+ years of experience across 
multiple Framework Programmes. You follow EC evaluation rules STRICTLY:

ABSOLUTE RULES:
1. Evaluate the proposal 'as is' — NEVER suggest improvements or assume fixes
2. Every criticism MUST point to a specific weakness IN THE TEXT
3. Every positive comment MUST point to a specific strength IN THE TEXT
4. Score MUST be CONSISTENT with your written comments
5. Do NOT penalize the same weakness under multiple criteria
6. Use the official EC scoring scale (0-5, half-point increments):
   0 = fails to address / cannot be assessed
   1 = poor — serious inherent weaknesses
   2 = fair — significant weaknesses
   3 = good — a number of shortcomings (THRESHOLD)
   4 = very good — small number of shortcomings
   5 = excellent — only minor shortcomings
7. Write in third person: "The proposal...", "The methodology..."
8. Be concise but substantive — like a real Evaluation Summary Report
9. Provide evidence for every claim by quoting or referencing specific proposal content
10. If information is MISSING, state that explicitly as a weakness"""

SYSTEM_PROMPT_COACH = """You are an expert Horizon Europe proposal consultant. Unlike an evaluator, you:
1. Identify specific weaknesses and explain WHY they reduce the score
2. Provide CONCRETE, ACTIONABLE revision suggestions with examples
3. Prioritize improvements by expected score impact
4. Reference common evaluator expectations from real ESR analysis
5. Be constructive but brutally honest — do not soften critical issues
6. Give specific text suggestions where possible: "Replace X with Y"
7. Think like a reviewer who wants to help the applicant succeed"""


def build_criterion_evaluation_prompt(
    criterion_config: CriterionConfig,
    section_text: str,
    full_context: str,
    knowledge_context: str,
    action_type: str,
    call_context: str = "",
) -> str:
    """Build criterion-specific evaluation prompt."""
    official_qs = "\n".join(f"  • {q}" for q in criterion_config.official_questions)
    practical_checks = "\n".join(f"  • {c}" for c in criterion_config.practical_checklist)
    sub_sigs = ", ".join(criterion_config.sub_signals)

    prompt = f"""## EVALUATION TASK: {criterion_config.name} criterion ({action_type})

### OFFICIAL EC EVALUATION QUESTIONS:
{official_qs}

### QUALITY SIGNALS TO CHECK (from real ESR analysis):
{practical_checks}

### SUB-SIGNALS TO ASSESS: {sub_sigs}

### SCORING SCALE (0-5, half-points allowed):
0 = Fails to address | 1 = Poor | 2 = Fair | 3 = Good (threshold) | 4 = Very good | 5 = Excellent
Per-criterion threshold: {criterion_config.threshold}/{criterion_config.max_score}

### KNOWLEDGE BASE CONTEXT:
{knowledge_context}
"""
    if call_context:
        prompt += f"\n### CALL/TOPIC CONTEXT:\n{call_context}\n"

    prompt += f"""
### PROPOSAL — {criterion_config.name} SECTION:
\"\"\"
{section_text[:15000]}
\"\"\"

### PROPOSAL — ADDITIONAL CONTEXT (other sections for cross-reference):
\"\"\"
{full_context[:5000]}
\"\"\"

### RESPOND IN THIS EXACT JSON FORMAT:
{{
    "criterion": "{criterion_config.name}",
    "score": <float, 0.0 to 5.0, half-point increments like 3.0, 3.5, 4.0>,
    "confidence_low": <float, lower bound of plausible score range>,
    "confidence_high": <float, upper bound of plausible score range>,
    "consensus_risk": "<low|medium|high> — how likely evaluators would disagree on this score",
    "strengths": [
        "<specific strength #1 with evidence from proposal text>",
        "<specific strength #2 with evidence>"
    ],
    "weaknesses": [
        "<specific weakness #1 with evidence or noting what is MISSING>",
        "<specific weakness #2 with evidence>"
    ],
    "weakness_categories": [
        "<from: LACK_OF_DETAIL, LACK_OF_QUANTIFICATION, UNCLEAR_TARGET_GROUPS, RESOURCE_IMBALANCE, INTERNAL_INCOHERENCE, WEAK_RISK_MITIGATION, GENERIC_OPEN_SCIENCE, SOTA_GAP, GENERIC_DISSEMINATION, PATHWAY_VAGUE, TRL_INCONSISTENCY, PARTNER_ROLE_UNCLEAR>"
    ],
    "sub_signal_assessments": [
        {{
            "signal": "<signal_name from list>",
            "rating": "<strong|adequate|weak|missing>",
            "evidence": "<direct quote or specific reference from proposal>",
            "comment": "<1-2 sentence assessment>"
        }}
    ],
    "esr_comment": "<2-3 paragraph ESR-style comment: first paragraph = strengths, second = weaknesses, all evidence-based, professional tone, NO suggestions for improvement>",
    "alternative_reading": "<If score is 2.5-3.5 range: describe how a stricter or more generous evaluator might score differently. Otherwise: empty string>"
}}

CRITICAL REMINDERS:
- EVERY strength/weakness MUST reference specific content from the proposal
- If a required element is MISSING from the text, that is a weakness
- Score MUST match the balance of strengths vs weaknesses
- Do NOT suggest improvements — only describe what IS and what IS NOT in the proposal"""

    return prompt


def build_coaching_prompt(
    criterion_name: str,
    score: float,
    weaknesses: List[str],
    weakness_categories: List[str],
    section_text: str,
    practical_checklist: List[str],
) -> str:
    """Build coaching/improvement prompt."""
    return f"""## COACHING TASK: Improve {criterion_name} (current score: {score}/5.0)

### IDENTIFIED WEAKNESSES:
{json.dumps(weaknesses, indent=2)}

### WEAKNESS CATEGORIES:
{json.dumps(weakness_categories)}

### PROPOSAL SECTION TEXT:
\"\"\"
{section_text[:8000]}
\"\"\"

### QUALITY CHECKLIST:
{json.dumps(practical_checklist[:8])}

### INSTRUCTIONS:
Provide 3-7 SPECIFIC, ACTIONABLE improvement recommendations:
1. Ranked by expected score impact (highest first)
2. For each: explain WHAT is wrong, WHY it hurts the score, and exactly HOW to fix it
3. Where possible, give example text/structure the applicant could use
4. Reference the checklist items where relevant
5. Be concrete: "Add a table with columns X, Y, Z showing..." NOT "improve the methodology"

Respond in this JSON format:
{{
    "improvements": [
        {{
            "priority": 1,
            "title": "<short title>",
            "problem": "<what is wrong>",
            "impact": "<why this hurts the score>",
            "solution": "<exactly how to fix it, with example if possible>",
            "expected_score_gain": "<estimated improvement, e.g., +0.5>"
        }}
    ],
    "summary": "<1-2 paragraph overall coaching advice>"
}}"""


# ═══════════════════════════════════════════════════════════
# EVALUATION ENGINE (uses OpenRouter LLM)
# ═══════════════════════════════════════════════════════════
class GrantMirrorEvaluator:
    """Main evaluation engine integrating all modules."""

    def __init__(self, client: OpenAI, knowledge_base: HorizonKnowledgeBase):
        self.client = client
        self.kb = knowledge_base

    def _get_section_text(self, proposal: ParsedProposal, criterion_name: str) -> str:
        """Get the most relevant section text for a criterion."""
        section_map = {
            "Excellence": [SectionType.EXCELLENCE, SectionType.OPEN_SCIENCE, SectionType.GENDER_DIMENSION],
            "Impact": [SectionType.IMPACT, SectionType.DISSEMINATION, SectionType.EXPLOITATION],
            "Implementation": [SectionType.IMPLEMENTATION, SectionType.WORK_PACKAGES, SectionType.RISK_TABLE],
        }

        target_sections = section_map.get(criterion_name, [])
        texts = []

        for st_type in target_sections:
            if st_type in proposal.sections:
                texts.append(proposal.sections[st_type].content)

        if texts:
            return "\n\n".join(texts)

        # Fallback: return chunk of full text
        full = proposal.full_text
        total = len(full)
        if criterion_name == "Excellence":
            return full[:total // 3]
        elif criterion_name == "Impact":
            return full[total // 3: 2 * total // 3]
        else:
            return full[2 * total // 3:]

    def evaluate_criterion(
        self,
        proposal: ParsedProposal,
        criterion_config: CriterionConfig,
        action_type: ActionType,
        call_context: str = "",
        progress_callback=None,
    ) -> Dict:
        """Evaluate a single criterion using LLM."""
        section_text = self._get_section_text(proposal, criterion_config.name)

        knowledge_context = self.kb.get_criterion_context(
            criterion=criterion_config.name,
            action_type=action_type.value,
        )

        # Build other sections for cross-reference
        other_sections = []
        for sec_type, sec_data in proposal.sections.items():
            if sec_data.word_count > 50:
                other_sections.append(f"[{sec_type.value}]: {sec_data.content[:500]}")
        full_context = "\n".join(other_sections)

        user_prompt = build_criterion_evaluation_prompt(
            criterion_config=criterion_config,
            section_text=section_text,
            full_context=full_context,
            knowledge_context=knowledge_context,
            action_type=action_type.value,
            call_context=call_context,
        )

        if progress_callback:
            progress_callback(f"🔍 {criterion_config.name} değerlendiriliyor...")

        raw = call_llm(self.client, SYSTEM_PROMPT_ESR, user_prompt)

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {
                "criterion": criterion_config.name,
                "score": 0,
                "confidence_low": 0,
                "confidence_high": 0,
                "consensus_risk": "high",
                "strengths": [],
                "weaknesses": ["JSON parse hatası — değerlendirme tekrarlanmalı"],
                "weakness_categories": [],
                "sub_signal_assessments": [],
                "esr_comment": "Değerlendirme ayrıştırma hatası nedeniyle tamamlanamadı.",
                "alternative_reading": "",
            }

        # Validate and clamp score
        score = float(result.get("score", 0))
        score = max(0.0, min(5.0, round(score * 2) / 2))  # Clamp and round to 0.5
        result["score"] = score
        result["confidence_low"] = max(0.0, float(result.get("confidence_low", score - 0.5)))
        result["confidence_high"] = min(5.0, float(result.get("confidence_high", score + 0.5)))

        return result

    def generate_coaching(
        self,
        criterion_config: CriterionConfig,
        eval_result: Dict,
        proposal: ParsedProposal,
    ) -> Dict:
        """Generate coaching advice for a criterion."""
        section_text = self._get_section_text(proposal, criterion_config.name)

        user_prompt = build_coaching_prompt(
            criterion_name=criterion_config.name,
            score=eval_result.get("score", 0),
            weaknesses=eval_result.get("weaknesses", []),
            weakness_categories=eval_result.get("weakness_categories", []),
            section_text=section_text,
            practical_checklist=criterion_config.practical_checklist,
        )

        raw = call_llm(self.client, SYSTEM_PROMPT_COACH, user_prompt, temperature=0.4)

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {
                "improvements": [],
                "summary": "Koçluk önerisi oluşturulamadı.",
            }

    def full_evaluation(
        self,
        proposal: ParsedProposal,
        action_type: ActionType,
        call_context: str = "",
        progress_callback=None,
    ) -> Dict:
        """Run full evaluation across all criteria."""
        config = ACTION_TYPE_CONFIGS[action_type]
        results = {
            "action_type": action_type.value,
            "criteria": [],
            "coaching": [],
        }

        total_weighted = 0.0
        all_thresholds_met = True

        for i, crit_config in enumerate(config.criteria):
            if progress_callback:
                progress_callback(
                    f"📝 Kriter {i+1}/{len(config.criteria)}: {crit_config.name} değerlendiriliyor..."
                )

            # ESR evaluation
            eval_result = self.evaluate_criterion(
                proposal, crit_config, action_type, call_context, progress_callback
            )
            eval_result["weight"] = crit_config.weight
            eval_result["threshold"] = crit_config.threshold
            eval_result["max_score"] = crit_config.max_score
            eval_result["threshold_met"] = eval_result["score"] >= crit_config.threshold

            weighted_score = eval_result["score"] * crit_config.weight
            eval_result["weighted_score"] = weighted_score
            total_weighted += weighted_score

            if not eval_result["threshold_met"]:
                all_thresholds_met = False

            results["criteria"].append(eval_result)

            # Coaching
            if progress_callback:
                progress_callback(f"💡 {crit_config.name} için koçluk önerisi oluşturuluyor...")

            coaching = self.generate_coaching(crit_config, eval_result, proposal)
            coaching["criterion"] = crit_config.name
            results["coaching"].append(coaching)

        # Aggregate
        results["total_weighted"] = round(total_weighted, 1)
        results["total_max"] = config.total_max
        results["total_threshold"] = config.total_threshold
        results["total_threshold_met"] = all_thresholds_met and total_weighted >= config.total_threshold
        results["all_criteria_met"] = all_thresholds_met

        # Funding probability
        if not results["total_threshold_met"]:
            results["funding_probability"] = "very_low"
        elif total_weighted >= config.total_max * 0.85:
            results["funding_probability"] = "high"
        elif total_weighted >= config.total_max * 0.75:
            results["funding_probability"] = "medium"
        elif total_weighted >= config.total_threshold:
            results["funding_probability"] = "low"
        else:
            results["funding_probability"] = "very_low"

        # Cross-cutting weakness detection
        all_categories = []
        for c in results["criteria"]:
            all_categories.extend(c.get("weakness_categories", []))

        from collections import Counter
        cat_counts = Counter(all_categories)
        results["cross_cutting_issues"] = [
            f"'{WEAKNESS_TAXONOMY[cat]['label']}' — {count} kriterde tespit edildi: {WEAKNESS_TAXONOMY[cat]['description']}"
            for cat, count in cat_counts.items()
            if count > 1 and cat in WEAKNESS_TAXONOMY
        ]

        return results


# ═══════════════════════════════════════════════════════════
# STREAMLIT UI
# ═══════════════════════════════════════════════════════════

def render_header():
    """Render app header."""
    st.markdown("""
    <div style="text-align: center; padding: 1rem 0;">
        <h1 style="font-size: 2.4rem; font-weight: 800; color: #1a1a2e; margin-bottom: 0.2rem;">
            🔬 GrantMirror-AI
        </h1>
        <p style="font-size: 1.15rem; color: #555; margin-top: 0;">
            Horizon Europe Proposal Pre-Screening & ESR Simulator
        </p>
        <p style="font-size: 0.85rem; color: #888;">
            Teklifinizi hakem gözüyle okur · ESR eleştirilerini önceden simüle eder · Düzeltme planı çıkarır
        </p>
    </div>
    <hr style="border: 1px solid #e0e0e0;">
    """, unsafe_allow_html=True)


def render_sidebar() -> Dict:
    """Render sidebar controls and return settings."""
    with st.sidebar:
        st.markdown("## ⚙️ Ayarlar")

        st.markdown("### 📋 Aksiyon Türü")
        action_type_labels = {
            ActionType.RIA: "🔬 RIA — Research & Innovation Action",
            ActionType.IA: "🚀 IA — Innovation Action",
            ActionType.CSA: "🤝 CSA — Coordination & Support Action",
            ActionType.MSCA_DN: "🎓 MSCA — Doctoral Networks",
            ActionType.EIC_PATHFINDER_OPEN: "💡 EIC Pathfinder Open",
            ActionType.EIC_ACCELERATOR: "📈 EIC Accelerator",
            ActionType.ERC_STG: "⭐ ERC Starting Grant",
        }

        selected_action = st.selectbox(
            "Aksiyon türünü seçin",
            options=list(action_type_labels.keys()),
            format_func=lambda x: action_type_labels[x],
            index=0,
        )

        # Show action type info
        config = ACTION_TYPE_CONFIGS[selected_action]
        with st.expander("ℹ️ Seçilen aksiyon detayları"):
            st.markdown(f"**Puanlama**: {config.scoring_scale}")
            st.markdown(f"**Toplam eşik**: {config.total_threshold}/{config.total_max}")
            st.markdown(f"**Kör değerlendirme**: {'Evet' if config.blind_evaluation else 'Hayır'}")
            st.markdown(f"**Min. konsorsiyum**: {config.min_consortium_size} kuruluş, {config.min_countries} ülke")
            if config.page_limit_full:
                st.markdown(f"**Sayfa limiti**: {config.page_limit_full}")
            for rule in config.special_rules:
                st.markdown(f"- _{rule}_")

        st.markdown("---")
        st.markdown("### 🎯 Değerlendirme Modu")

        eval_mode = st.radio(
            "Çıktı formatı",
            options=["both", "esr_only", "coaching_only"],
            format_func=lambda x: {
                "both": "📋 ESR + 🎯 Koçluk (Tam)",
                "esr_only": "📋 Sadece ESR Simülasyonu",
                "coaching_only": "🎯 Sadece Koçluk",
            }[x],
            index=0,
        )

        st.markdown("---")
        st.markdown("### 📝 Çağrı Bağlamı (Opsiyonel)")
        call_context = st.text_area(
            "Çağrı/topic metnini yapıştırın",
            height=120,
            placeholder="Work Programme'daki topic scope, expected outcomes vb. bilgileri buraya yapıştırabilirsiniz...",
            help="Bu bilgi, değerlendirmenin çağrıya uygunluğunu artırır.",
        )

        st.markdown("---")
        st.markdown("### 🔒 Kör Değerlendirme Taraması")
        run_deidentification = st.checkbox(
            "Kimlik ifşa taraması yap",
            value=config.blind_evaluation,
            help="İki aşamalı çağrılarda 2026'dan itibaren varsayılan. Kurum/kişi adı, self-referans vb. tarar.",
        )

        st.markdown("---")
        st.markdown("""
        <div style="background: #f0f7ff; padding: 0.8rem; border-radius: 8px; font-size: 0.8rem; color: #444;">
            <strong>⚠️ Yasal Uyarı</strong><br>
            Bu araç resmî EC değerlendirmesinin yerini almaz. 
            Ön-tarama ve hazırlık aracı olarak tasarlanmıştır.
            Gerçek puanlar hakem uzmanlığı, panel dinamiği ve 
            çağrı rekabetine bağlıdır.
        </div>
        """, unsafe_allow_html=True)

        return {
            "action_type": selected_action,
            "eval_mode": eval_mode,
            "call_context": call_context,
            "run_deidentification": run_deidentification,
        }


def render_score_gauge(score: float, max_score: float, threshold: float, label: str):
    """Render a visual score gauge."""
    pct = score / max_score * 100
    threshold_pct = threshold / max_score * 100
    color = "#2ecc71" if score >= threshold + 1 else "#f39c12" if score >= threshold else "#e74c3c"

    st.markdown(f"""
    <div style="margin-bottom: 1rem;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 0.3rem;">
            <span style="font-weight: 600;">{label}</span>
            <span style="font-weight: 700; color: {color};">{score}/{max_score}</span>
        </div>
        <div style="background: #e8e8e8; border-radius: 10px; height: 24px; position: relative; overflow: hidden;">
            <div style="background: {color}; width: {pct}%; height: 100%; border-radius: 10px; transition: width 0.5s;"></div>
            <div style="position: absolute; left: {threshold_pct}%; top: 0; height: 100%; width: 2px; background: #333;" title="Threshold: {threshold}"></div>
        </div>
        <div style="font-size: 0.75rem; color: #888; margin-top: 0.2rem;">
            Eşik: {threshold} | {'✅ Geçti' if score >= threshold else '❌ Geçemedi'}
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_eligibility_results(eligibility: EligibilityReport):
    """Render eligibility check results."""
    with st.expander(
        f"{'✅' if eligibility.is_eligible else '❌'} Uygunluk & Kabul Edilebilirlik Kontrolü",
        expanded=not eligibility.is_eligible,
    ):
        for check in eligibility.results:
            icon = {
                CheckStatus.PASS: "✅",
                CheckStatus.FAIL: "❌",
                CheckStatus.WARNING: "⚠️",
                CheckStatus.INFO: "ℹ️",
                CheckStatus.UNABLE: "❓",
            }[check.status]

            st.markdown(f"{icon} **{check.check_name}**: {check.message}")
            if check.details:
                st.markdown(f"  _{check.details}_")


def render_criterion_result(criterion_data: Dict, coaching_data: Dict, show_coaching: bool):
    """Render evaluation result for a single criterion."""
    score = criterion_data["score"]
    threshold = criterion_data["threshold"]
    max_score = criterion_data["max_score"]
    name = criterion_data.get("criterion", "Unknown")

    # Score gauge
    render_score_gauge(score, max_score, threshold, name)

    # Confidence and consensus
    col1, col2, col3 = st.columns(3)
    with col1:
        conf_low = criterion_data.get("confidence_low", score - 0.5)
        conf_high = criterion_data.get("confidence_high", score + 0.5)
        st.metric("Güven Aralığı", f"{conf_low} – {conf_high}")
    with col2:
        risk = criterion_data.get("consensus_risk", "medium")
        risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(risk, "⚪")
        st.metric("Uzlaşma Riski", f"{risk_emoji} {risk.title()}")
    with col3:
        weight = criterion_data.get("weight", 1.0)
        weighted = criterion_data.get("weighted_score", score * weight)
        st.metric("Ağırlıklı Puan", f"{weighted:.1f}")

    # ESR Comment
    st.markdown("#### 📋 ESR Yorumu")
    st.markdown(
        f'<div style="background: #f8f9fa; padding: 1rem; border-radius: 8px; border-left: 4px solid #667eea; font-size: 0.95rem;">'
        f'{criterion_data.get("esr_comment", "N/A")}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Strengths & Weaknesses
    col_s, col_w = st.columns(2)
    with col_s:
        st.markdown("##### ✅ Güçlü Yönler")
        for s in criterion_data.get("strengths", []):
            st.markdown(f"- {s}")
        if not criterion_data.get("strengths"):
            st.markdown("_Belirgin güçlü yön tespit edilemedi._")

    with col_w:
        st.markdown("##### ❌ Zayıf Yönler")
        for w in criterion_data.get("weaknesses", []):
            st.markdown(f"- {w}")
        if not criterion_data.get("weaknesses"):
            st.markdown("_Belirgin zayıf yön tespit edilemedi._")

    # Weakness categories
    categories = criterion_data.get("weakness_categories", [])
    if categories:
        st.markdown("**🏷️ Zayıflık Kategorileri:** " + " · ".join(
            f"`{WEAKNESS_TAXONOMY.get(c, {}).get('label', c)}`" for c in categories
        ))

    # Sub-signal assessments
    subs = criterion_data.get("sub_signal_assessments", [])
    if subs:
        with st.expander("📊 Alt Sinyal Değerlendirmesi"):
            for sa in subs:
                rating = sa.get("rating", "unknown")
                icon = {"strong": "🟢", "adequate": "🟡", "weak": "🟠", "missing": "🔴"}.get(rating, "⚪")
                st.markdown(f"{icon} **{sa.get('signal', 'N/A')}** — {rating}")
                if sa.get("comment"):
                    st.markdown(f"  _{sa['comment']}_")
                if sa.get("evidence"):
                    st.markdown(f"  > Kanıt: \"{sa['evidence'][:200]}\"")

    # Alternative reading
    alt = criterion_data.get("alternative_reading", "")
    if alt:
        with st.expander("🔄 Alternatif Okuma (farklı bir hakem nasıl puanlayabilir?)"):
            st.markdown(alt)

    # Coaching
    if show_coaching and coaching_data:
        st.markdown("---")
        st.markdown("#### 🎯 Koçluk Önerileri")

        improvements = coaching_data.get("improvements", [])
        if improvements:
            for imp in improvements:
                with st.expander(
                    f"🔧 Öncelik {imp.get('priority', '?')}: {imp.get('title', 'N/A')} "
                    f"(tahmini etki: {imp.get('expected_score_gain', '?')})"
                ):
                    st.markdown(f"**Problem:** {imp.get('problem', 'N/A')}")
                    st.markdown(f"**Etki:** {imp.get('impact', 'N/A')}")
                    st.markdown(f"**Çözüm:** {imp.get('solution', 'N/A')}")

        summary = coaching_data.get("summary", "")
        if summary:
            st.markdown(f"**Genel Öneri:** {summary}")


def render_overall_results(results: Dict):
    """Render overall evaluation summary."""
    st.markdown("## 📊 Genel Değerlendirme Özeti")

    config = ACTION_TYPE_CONFIGS[ActionType(results["action_type"])]

    # Main metrics
    col1, col2, col3, col4 = st.columns(4)

    total_w = results["total_weighted"]
    total_max = results["total_max"]
    threshold = results["total_threshold"]
    met = results["total_threshold_met"]

    with col1:
        st.metric(
            "Toplam Ağırlıklı Puan",
            f"{total_w:.1f} / {total_max}",
            delta=f"{total_w - threshold:+.1f} eşikten" if met else f"{total_w - threshold:.1f} eşikten",
            delta_color="normal" if met else "inverse",
        )
    with col2:
        prob = results.get("funding_probability", "unknown")
        prob_labels = {
            "high": "🟢 Yüksek",
            "medium": "🟡 Orta",
            "low": "🟠 Düşük",
            "very_low": "🔴 Çok Düşük",
        }
        st.metric("Fonlanma Olasılığı", prob_labels.get(prob, prob))
    with col3:
        criteria_met = sum(1 for c in results["criteria"] if c.get("threshold_met", False))
        total_criteria = len(results["criteria"])
        st.metric("Kriter Eşikleri", f"{criteria_met}/{total_criteria} geçti")
    with col4:
        cross_issues = len(results.get("cross_cutting_issues", []))
        st.metric("Sistemik Sorun", f"{cross_issues} tespit")

    st.markdown("---")

    # Score table
    st.markdown("### Kriter Bazında Puanlar")

    score_cols = st.columns(len(results["criteria"]))
    for i, crit in enumerate(results["criteria"]):
        with score_cols[i]:
            render_score_gauge(
                crit["score"],
                crit["max_score"],
                crit["threshold"],
                crit.get("criterion", f"Kriter {i+1}"),
            )

    # Cross-cutting issues
    cross = results.get("cross_cutting_issues", [])
    if cross:
        st.markdown("### ⚠️ Kriterler Arası Sistemik Sorunlar")
        for issue in cross:
            st.warning(issue)


def render_deidentification_results(proposal: ParsedProposal):
    """Render de-identification scan results."""
    signals = scan_for_identity_signals(
        text=proposal.full_text,
        partner_names=proposal.partner_names,
        person_names=proposal.person_names,
    )
    report = generate_deidentification_report(signals)

    with st.expander(
        f"🔒 Kör Değerlendirme Uyumluluk Taraması ({len(signals)} sinyal)",
        expanded=len(signals) > 0,
    ):
        st.markdown(report)


def render_document_overview(proposal: ParsedProposal):
    """Render document parsing overview."""
    with st.expander("📄 Belge Analizi Özeti"):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Toplam Sayfa", proposal.total_pages)
        with col2:
            st.metric("Toplam Kelime", f"{proposal.total_words:,}")
        with col3:
            st.metric("Tespit Edilen Bölüm", len(proposal.sections))

        if proposal.acronym:
            st.markdown(f"**Proje Kısaltması**: {proposal.acronym}")

        st.markdown("**Tespit edilen bölümler:**")
        for sec_type, sec_data in proposal.sections.items():
            st.markdown(f"- **{sec_type.value}**: {sec_data.word_count} kelime")

        if proposal.trl_mentions:
            st.markdown(f"**TRL referansları**: {len(proposal.trl_mentions)} adet")
            for trl in proposal.trl_mentions[:3]:
                st.markdown(f"  - {trl}")

        if proposal.kpi_mentions:
            st.markdown(f"**KPI/Gösterge referansları**: {len(proposal.kpi_mentions)} adet")

        if proposal.warnings:
            st.markdown("**⚠️ Uyarılar:**")
            for w in proposal.warnings:
                st.warning(w)


# ═══════════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════════
def main():
    render_header()
    settings = render_sidebar()

    # File upload
    st.markdown("## 📤 Teklif Yükleme")
    uploaded_file = st.file_uploader(
        "Horizon Europe teklifinizi yükleyin (Part B — PDF veya DOCX)",
        type=["pdf", "docx", "doc"],
        help="Resmî şablona uygun Part B dokümanınızı yükleyin. Sistem bölümleri otomatik tespit edecektir.",
    )

    if uploaded_file is None:
        # Landing content
        st.markdown("---")
        st.markdown("""
        ### 🎯 GrantMirror-AI Ne Yapar?

        | Özellik | Açıklama |
        |---------|----------|
        | 📋 **ESR Simülasyonu** | Gerçek hakem formatında kriter bazlı değerlendirme raporu üretir |
        | 🔍 **Uygunluk Kontrolü** | Sayfa limiti, konsorsiyum, zorunlu bölümler ve kör değerlendirme uyumunu denetler |
        | 🎯 **Koçluk Modu** | Her zayıflık için somut, önceliklendirilmiş düzeltme önerileri sunar |
        | 📊 **Güven Aralığı** | Tek puan yerine puan aralığı + uzlaşma riski üretir |
        | 🔒 **Kimlik Taraması** | Kör değerlendirme çağrıları için kimlik ifşa eden bilgileri tespit eder |
        | 🏷️ **Zayıflık Taksonomisi** | ESR analizlerinden türetilen 12 zayıflık kategorisini otomatik sınıflar |

        ### 📚 Desteklenen Aksiyon Türleri
        - **Pillar II**: RIA, IA, CSA (ortak çağrılar)
        - **MSCA**: Doctoral Networks
        - **EIC**: Pathfinder Open, Accelerator
        - **ERC**: Starting Grant

        ### ⚙️ Nasıl Çalışır?
        1. Teklifinizi yükleyin (PDF/DOCX)
        2. Aksiyon türünü seçin
        3. Opsiyonel olarak çağrı metnini ekleyin
        4. Değerlendirmeyi başlatın
        5. ESR simülasyonu + koçluk raporunu indirin

        ---
        <p style="text-align: center; color: #888; font-size: 0.85rem;">
            ⚠️ Bu araç resmî EC hakem değerlendirmesinin yerini almaz.<br>
            Başvuru kalitesini artırmaya yönelik bir ön-tarama ve hazırlık aracıdır.
        </p>
        """, unsafe_allow_html=True)
        return

    # ── File uploaded — process ──────────────────────────
    file_bytes = uploaded_file.read()
    filename = uploaded_file.name

    # Step 1: Parse
    with st.spinner("📄 Belge ayrıştırılıyor..."):
        try:
            proposal = parse_proposal(file_bytes, filename)
        except Exception as e:
            st.error(f"❌ Belge ayrıştırma hatası: {str(e)}")
            return

    render_document_overview(proposal)

    # Step 2: Eligibility
    with st.spinner("✅ Uygunluk kontrolleri çalıştırılıyor..."):
        eligibility = run_eligibility_checks(
            proposal,
            settings["action_type"],
            stage="full",
        )

    render_eligibility_results(eligibility)

    # Step 3: De-identification (if requested)
    if settings["run_deidentification"]:
        render_deidentification_results(proposal)

    # Step 4: Evaluation trigger
    st.markdown("---")
    st.markdown("## 🚀 Değerlendirme")

    col_start, col_info = st.columns([1, 2])
    with col_start:
        start_eval = st.button(
            "🔬 Değerlendirmeyi Başlat",
            type="primary",
            use_container_width=True,
        )
    with col_info:
        config = ACTION_TYPE_CONFIGS[settings["action_type"]]
        n_criteria = len(config.criteria)
        st.info(
            f"📊 {settings['action_type'].value} için {n_criteria} kriter değerlendirilecek. "
            f"Tahmini süre: {n_criteria * 30}-{n_criteria * 60} saniye."
        )

    if not start_eval:
        return

    # ── Run evaluation ───────────────────────────────────
    client = get_llm_client()
    kb = HorizonKnowledgeBase()
    evaluator = GrantMirrorEvaluator(client, kb)

    progress_bar = st.progress(0.0)
    status_text = st.empty()

    def progress_callback(msg: str):
        status_text.markdown(f"⏳ {msg}")

    with st.spinner("🔬 Değerlendirme yapılıyor..."):
        n_steps = len(config.criteria) * 2  # eval + coaching per criterion
        current_step = [0]

        original_eval = evaluator.evaluate_criterion

        def tracked_eval(proposal, crit_config, action_type, call_context="", progress_callback=None):
            result = original_eval(proposal, crit_config, action_type, call_context, progress_callback)
            current_step[0] += 1
            progress_bar.progress(min(current_step[0] / n_steps, 1.0))
            return result

        evaluator.evaluate_criterion = tracked_eval

        original_coach = evaluator.generate_coaching

        def tracked_coach(crit_config, eval_result, proposal):
            result = original_coach(crit_config, eval_result, proposal)
            current_step[0] += 1
            progress_bar.progress(min(current_step[0] / n_steps, 1.0))
            return result

        evaluator.generate_coaching = tracked_coach

        results = evaluator.full_evaluation(
            proposal=proposal,
            action_type=settings["action_type"],
            call_context=settings["call_context"],
            progress_callback=progress_callback,
        )

    progress_bar.progress(1.0)
    status_text.markdown("✅ Değerlendirme tamamlandı!")
    time.sleep(0.5)
    status_text.empty()
    progress_bar.empty()

    # ── Display results ──────────────────────────────────
    st.markdown("---")

    # Store in session
    st.session_state["results"] = results
    st.session_state["proposal"] = proposal
    st.session_state["eligibility"] = eligibility

    # Overall summary
    render_overall_results(results)

    st.markdown("---")

    # Per-criterion details
    st.markdown("## 📝 Kriter Bazında Detaylı Değerlendirme")

    show_coaching = settings["eval_mode"] in ("both", "coaching_only")
    show_esr = settings["eval_mode"] in ("both", "esr_only")

    tab_labels = [c.get("criterion", f"Kriter {i+1}") for i, c in enumerate(results["criteria"])]
    tabs = st.tabs(tab_labels)

    for i, tab in enumerate(tabs):
        with tab:
            crit_data = results["criteria"][i]
            coach_data = results["coaching"][i] if i < len(results["coaching"]) else {}
            render_criterion_result(crit_data, coach_data, show_coaching)

    # ── Export ───────────────────────────────────────────
    st.markdown("---")
    st.markdown("## 📥 Raporları İndir")

    col_dl1, col_dl2, col_dl3 = st.columns(3)

    # JSON export
    with col_dl1:
        json_export = json.dumps(results, indent=2, ensure_ascii=False)
        st.download_button(
            label="📊 JSON (Ham Veri)",
            data=json_export,
            file_name=f"grantmirror_{filename}_results.json",
            mime="application/json",
            use_container_width=True,
        )

    # ESR-style markdown export
    with col_dl2:
        esr_md = _build_esr_markdown(results, eligibility)
        st.download_button(
            label="📋 ESR Raporu (Markdown)",
            data=esr_md,
            file_name=f"grantmirror_{filename}_esr.md",
            mime="text/markdown",
            use_container_width=True,
        )

    # Coaching markdown export
    with col_dl3:
        coach_md = _build_coaching_markdown(results)
        st.download_button(
            label="🎯 Koçluk Raporu (Markdown)",
            data=coach_md,
            file_name=f"grantmirror_{filename}_coaching.md",
            mime="text/markdown",
            use_container_width=True,
        )


# ═══════════════════════════════════════════════════════════
# EXPORT HELPERS
# ═══════════════════════════════════════════════════════════

def _build_esr_markdown(results: Dict, eligibility: EligibilityReport) -> str:
    """Build ESR-style markdown report for download."""
    lines = [
        "# Evaluation Summary Report (ESR Simulation)",
        f"**Action Type**: {results['action_type']}",
        f"**Generated by**: GrantMirror-AI (Pre-screening tool — not official evaluation)",
        "",
        "---",
        "",
    ]

    # Eligibility
    lines.append("## Admissibility & Eligibility")
    for check in eligibility.results:
        lines.append(f"- {check.status.value}: {check.check_name} — {check.message}")
    lines.append("")

    # Per-criterion
    for crit in results["criteria"]:
        name = crit.get("criterion", "N/A")
        score = crit.get("score", 0)
        threshold = crit.get("threshold", 3.0)
        max_s = crit.get("max_score", 5.0)

        lines.append(f"## {name}")
        lines.append(f"**Score: {score}/{max_s}** (Threshold: {threshold})")
        lines.append(f"**Confidence Range**: {crit.get('confidence_low', '?')} – {crit.get('confidence_high', '?')}")
        lines.append(f"**Consensus Risk**: {crit.get('consensus_risk', 'N/A')}")
        lines.append("")
        lines.append(crit.get("esr_comment", "N/A"))
        lines.append("")

        if crit.get("strengths"):
            lines.append("**Strengths:**")
            for s in crit["strengths"]:
                lines.append(f"- {s}")
            lines.append("")

        if crit.get("weaknesses"):
            lines.append("**Weaknesses:**")
            for w in crit["weaknesses"]:
                lines.append(f"- {w}")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Overall
    lines.append("## Overall Assessment")
    lines.append(f"**Total Weighted Score**: {results['total_weighted']}/{results['total_max']}")
    lines.append(f"**Threshold**: {results['total_threshold']} — {'Met ✅' if results['total_threshold_met'] else 'Not met ❌'}")
    lines.append(f"**Funding Probability**: {results.get('funding_probability', 'N/A')}")
    lines.append("")

    if results.get("cross_cutting_issues"):
        lines.append("## Cross-cutting Issues")
        for issue in results["cross_cutting_issues"]:
            lines.append(f"- {issue}")

    lines.append("")
    lines.append("---")
    lines.append("*This is an AI-generated simulation and does not replace official EC evaluation.*")

    return "\n".join(lines)


def _build_coaching_markdown(results: Dict) -> str:
    """Build coaching report markdown for download."""
    lines = [
        "# Proposal Improvement Report (Coaching)",
        f"**Action Type**: {results['action_type']}",
        f"**Current Score**: {results['total_weighted']}/{results['total_max']}",
        f"**Threshold Status**: {'Above ✅' if results['total_threshold_met'] else 'Below ❌'}",
        "",
        "---",
        "",
    ]

    for coaching in results.get("coaching", []):
        name = coaching.get("criterion", "N/A")
        lines.append(f"## {name}")
        lines.append("")

        for imp in coaching.get("improvements", []):
            lines.append(f"### Priority {imp.get('priority', '?')}: {imp.get('title', 'N/A')}")
            lines.append(f"**Problem**: {imp.get('problem', 'N/A')}")
            lines.append(f"**Impact on Score**: {imp.get('impact', 'N/A')}")
            lines.append(f"**Solution**: {imp.get('solution', 'N/A')}")
            lines.append(f"**Expected Gain**: {imp.get('expected_score_gain', 'N/A')}")
            lines.append("")

        summary = coaching.get("summary", "")
        if summary:
            lines.append(f"**Overall**: {summary}")
            lines.append("")

        lines.append("---")
        lines.append("")

    if results.get("cross_cutting_issues"):
        lines.append("## Systemic Issues")
        for issue in results["cross_cutting_issues"]:
            lines.append(f"- {issue}")

    lines.append("")
    lines.append("*Generated by GrantMirror-AI — use as guidance alongside expert consultation.*")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    main()
