import streamlit as st
import pandas as pd
from datetime import date
import json

from google import genai

# ---------- CONFIG ----------
st.set_page_config(page_title="Expense Report Assistant", page_icon="🧾", layout="wide")

CATEGORIES = [
    "Travel / Local Transport",
    "Meals",
    "Accommodation",
    "Air Travel",
    "Office Supplies",
    "Client Entertainment",
    "Other",
]

# ---------- GEMINI CLIENT ----------
@st.cache_resource
def get_client():
    api_key = st.secrets.get("GEMINI_API_KEY", None)
    if not api_key:
        return None
    return genai.Client(api_key=api_key)

client = get_client()
MODEL_NAME = "gemini-flash-latest"  # check aistudio.google.com for current model names


def ai_categorize_and_explain(description, amount, category_hint):
    """Ask Gemini to suggest a category and, if relevant, explain a policy flag."""
    if client is None:
        return {"suggested_category": category_hint, "note": "AI unavailable (no API key set)."}

    prompt = f"""You are an expense-categorization assistant for a company finance team.
Given this expense, respond ONLY with JSON, no markdown, no backticks:
{{"suggested_category": one of {CATEGORIES}, "note": "one short plain-English sentence explaining the categorization or any concern"}}

Expense description: "{description}"
Amount: ₹{amount}
User-selected category: {category_hint}
"""
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config={"http_options": {"timeout": 15000}},  # 15 seconds, in milliseconds
        )
        text = response.text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        if data.get("suggested_category") not in CATEGORIES:
            data["suggested_category"] = category_hint
        return data
    except Exception as e:
        return {"suggested_category": category_hint, "note": f"AI error, showing fallback. ({e})"}


def check_policy(category, amount, has_receipt, air_class, description):
    """
    Deterministic, rule-based policy check (no AI involved).
    Returns (status, flags) where status is one of:
    "Compliant", "Requires Review", "Non-Compliant"
    """
    flags = []
    status = "Compliant"

    def flag(msg, level="Requires Review"):
        nonlocal status
        flags.append(msg)
        # Non-Compliant outranks Requires Review
        if level == "Non-Compliant" or status != "Non-Compliant":
            if level == "Non-Compliant":
                status = "Non-Compliant"
            elif status == "Compliant":
                status = "Requires Review"

    if amount <= 0:
        flag("Amount must be greater than zero.", "Non-Compliant")
        return status, flags

    if category == "Travel / Local Transport":
        if amount > 500 and not has_receipt:
            flag("Receipt required for travel expenses above ₹500.")
        if amount > 2500:
            flag("Exceeds ₹2,500 — requires manager approval.")

    elif category == "Meals":
        if amount > 1500:
            flag("Exceeds meal limit of ₹1,500 — requires manager approval.")
        if amount > 500 and not has_receipt:
            flag("Receipt required for meal expenses above ₹500.")
        if "alcohol" in description.lower():
            flag("Alcohol is not reimbursable under company policy.", "Non-Compliant")

    elif category == "Accommodation":
        if not has_receipt:
            flag("Receipt required for all accommodation expenses.")
        if amount > 7000:
            flag("Exceeds ₹7,000/night limit — requires manager approval.")

    elif category == "Air Travel":
        if not has_receipt:
            flag("Receipt/ticket required for air travel.")
        if air_class != "Economy":
            flag("Only Economy class is normally reimbursable.")

    elif category == "Office Supplies":
        if amount > 500 and not has_receipt:
            flag("Receipt required for office supplies above ₹500.")
        if amount > 5000:
            flag("Exceeds ₹5,000 — requires manager approval.")

    elif category == "Client Entertainment":
        if not has_receipt:
            flag("Receipt required for client entertainment.")
        if amount > 3000:
            flag("Exceeds ₹3,000 limit — requires manager approval.")
        if not description.strip():
            flag("Business purpose must be provided in the description.")

    elif category == "Other":
        flag("No predefined policy rule for 'Other' — always needs manual review.")

    return status, flags


STATUS_STYLE = {
    "Compliant": ("✅", "success"),
    "Requires Review": ("⚠️", "warning"),
    "Non-Compliant": ("❌", "error"),
}

# ---------- SESSION STATE ----------
if "entries" not in st.session_state:
    st.session_state.entries = []

# ---------- UI ----------
st.title("🧾 Expense Report Assistant")
st.caption("Submit expenses, get AI-assisted categorization, and an instant compliance decision.")

with st.form("entry_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        entry_date = st.date_input("Date", value=date.today())
        category = st.selectbox("Category", CATEGORIES)
        amount = st.number_input("Amount (₹)", min_value=0.0, step=50.0, format="%.2f")
        air_class = st.selectbox(
            "Travel class (only applies to Air Travel)",
            ["N/A", "Economy", "Premium Economy", "Business", "First"],
            help="Only checked against policy when Category is 'Air Travel'.",
        )
    with col2:
        description = st.text_input(
            "Description / Business purpose",
            placeholder="e.g. Uber to airport for client meeting",
            help="For Client Entertainment, this also serves as the required business purpose.",
        )
        has_receipt = st.checkbox("Receipt attached?")
    submitted = st.form_submit_button("Submit Expense")

    if submitted:
        if not description.strip():
            st.error("Please add a description before submitting.")
        elif amount <= 0:
            st.error("Amount must be greater than zero.")
        else:
            ai_result = ai_categorize_and_explain(description, amount, category)
            status, flags = check_policy(category, amount, has_receipt, air_class, description)

            entry = {
                "Date": str(entry_date),
                "Description": description,
                "Category (you)": category,
                "Category (AI suggests)": ai_result.get("suggested_category", category),
                "Amount": amount,
                "Receipt": "Yes" if has_receipt else "No",
                "AI Note": ai_result.get("note", ""),
                "Status": status,
                "Reasons": "; ".join(flags) if flags else "No policy violations detected.",
            }
            st.session_state.entries.append(entry)

            icon, kind = STATUS_STYLE[status]
            getattr(st, kind)(f"{icon} **{status.upper()}** — {entry['Reasons']}")

# ---------- TABLE + SUMMARY ----------
st.divider()
st.subheader("Submitted Expenses")

if st.session_state.entries:
    df = pd.DataFrame(st.session_state.entries)

    def style_status(val):
        colors = {"Compliant": "#1a3a1a", "Requires Review": "#4a3a10", "Non-Compliant": "#4a1a1a"}
        return f"background-color: {colors.get(val, '')}"

    st.dataframe(df.style.map(style_status, subset=["Status"]), use_container_width=True)

    total = df["Amount"].sum()
    needs_review = df[df["Status"] != "Compliant"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Submitted", f"₹{total:,.2f}")
    c2.metric("Entries", len(df))
    c3.metric("Needs Review / Non-Compliant", len(needs_review))

    if not needs_review.empty:
        st.warning("These entries are not auto-approved and need a human to look at them:")
        st.dataframe(needs_review[["Description", "Amount", "Status", "Reasons"]], use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download as CSV", csv, "expense_report.csv", "text/csv")

    if st.button("Clear all entries"):
        st.session_state.entries = []
        st.rerun()
else:
    st.info("No expenses submitted yet. Add one above.")

st.divider()
with st.expander("📋 Policy reference"):
    st.markdown("""
| Category | Rule |
|---|---|
| Travel / Local Transport | ≤₹500 no receipt needed. >₹500 needs a receipt. >₹2,500 needs manager approval. |
| Meals | Max ₹1,500/expense. Receipt required above ₹500. No alcohol. |
| Accommodation | Max ₹7,000/night. Receipt always required. |
| Air Travel | Economy only. Receipt/ticket always required. |
| Office Supplies | ≤₹5,000 normally fine. Receipt required above ₹500. |
| Client Entertainment | Max ₹3,000. Receipt required, and the Description field must state a business purpose. |
| Other | Always requires manual review. |
""")

st.caption(
    "⚠️ This tool flags policy issues and suggests a status — it does not grant final approval. "
    "A human approver should review every 'Requires Review' or 'Non-Compliant' item. "
    "Your inputs are sent to Google's Gemini API for categorization."
)