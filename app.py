import streamlit as st
import pandas as pd
from datetime import date
import json

from google import genai

# ---------- CONFIG ----------
st.set_page_config(page_title="Expense Report Assistant", page_icon="🧾", layout="wide")

MEAL_LIMIT = 1500          # ₹ per entry before approval needed
TRAVEL_RECEIPT_THRESHOLD = 500  # ₹ above which a receipt is required
CATEGORIES = ["Travel", "Meals", "Software", "Office Supplies", "Client Entertainment", "Other"]

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
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        text = response.text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        if data.get("suggested_category") not in CATEGORIES:
            data["suggested_category"] = category_hint
        return data
    except Exception as e:
        return {"suggested_category": category_hint, "note": f"AI error, showing fallback. ({e})"}


def check_policy(category, amount, has_receipt):
    """Simple rule-based policy check. Deterministic, not AI-driven."""
    flags = []
    if category == "Meals" and amount > MEAL_LIMIT:
        flags.append(f"Exceeds meal limit of ₹{MEAL_LIMIT} — needs manager approval.")
    if category == "Travel" and amount > TRAVEL_RECEIPT_THRESHOLD and not has_receipt:
        flags.append(f"Travel expense over ₹{TRAVEL_RECEIPT_THRESHOLD} requires a receipt.")
    if category == "Client Entertainment" and "alcohol" in st.session_state.get("_last_desc", "").lower():
        flags.append("Alcohol is not reimbursable under company policy.")
    if amount <= 0:
        flags.append("Amount must be greater than zero.")
    return flags


# ---------- SESSION STATE ----------
if "entries" not in st.session_state:
    st.session_state.entries = []

# ---------- UI ----------
st.title("🧾 Expense Report Assistant")
st.caption("Submit expenses, get AI-assisted categorization, and see policy flags instantly.")

with st.form("entry_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        entry_date = st.date_input("Date", value=date.today())
        category = st.selectbox("Category", CATEGORIES)
        amount = st.number_input("Amount (₹)", min_value=0.0, step=50.0, format="%.2f")
    with col2:
        description = st.text_input("Description", placeholder="e.g. Uber to airport for client meeting")
        has_receipt = st.checkbox("Receipt attached?")
    submitted = st.form_submit_button("Submit Expense")

    if submitted:
        if not description.strip():
            st.error("Please add a description before submitting.")
        elif amount <= 0:
            st.error("Amount must be greater than zero.")
        else:
            st.session_state["_last_desc"] = description
            ai_result = ai_categorize_and_explain(description, amount, category)
            flags = check_policy(category, amount, has_receipt)

            entry = {
                "Date": str(entry_date),
                "Description": description,
                "Category (you)": category,
                "Category (AI suggests)": ai_result.get("suggested_category", category),
                "Amount": amount,
                "Receipt": "Yes" if has_receipt else "No",
                "AI Note": ai_result.get("note", ""),
                "Policy Flags": "; ".join(flags) if flags else "None",
            }
            st.session_state.entries.append(entry)
            st.success("Expense added below.")

# ---------- TABLE + SUMMARY ----------
st.divider()
st.subheader("Submitted Expenses")

if st.session_state.entries:
    df = pd.DataFrame(st.session_state.entries)
    st.dataframe(df, use_container_width=True)

    total = df["Amount"].sum()
    flagged = df[df["Policy Flags"] != "None"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Submitted", f"₹{total:,.2f}")
    c2.metric("Entries", len(df))
    c3.metric("Flagged for Review", len(flagged))

    if not flagged.empty:
        st.warning("Some entries need manager approval or are missing documentation:")
        st.dataframe(flagged[["Description", "Amount", "Policy Flags"]], use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download as CSV", csv, "expense_report.csv", "text/csv")

    if st.button("Clear all entries"):
        st.session_state.entries = []
        st.rerun()
else:
    st.info("No expenses submitted yet. Add one above.")

st.divider()
st.caption(
    "⚠️ This tool flags policy issues and suggests categories — it does not grant final approval. "
    "A human approver should review all flagged items. Your inputs are sent to Google's Gemini API for categorization."
)