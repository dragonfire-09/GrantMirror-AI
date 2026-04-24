import streamlit as st


def inject_modern_css():
    st.markdown(
        """
        <style>
        /* ─────────────────────────────
           GLOBAL
        ───────────────────────────── */

        .main {
            background: #f7f8fb;
        }

        h1, h2, h3 {
            color: #101828;
            letter-spacing: -0.03em;
        }

        section.main > div {
            max-width: 1280px;
        }

        /* ─────────────────────────────
           SIDEBAR
        ───────────────────────────── */

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #27245f 0%, #343092 100%) !important;
            border-right: 1px solid rgba(255, 255, 255, 0.12) !important;
        }

        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] div {
            color: #f8fafc !important;
        }

        [data-testid="stSidebar"] hr {
            border-color: rgba(255,255,255,0.16) !important;
        }

        /* ─────────────────────────────
           SIDEBAR RADIO
        ───────────────────────────── */

        [data-testid="stSidebar"] [role="radiogroup"] label {
            background: rgba(255,255,255,0.06) !important;
            border-radius: 12px !important;
            padding: 0.35rem 0.45rem !important;
            margin-bottom: 0.25rem !important;
        }

        [data-testid="stSidebar"] [role="radiogroup"] label:hover {
            background: rgba(255,255,255,0.12) !important;
        }

        /* ─────────────────────────────
           SELECTBOX FIX
        ───────────────────────────── */

        [data-testid="stSidebar"] div[data-baseweb="select"] > div {
            background: #ffffff !important;
            border-radius: 12px !important;
            border: 1px solid rgba(255,255,255,0.22) !important;
            min-height: 48px !important;
            box-shadow: 0 6px 18px rgba(15,23,42,0.14) !important;
        }

        [data-testid="stSidebar"] div[data-baseweb="select"] *,
        [data-testid="stSidebar"] div[data-baseweb="select"] div,
        [data-testid="stSidebar"] div[data-baseweb="select"] span,
        [data-testid="stSidebar"] div[data-baseweb="select"] input {
            color: #101828 !important;
            -webkit-text-fill-color: #101828 !important;
            font-weight: 650 !important;
        }

        [data-testid="stSidebar"] div[data-baseweb="select"] svg {
            fill: #101828 !important;
            color: #101828 !important;
        }

        div[data-baseweb="popover"] {
            background: #ffffff !important;
            border-radius: 14px !important;
            box-shadow: 0 18px 38px rgba(15,23,42,0.18) !important;
        }

        div[data-baseweb="popover"] *,
        div[data-baseweb="popover"] li,
        div[data-baseweb="popover"] div,
        div[data-baseweb="popover"] span {
            color: #101828 !important;
            -webkit-text-fill-color: #101828 !important;
            background-color: #ffffff !important;
            font-weight: 600 !important;
        }

        div[data-baseweb="popover"] li:hover,
        div[data-baseweb="popover"] div:hover {
            background-color: #eef2ff !important;
        }

        /* ─────────────────────────────
           SIDEBAR INPUTS / TEXTAREA
        ───────────────────────────── */

        [data-testid="stSidebar"] input,
        [data-testid="stSidebar"] textarea {
            background: #ffffff !important;
            color: #101828 !important;
            -webkit-text-fill-color: #101828 !important;
            border-radius: 12px !important;
        }

        [data-testid="stSidebar"] textarea::placeholder,
        [data-testid="stSidebar"] input::placeholder {
            color: #667085 !important;
            -webkit-text-fill-color: #667085 !important;
        }

        /* ─────────────────────────────
           CARDS / HERO
        ───────────────────────────── */

        .gm-hero {
            background: linear-gradient(135deg, #101828 0%, #344054 45%, #175cd3 100%);
            padding: 2.4rem;
            border-radius: 24px;
            color: white;
            margin-bottom: 2rem;
            box-shadow: 0 20px 45px rgba(16,24,40,0.18);
        }

        .gm-hero h1 {
            color: white !important;
            font-size: 2.6rem;
            margin-bottom: 0.3rem;
        }

        .gm-hero p {
            color: #d0d5dd !important;
            font-size: 1rem;
        }

        .gm-card {
            background: #ffffff;
            border: 1px solid #eaecf0;
            border-radius: 18px;
            padding: 1.2rem;
            box-shadow: 0 8px 24px rgba(16,24,40,0.06);
            margin-bottom: 1rem;
        }

        .gm-call-card {
            background: #ffffff;
            border: 1px solid #eaecf0;
            border-radius: 16px;
            padding: 1rem 1.2rem;
            margin-bottom: 0.8rem;
            box-shadow: 0 6px 18px rgba(16,24,40,0.05);
        }

        .gm-badge-open {
            background: #dcfae6;
            color: #067647 !important;
            padding: 0.25rem 0.55rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 800;
        }

        .gm-badge-forthcoming {
            background: #fef0c7;
            color: #b54708 !important;
            padding: 0.25rem 0.55rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 800;
        }

        .gm-badge-closed {
            background: #fee4e2;
            color: #b42318 !important;
            padding: 0.25rem 0.55rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 800;
        }
        /* ===== FEATURE GRID ===== */

.gm-feature-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 20px;
    margin-top: 1.5rem;
}

/* ===== FEATURE CARD ===== */

.gm-feature-card {
    background: rgba(255, 255, 255, 0.92);
    border: 1px solid #eaecf0;
    border-radius: 24px;
    padding: 1.3rem;
    min-height: 190px;
    box-shadow: 0 12px 30px rgba(16,24,40,0.06);
    transition: all 0.25s ease;
    backdrop-filter: blur(6px);
}

.gm-feature-card:hover {
    transform: translateY(-6px) scale(1.01);
    box-shadow: 0 22px 48px rgba(16,24,40,0.15);
    border-color: #84adff;
}

/* ===== TOP AREA ===== */

.gm-feature-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
}

/* ===== ICON ===== */

.gm-feature-icon {
    width: 52px;
    height: 52px;
    border-radius: 18px;
    background: linear-gradient(135deg, #eef4ff, #dbeafe);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.6rem;
    box-shadow: inset 0 1px 2px rgba(255,255,255,0.5);
}

/* ===== TAG ===== */

.gm-feature-tag {
    font-size: 0.7rem;
    font-weight: 800;
    color: #175cd3;
    background: #eff4ff;
    padding: 0.3rem 0.65rem;
    border-radius: 999px;
    letter-spacing: 0.03em;
}

/* ===== TITLE ===== */

.gm-feature-title {
    font-size: 1.1rem;
    font-weight: 900;
    color: #101828;
    margin-bottom: 0.4rem;
}

/* ===== DESCRIPTION ===== */

.gm-feature-desc {
    font-size: 0.9rem;
    color: #667085;
    line-height: 1.5;
}

/* ===== RESPONSIVE ===== */

@media (max-width: 1100px) {
    .gm-feature-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 700px) {
    .gm-feature-grid {
        grid-template-columns: 1fr;
    }
}

        /* ─────────────────────────────
           BUTTONS
        ───────────────────────────── */

        .stButton > button,
        .stDownloadButton > button {
            border-radius: 12px !important;
            font-weight: 750 !important;
            border: 1px solid #d0d5dd !important;
            box-shadow: 0 4px 12px rgba(16,24,40,0.05) !important;
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover {
            border-color: #175cd3 !important;
            color: #175cd3 !important;
        }

        /* ─────────────────────────────
           FILE UPLOADER
        ───────────────────────────── */

        [data-testid="stFileUploader"] {
            border: 1.5px dashed #d0d5dd;
            border-radius: 20px;
            padding: 1.2rem;
            background: #ffffff;
        }

        /* ─────────────────────────────
           METRICS
        ───────────────────────────── */

        [data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #eaecf0;
            border-radius: 16px;
            padding: 1rem;
            box-shadow: 0 6px 18px rgba(16,24,40,0.04);
        }

        [data-testid="stMetricValue"] {
            color: #101828;
            font-weight: 800;
        }

        /* ─────────────────────────────
           EXPANDERS
        ───────────────────────────── */

        div[data-testid="stExpander"] {
            border-radius: 14px !important;
            border: 1px solid rgba(255,255,255,0.15) !important;
            overflow: hidden;
        }

        [data-testid="stSidebar"] div[data-testid="stExpander"] {
            background: rgba(255,255,255,0.06) !important;
        }

        /* ─────────────────────────────
           SMALL FIXES
        ───────────────────────────── */

        a {
            color: #175cd3 !important;
            font-weight: 650;
            text-decoration: none !important;
        }

        a:hover {
            text-decoration: underline !important;
        }

        code {
            border-radius: 8px !important;
        }

        </style>
        """,
        unsafe_allow_html=True,
    )


def render_modern_header():
    st.markdown(
        """
        <div class="gm-hero">
            <h1>🔬 GrantMirror-AI</h1>
            <p>Horizon Europe Proposal Pre-Screening · ESR Simulator · Call Matching · Funding Probability</p>
            <p style="font-size:0.9rem;">
                Canlı çağrı verisi · RAG bilgi motoru · Hakem simülasyonu · Koçluk raporu · Excel export
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
