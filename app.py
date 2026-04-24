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
st.caption("Multi-reviewer Horizon Europe proposal pre-evaluation platform")


with st.sidebar:
    st.header("Call Information")

    call_id = st.text_input(
        "Call ID",
        placeholder="Example: HORIZON-CL6-2025-..."
    )

    topic_id = st.text_input(
        "Topic ID",
        placeholder="Example: HORIZON-CL6-2025-..."
    )

    action_type = st.selectbox(
        "Type of Action",
        ["RIA", "IA", "CSA", "MSCA", "EIC", "ERC", "Other"]
    )

    expected_outcomes = st.text_area(
        "Expected Outcomes",
        placeholder="Paste expected outcomes from the call text...",
        height=140
    )

    scope = st.text_area(
        "Scope",
        placeholder="Paste scope section from the call text...",
        height=180
    )

    st.divider()

    uploaded_file = st.file_uploader(
        "Upload Proposal",
        type=["pdf", "docx"]
    )


if uploaded_file is None:
    st.info("Upload a Horizon Europe proposal PDF or DOCX file to start.")
    st.stop()


st.success(f"Uploaded file: {uploaded_file.name}")


try:
    with st.spinner("Extracting proposal text..."):
        proposal_text = extract_text(uploaded_file)

except Exception as e:
    st.error("Could not extract text from the uploaded file.")
    st.write(str(e))
    st.stop()


with st.expander("Preview extracted proposal text"):
    st.text_area(
        "Extracted Text",
        proposal_text[:7000],
        height=300
    )


call_info = f"""
Call ID: {call_id}
Topic ID: {topic_id}
Type of Action: {action_type}

Expected Outcomes:
{expected_outcomes}

Scope:
{scope}
"""


if st.button("🚀 Run Multi-Reviewer Evaluation", type="primary"):
    with st.spinner("Three AI evaluators are reviewing the proposal..."):
        result = evaluate_proposal(proposal_text, call_info)

    if "error" in result:
        st.error(result["error"])
        st.write(result.get("details", ""))
        st.stop()

    consensus = result["consensus"]
    reviews = result["reviews"]
    scores = consensus["consensus_scores"]

    st.divider()
    st.subheader("Consensus Evaluation Dashboard")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Excellence", f"{scores['excellence']}/5")
    col2.metric("Impact", f"{scores['impact']}/5")
    col3.metric("Implementation", f"{scores['implementation']}/5")
    col4.metric("Consensus Total", f"{scores['total']}/15")

    col5, col6, col7 = st.columns(3)

    col5.metric(
        "Funding Probability",
        f"{consensus['funding_probability']}%"
    )

    col6.metric(
        "Confidence",
        f"{consensus['confidence']['confidence_score']}%"
    )

    col7.metric(
        "Agreement Level",
        consensus["confidence"]["confidence_level"]
    )

    st.warning(consensus["threshold_risk"])

    fig = go.Figure()

    fig.add_trace(
        go.Scatterpolar(
            r=[
                scores["excellence"],
                scores["impact"],
                scores["implementation"],
            ],
            theta=[
                "Excellence",
                "Impact",
                "Implementation",
            ],
            fill="toself",
            name="Consensus Score",
        )
    )

    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 5],
            )
        ),
        showlegend=False,
    )

    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Reviewer Score Comparison")

    reviewer_df = pd.DataFrame(consensus["reviewer_scores"])
    st.dataframe(reviewer_df, use_container_width=True)

    st.subheader("Priority Improvement Actions")

    if consensus["priority_actions"]:
        for index, action in enumerate(consensus["priority_actions"], start=1):
            st.write(f"{index}. {action}")
    else:
        st.info("No priority actions returned.")

    st.divider()
    st.header("Detailed Evaluator Reports")

    for review in reviews:
        with st.expander(review["reviewer"], expanded=False):
            st.metric("Total Score", f"{review['total_score']}/15")

            for section in ["excellence", "impact", "implementation"]:
                section_data = review[section]

                st.subheader(section.capitalize())
                st.write(f"Score: {section_data['score']}/5")

                st.markdown("**Strengths**")
                strengths = section_data.get("strengths", [])
                if strengths:
                    for item in strengths:
                        st.success(item)
                else:
                    st.write("No strengths listed.")

                st.markdown("**Weaknesses**")
                weaknesses = section_data.get("weaknesses", [])
                if weaknesses:
                    for item in weaknesses:
                        st.error(item)
                else:
                    st.write("No weaknesses listed.")

                st.markdown("**Critical Comments**")
                critical_comments = section_data.get("critical_comments", [])
                if critical_comments:
                    for item in critical_comments:
                        st.warning(item)
                else:
                    st.write("No critical comments listed.")

                st.markdown("**Recommendations**")
                recommendations = section_data.get("recommendations", [])
                if recommendations:
                    for item in recommendations:
                        st.info(item)
                else:
                    st.write("No recommendations listed.")

            st.markdown("**Overall Comment**")
            st.write(review.get("overall_comment", ""))

            st.markdown("**Call Match Assessment**")
            call_match = review.get("call_match_assessment", {})
            st.write(f"Alignment Score: {call_match.get('alignment_score', 'N/A')}/5")
            st.write(f"In-Scope Risk: {call_match.get('in_scope_risk', 'N/A')}")

            missing_requirements = call_match.get("missing_call_requirements", [])
            if missing_requirements:
                st.markdown("Missing Call Requirements:")
                for item in missing_requirements:
                    st.warning(item)

    csv = reviewer_df.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="Download Reviewer Scores CSV",
        data=csv,
        file_name="multi_reviewer_scores.csv",
        mime="text/csv",
    )
