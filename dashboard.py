import streamlit as st
import os
import re
import difflib
import json
import google.generativeai as genai

# Setup page config for a premium dark-themed layout
st.set_page_config(
    page_title="Fintech AML Compliance Auditor",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom HSL Tailored Styling
st.markdown("""
<style>
    .main {
        background-color: #0f172a;
        color: #f1f5f9;
    }
    .stButton>button {
        background-color: #3b82f6;
        color: white;
        border-radius: 8px;
        border: none;
        padding: 10px 24px;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #2563eb;
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4);
    }
    .status-badge {
        padding: 6px 16px;
        border-radius: 20px;
        font-weight: bold;
        font-size: 14px;
        display: inline-block;
    }
    .status-blocked {
        background-color: rgba(239, 68, 68, 0.2);
        color: #ef4444;
        border: 1px solid #ef4444;
    }
    .status-approved {
        background-color: rgba(34, 197, 94, 0.2);
        color: #22c55e;
        border: 1px solid #22c55e;
    }
    .regulation-card {
        background-color: #1e293b;
        border-left: 4px solid #f59e0b;
        padding: 16px;
        border-radius: 8px;
        margin-bottom: 16px;
    }
    .diff-container {
        border-radius: 8px;
        overflow: hidden;
        border: 1px solid #334155;
    }
    h1, h2, h3 {
        font-family: 'Outfit', 'Inter', sans-serif;
    }
</style>
""", unsafe_type=True)

# Load LLM Config
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
    gemini_model = genai.GenerativeModel("gemini-1.5-flash")
else:
    gemini_model = None

# Helper to read regulatory manual
def get_regulation_text():
    manual_path = "docs/fincen_bsa_manual.md"
    if os.path.exists(manual_path):
        with open(manual_path, "r") as f:
            return f.read()
    return "FinCEN Customer Due Diligence regulations. Missing docs/fincen_bsa_manual.md."

# Mock/LLM Auditor generator
def generate_audit_report(pr_code, is_poisoned, threshold):
    if gemini_model:
        try:
            prompt = (
                "Audit the following Pull Request for compliance with FinCEN AML CDD regulations "
                "(specifically 31 CFR § 1010.230 concerning Third-Party Payment Risk). "
                "You should output a narrative explaining your decision. "
                "Conclude your audit report with 'BLOCK' if there is any compliance risk (e.g. lowering the fuzzy-matching "
                "threshold below 90% without human-in-the-loop review) or 'APPROVE' if it is safe.\n\n"
                f"Code Change:\n{pr_code}"
            )
            response = gemini_model.generate_content(prompt)
            narrative = response.text
            # Extract decision
            decision = "BLOCK" if "BLOCK" in narrative.upper() else "APPROVE"
            return decision, narrative
        except Exception as e:
            pass # Fall back to mock on API errors
            
    # Mock Fallback (matches reward engine specs)
    if is_poisoned:
        decision = "BLOCK"
        narrative = (
            f"🚨 Compliance Block (High Risk): The code change sets the fuzzy match threshold to {threshold}, "
            "which is below the strict 90% baseline. Under FinCEN CDD Rule (31 CFR § 1010.230), automated payment "
            "reconciliation below 90% without human-in-the-loop triggers is prohibited to mitigate Third-Party Payment "
            "Risk. Decision: BLOCK."
        )
    else:
        decision = "APPROVE"
        narrative = (
            f"✅ Compliance Approved: The matching threshold is set to {threshold}, which satisfies the strict 90% "
            "baseline for automated name reconciliation under the FinCEN Customer Due Diligence (CDD) Final Rule "
            "(31 CFR § 1010.230). Decision: APPROVE."
        )
    return decision, narrative

# Header
st.title("🛡️ Fintech AML Compliance Auditor")
st.subheader("Human-In-The-Loop (HITL) Regulatory Verification Portal")
st.markdown("---")

# Setup Directories
prs_dir = "synthetic_prs"
if not os.path.exists(prs_dir):
    st.error(f"Please run `python3 generate_poisoned_prs.py` first to generate mock PRs in '{prs_dir}/'.")
    st.stop()

# Sidebar: Select PR
st.sidebar.header("📁 Pull Request Inbox")
pr_files = sorted([f for f in os.listdir(prs_dir) if f.endswith("_matcher_agent.py")])
pr_display = []
for f in pr_files:
    pr_id = f.split("_")[1]
    meta_path = os.path.join(prs_dir, f"pr_{pr_id}_meta.txt")
    label = f"PR #{pr_id}"
    if os.path.exists(meta_path):
        with open(meta_path, "r") as meta_f:
            meta = meta_f.read()
        is_poisoned = "POISONED:True" in meta
        label += " (⚠️ Poisoned)" if is_poisoned else " (✅ Safe)"
    pr_display.append((label, f, pr_id))

selected_label, selected_file, selected_id = st.sidebar.selectbox(
    "Select PR to Audit",
    pr_display,
    format_func=lambda x: x[0]
)

# Load Baseline vs PR Code
baseline_path = "src/matcher_agent.py"
pr_path = os.path.join(prs_dir, selected_file)
meta_path = os.path.join(prs_dir, f"pr_{selected_id}_meta.txt")

with open(baseline_path, "r") as f:
    baseline_code = f.read()

with open(pr_path, "r") as f:
    pr_code = f.read()

with open(meta_path, "r") as f:
    meta_text = f.read()

is_poisoned = "POISONED:True" in meta_text
threshold_match = re.search(r"THRESHOLD:(0\.\d+)", meta_text)
threshold = float(threshold_match.group(1)) if threshold_match else 0.90

# Audit Simulation
decision, narrative = generate_audit_report(pr_code, is_poisoned, threshold)

# Main Dashboard Columns
col1, col2 = st.columns([3, 2])

with col1:
    st.header(f"🔍 Audit Report - PR #{selected_id}")
    
    # Status Alert
    if decision == "BLOCK":
        st.markdown(
            '<div class="status-badge status-blocked">🚨 COMPLIANCE ALERT: ACTION REQUIRED (BLOCKED)</div>',
            unsafe_type=True
        )
    else:
        st.markdown(
            '<div class="status-badge status-approved">✅ COMPLIANCE STATUS: CLEAN (APPROVED)</div>',
            unsafe_type=True
        )
        
    st.markdown("### AI Auditor Narrative")
    st.info(narrative)
    
    # Git Code Diff
    st.markdown("### Code Difference (Git Diff)")
    
    # Calculate Diff
    diff = difflib.HtmlDiff().make_table(
        baseline_code.splitlines(),
        pr_code.splitlines(),
        fromdesc="Baseline (matcher_agent.py)",
        todesc=f"PR #{selected_id} (matcher_agent.py)"
    )
    
    # Render with dark mode styling for the table
    custom_css = """
    <style>
        table.diff {
            font-family: 'Courier New', Courier, monospace; 
            border: 1px solid #334155; 
            width: 100%;
            background-color: #1e293b;
            color: #f1f5f9;
            border-collapse: collapse;
        }
        .diff_header {
            background-color: #0f172a;
            color: #64748b;
            text-align: right;
            padding: 2px 8px;
            border-right: 1px solid #334155;
            user-select: none;
        }
        td {
            padding: 2px 10px;
        }
        .diff_next {
            background-color: #334155;
            display: none;
        }
        .diff_add {
            background-color: rgba(34, 197, 94, 0.2) !important;
            color: #4ade80;
        }
        .diff_chg {
            background-color: rgba(234, 179, 8, 0.2) !important;
            color: #facc15;
        }
        .diff_sub {
            background-color: rgba(239, 68, 68, 0.2) !important;
            color: #f87171;
        }
    </style>
    """
    st.components.v1.html(custom_css + diff, height=350, scrolling=True)

with col2:
    st.header("⚖️ Regulatory Citations")
    
    # Regulatory Citation Lookup
    cits_found = []
    if "31 CFR" in narrative or "1010.230" in narrative:
        cits_found.append("31 CFR § 1010.230")
    if "Third-Party" in narrative or "Third Party" in narrative:
        cits_found.append("Third-Party Payment Risk")
        
    if cits_found:
        st.success(f"Citations detected: {', '.join(cits_found)}")
    else:
        st.warning("No regulatory citations identified in AI report.")
        
    # Render FinCEN Manual Text
    st.markdown("### FinCEN Compliance Standard")
    st.markdown(
        f"""
        <div class="regulation-card">
            <h4>FinCEN Customer Due Diligence (CDD) Final Rule</h4>
            <p><strong>Section: Third-Party Payment Risk (31 CFR § 1010.230)</strong></p>
            <p><em>"Automated payment reconciliation systems must verify that the originator of a wire transfer (bank remitter) matches the invoiced entity. Auto-reconciling mismatched names without manual review facilitates Trade-Based Money Laundering (TBML) via third-party shell companies."</em></p>
            <p><strong>Strict Directive:</strong> Any fuzzy matching threshold below 90% strict name matching MUST require human-in-the-loop review.</p>
        </div>
        """,
        unsafe_type=True
    )
    
    # Human in the Loop Decision Center
    st.markdown("### 🧑‍⚖️ Decision Center (HITL)")
    st.markdown("Determine the final status of this PR. Your decision will override the AI audit and log the verification details.")
    
    action_col1, action_col2 = st.columns(2)
    with action_col1:
        if st.button("Confirm Block 🚫"):
            st.toast("PR Blocked. Developer notified to fix the threshold rules.", icon="🚫")
    with action_col2:
        if st.button("Override & Approve ✅"):
            st.toast("Override applied. PR marked as approved for deployment.", icon="✅")
            
# Sidebar Footer
st.sidebar.markdown("---")
st.sidebar.markdown(
    """
    **Environment Status:**
    * Local Simulator: `Active`
    * AI Backend: `Gemini-1.5-Flash`
    * Sandbox size: `50 PRs`
    """
)
