import streamlit as st


def inject_modern_css():
    st.markdown(
        """
        <style>
        .main {
            background: #f7f8fb;
        }

        h1, h2, h3 {
            color: #101828;
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #2b2d6e 0%, #1f2154 100%);
        }

        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span {
            color: #f8fafc !important;
        }

        [data-testid="stSidebar"] [data-baseweb="select"] > div {
            background-color: #ffffff !important;
            color: #101828 !important;
            border-radius: 12px !important;
            border: none !important;
        }

        [data-testid="stSidebar"] [data-baseweb="select"] span {
            color: #101828 !important;
            font-weight: 600 !important;
        }

        [data-testid="stSidebar"] [data-baseweb="select"] svg {
            fill: #101828 !important;
            color: #101828 !important;
        }

        div[data-baseweb="popover"] {
            background-color: #ffffff !important;
            border-radius: 12px !important;
        }

        div[data-baseweb="popover"] li,
        div[data-baseweb="popover"] div {
            color: #101828 !important;
            font-weight: 500 !important;
        }

        div[data-baseweb="popover"] li:hover {
            background-color: #eef2ff !important;
        }

        .gm-hero {
            background: linear-gradient(135deg, #101828 0%, #344054 45%, #175cd3 100%);
            padding: 2.4rem;
            border-radius: 24px;
            color: white;
            margin-bottom: 2rem;
            box-shadow: 0 20px 45px rgba(16,24,40,0.18);
        }

        .gm-hero h1 {
            color: white;
            font-size: 2.6rem;
            margin-bottom: 0.3rem;
        }

        .gm-hero p {
            color: #d0d5dd;
            font-size: 1rem;
        }

        .gm-card {
            background: white;
            border: 1px solid #eaecf0;
            border-radius: 18px;
            padding: 1.2rem;
            box-shadow: 0 8px 24px rgba(16,24,40,0.06);
            margin-bottom: 1rem;
        }

        .gm-call-card {
            background: white;
            border: 1px solid #eaecf0;
            border-radius: 16px;
            padding: 1rem 1.2rem;
            margin-bottom: 0.8rem;
            box-shadow: 0 6px 18px rgba(16,24,40,0.05);
        }

        .gm-badge-open {
            background: #dcfae6;
            color: #067647;
            padding: 0.25rem 0.55rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 700;
        }

        .gm-badge-forthcoming {
            background: #fef0c7;
            color: #b54708;
            padding: 0.25rem 0.55rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 700;
        }

        .gm-badge-closed {
            background: #fee4e2;
            color: #b42318;
            padding: 0.25rem 0.55rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 700;
        }

        .stButton > button {
            border-radius: 12px !important;
            font-weight: 700 !important;
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
