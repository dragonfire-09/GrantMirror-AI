import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from document_parser import extract_text
from evaluator import evaluate_proposal


st.set_page_config(
    page_title="Horizon Evaluator AI",
    page_icon="🧠",
    layout="wide"
)


st.title("🧠 Horizon Evaluator AI")
st.caption("AI-based Horizon Europe Proposal Pre-Evaluation Platform")


with st.sidebar:
    st.header("Call Information")

    call_id = st.text_input("Call ID", placeholder="HORIZON-CL6-2025-...")
    topic_id = st.text_input("Topic ID", placeholder="HORIZON-CL6-2025-...")
    action_type = st.selectbox(
        "Type of Action",
        ["RIA", "IA", "CSA", "MSCA", "EIC", "ERC", "Other"]
    )

    expected_outcomes = st.text_area(
        "Expected Outcomes",
        placeholder="Paste the expected outcomes from the call text..."
    )

    scope = st.text_area(
        "Scope",
        placeholder="Paste the scope section from the call text..."
    )

    st.divider()

    uploaded_file = st.file_uploader(
        "Upload Proposal",
        type=["pdf", "docx"]
    )


if uploaded_file:
    st.success(f"Uploaded file: {uploaded_file.name}")

    with st.spinner("Extracting proposal text..."):
        proposal_text = extract_text(uploaded_file)

    with st.expander("Preview extracted text"):
        st.text_area("Extracted Text", proposal_text[:5000], height=300)

    call_info = f"""
Call ID: {call_id}
Topic ID: {topic_id}
Type of Action: {action_type}

Expected Outcomes:
{expected_outcomes}

Scope:
{scope}
"""

    if st.button("🚀 Evaluate Proposal", type="primary"):
        with st.spinner("AI evaluator is reviewing the proposal..."):
            result = evaluate_proposal(proposal_text, call_info)

        if "error" in result:
            st.error(result["error"])
            st.text(result["raw_response"])
        else:
            st.subheader("Evaluation Dashboard")

            excellence_score = result["excellence"]["score"]
            impact_score = result["impact"]["score"]
            implementation_score = result["implementation"]["score"]
            total_score = result["total_score"]

            col1, col2, col3, col4 = st.columns(4)

            col1.metric("Excellence", f"{excellence_score}/5")
            col2.metric("Impact", f"{impact_score}/5")
            col3.metric("Implementation", f"{implementation_score}/5")
            col4.metric("Total Score", f"{total_score}/15")

            fig = go.Figure()

            fig.add_trace(go.Scatterpolar(
                r=[excellence_score, impact_score, implementation_score],
                theta=["Excellence", "Impact", "Implementation"],
                fill="toself",
                name="Proposal Score"
            ))

            fig.update_layout(
                polar=dict(
                    radialaxis=dict(
                        visible=True,
                        range=[0, 5]
                    )
                ),
                showlegend=False
            )

            st.plotly_chart(fig, use_container_width=True)

            st.warning(f"Threshold Risk: {result['threshold_risk']}")

            st.subheader("Likely ESR Summary")
            st.write(result["likely_esr_summary"])

            criteria = {
                "Excellence": result["excellence"],
                "Impact": result["impact"],
                "Implementation": result["implementation"],
            }

            for criterion_name, data in criteria.items():
                st.divider()
                st.header(criterion_name)

                st.subheader("Strengths")
                for item in data["strengths"]:
                    st.success(item)

                st.subheader("Weaknesses")
                for item in data["weaknesses"]:
                    st.error(item)

                st.subheader("Critical Evaluator Comments")
                for item in data["critical_comments"]:
                    st.warning(item)

                st.subheader("Recommendations")
                for item in data["recommendations"]:
                    st.info(item)

            st.divider()
            st.header("Priority Actions")

            for index, action in enumerate(result["priority_actions"], start=1):
                st.write(f"{index}. {action}")

            report_df = pd.DataFrame({
                "Criterion": ["Excellence", "Impact", "Implementation", "Total"],
                "Score": [
                    excellence_score,
                    impact_score,
                    implementation_score,
                    total_score
                ],
                "Maximum": [5, 5, 5, 15]
            })

            csv = report_df.to_csv(index=False).encode("utf-8")

            st.download_button(
                label="Download Score Summary CSV",
                data=csv,
                file_name="horizon_evaluation_summary.csv",
                mime="text/csv"
            )

else:
    st.info("Upload a Horizon Europe proposal PDF or DOCX file to start.")
